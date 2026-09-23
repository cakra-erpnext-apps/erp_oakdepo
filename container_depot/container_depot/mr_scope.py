"""M&R vs Periodic Test: dua menu, dua tim, SATU doctype (Repair Order).

Uji berkala dikerjakan dengan alur yang persis sama dengan repair — estimasi, approval owner,
part, foto, review, tagihan — jadi ia tetap sebuah Repair Order ber-``job_type = Periodic
Test``, bukan doctype kembaran yang harus diperbaiki dua kali setiap ada bug. Yang dipisah
hanya siapa yang melihat baris mana, dan itu seluruhnya ada di modul ini:

* ``TEAM_JOB_TYPE`` — tim lapangan yang hanya mengerjakan satu jenis. Role lain yang memegang
  izin baca Repair Order (SPV Lapangan, Admin Ops, Team EIR, …) melihat keduanya.
* hook ``permission_query_conditions`` / ``has_permission`` (hooks.py) — list dan dokumen
  tunggal, di Desk maupun di endpoint PWA yang memakai ``frappe.has_permission``.
* ``MENU_JOB_TYPE`` — menu PWA ``mr`` dan ``periodic`` sama-sama bertumpu pada write Repair
  Order (ess.context._MENU); jenis yang boleh dilihat yang memisahkan keduanya.
"""

from __future__ import annotations

import frappe

REPAIR = "Repair"
PERIODIC = "Periodic Test"

TEAM_JOB_TYPE = {"Team Repair": REPAIR, "Team Periodic": PERIODIC}

# Menu PWA -> jenis pekerjaan yang dikerjakannya, dan kebalikannya untuk rute notifikasi.
MENU_JOB_TYPE = {"mr": REPAIR, "periodic": PERIODIC}
JOB_TYPE_MENU = {v: k for k, v in MENU_JOB_TYPE.items()}


def _roles_reading_repair_order() -> set:
	# Custom DocPerm membayangi JSON sejak seeder izin berjalan (lihat install.setup_permissions),
	# jadi itu satu-satunya tabel yang perlu dibaca. Di-cache per request: hook izin dipanggil
	# per baris.
	cached = getattr(frappe.local, "_mr_scope_readers", None)
	if cached is None:
		cached = set(frappe.get_all(
			"Custom DocPerm", filters={"parent": "Repair Order", "read": 1}, pluck="role"
		))
		frappe.local._mr_scope_readers = cached
	return cached


def allowed_job_types(user: str | None = None) -> set | None:
	"""Jenis Repair Order yang boleh dilihat ``user``. ``None`` = semua."""
	user = user or frappe.session.user
	if user == "Administrator":
		return None
	roles = set(frappe.get_roles(user))
	teams = roles & TEAM_JOB_TYPE.keys()
	if not teams:
		return None
	# Tim + role lain yang juga membaca Repair Order (mis. SPV) = tidak dibatasi.
	if (roles - TEAM_JOB_TYPE.keys()) & _roles_reading_repair_order():
		return None
	return {TEAM_JOB_TYPE[r] for r in teams}


def may_see(job_type: str | None, user: str | None = None) -> bool:
	allowed = allowed_job_types(user)
	return allowed is None or (job_type or REPAIR) in allowed


def query_conditions(user=None, doctype=None) -> str:
	allowed = allowed_job_types(user)
	if allowed is None:
		return ""
	values = ", ".join(frappe.db.escape(v) for v in sorted(allowed))
	return f"`tabRepair Order`.`job_type` in ({values})"


def has_permission(doc, ptype=None, user=None, **kwargs) -> bool:
	return may_see(doc.get("job_type"), user)


def menu_for(job_type: str | None) -> str:
	"""Menu PWA pemilik sebuah order."""
	return JOB_TYPE_MENU.get(job_type or REPAIR, "mr")
