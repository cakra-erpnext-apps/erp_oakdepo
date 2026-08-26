"""Pekerjaan lapangan dikunci ke orang yang menekan "Mulai".

Begitu sebuah EIR / Cleaning Order / M&R dimulai, order itu jadi pegangan operator yang
memulainya: hilang dari worklist PWA operator lain, dan kalau mereka tetap masuk lewat
tautan notifikasi (yang dikirim ke seluruh role, bukan ke satu orang) endpoint-nya menolak
dengan :class:`ClaimedByAnother` — PWA menampilkan toast dan memulangkan mereka ke worklist.

Tujuannya bukan keamanan: Desk tetap menampilkan semua dokumen ke siapa pun yang berwenang,
dan itu memang yang dipakai untuk mengawasi. Ini pagar lapangan supaya satu tangki tidak
dikerjakan dua orang dan jelas siapa yang memegangnya.

Yang TIDAK diklaim: daftar "Diajukan Review" dan Riwayat. Order yang sudah dikirim untuk
review bukan lagi milik si operator — siapa pun di branch boleh menariknya kembali atau
membacanya, persis seperti sebelum ada modul ini.

Bypass ada di ``CLAIM_BYPASS_ROLES``: Admin Ops adalah backstop ops yang turun ke lapangan
untuk membereskan job macet (lihat ``install.PWA_OFFICE_ROLES``), System Manager /
Administrator jelas. Menambah SPV Lapangan cukup satu baris di sini.
"""

from __future__ import annotations

import frappe
from frappe import _

from container_depot.container_depot.exceptions import ClaimedByAnother

CLAIM_BYPASS_ROLES = {"System Manager", "Admin Ops"}


def sees_all_work(user=None) -> bool:
	"""Boleh melihat/membuka pekerjaan yang sudah diklaim akun lain?"""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return not set(frappe.get_roles(user)).isdisjoint(CLAIM_BYPASS_ROLES)


def filter_claimed(items: list, field: str, user=None) -> list:
	"""Buang baris yang diklaim akun lain. Yang belum diklaim (kolomnya kosong) selalu tampil.

	Disaring di Python, bukan di SQL: ketiga worklist sudah menarik seluruh daftar untuk
	diurutkan berdasarkan target lift-on, jadi tidak ada query tambahan — dan filter ini
	harus dihitung SEBELUM ``total`` supaya angka di tab worklist cocok dengan isinya.
	"""
	user = user or frappe.session.user
	if sees_all_work(user):
		return items
	return [r for r in items if not r.get(field) or r.get(field) == user]


def guard_claim(claimed_by, subject: str) -> None:
	"""Tolak kalau ``claimed_by`` akun lain — dipakai endpoint buka / mulai / simpan.

	Yang belum diklaim lolos: klaim baru terjadi saat "Mulai" ditekan, dan yang menekan
	duluan yang menang.
	"""
	user = frappe.session.user
	if not claimed_by or claimed_by == user or sees_all_work(user):
		return
	frappe.throw(
		_("{0} sedang dikerjakan oleh {1}. Kalau memang harus diambil alih, minta Admin Ops.").format(
			subject, worker_name(claimed_by)
		),
		exc=ClaimedByAnother,
	)


def worker_name(user: str | None) -> str:
	"""Nama yang enak dibaca di toast — jatuh ke id user kalau full_name kosong."""
	if not user:
		return ""
	return frappe.db.get_value("User", user, "full_name") or user
