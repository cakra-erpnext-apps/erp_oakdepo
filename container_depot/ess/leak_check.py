"""ESS PWA endpoints for Leak Check — menu ``leak`` (create on ``Leak Check``: Team Survey,
SPV Lapangan, Admin Ops). Wajib ada sebelum gate-out, lihat ``gate.mark_gate_out``."""

from __future__ import annotations

import frappe
from frappe import _

from container_depot.container_depot import container_position
from container_depot.container_depot.user_branch import assert_in_user_branch
from container_depot.ess.guard import require_menu
from container_depot.ess.idempotency import guarded

MENU = "leak"


@frappe.whitelist(methods=["GET"])
def leak_tank_search(search=None, page_length=10):
	"""GET — cari tank (pencarian yang sama dengan Letak Tank)."""
	require_menu(MENU)
	return container_position.search_containers(search=search, page_length=page_length)


@frappe.whitelist(methods=["GET"])
def leak_list(status=None, search=None, depot=None, principal=None, day=None, sort=None,
			  start=0, page_length=20):
	"""GET — Leak Check orders, newest first, grouped by day on the screen."""
	require_menu(MENU)
	from container_depot.container_depot.doctype.leak_check.leak_check import list_leak_checks

	return list_leak_checks(status=status, search=search, depot=depot, principal=principal,
							day=day, sort=sort, start=start, page_length=page_length)


@frappe.whitelist(methods=["GET"])
def leak_detail(name=None):
	"""GET — one Leak Check with its photos."""
	require_menu(MENU)
	from container_depot.container_depot.doctype.leak_check.leak_check import get_leak_check_detail

	return get_leak_check_detail(name)


@frappe.whitelist(methods=["POST"])
def leak_record(container=None, photos=None, remarks=None, request_id=None, name=None):
	"""POST — simpan satu Leak Check. ``photos`` = ``[{photo, caption, is_leak}]``.

	``request_id``: endpoint ini INSERT, kiriman ulang di sinyal buruk jangan jadi dua."""
	require_menu(MENU)
	return guarded(request_id, lambda: _record(container, photos, remarks, name))


def _record(container, photos, remarks=None, name=None):
	"""``name`` = fill that Open order (the detail screen); else the container's Open order, or
	a fresh hand-made one."""
	if name:
		container = frappe.db.get_value("Leak Check", name, "container")
	if not container:
		frappe.throw(_("Container wajib diisi."))
	assert_in_user_branch(depot=frappe.db.get_value("Container", container, "depot"))
	if isinstance(photos, str):
		photos = frappe.parse_json(photos)
	rows = [
		{
			"photo": str(p.get("photo") or "").strip(),
			"caption": str(p.get("caption") or "").strip() or None,
			"is_leak": 1 if p.get("is_leak") else 0,
		}
		for p in (photos or [])
		if isinstance(p, dict) and str(p.get("photo") or "").strip()
	]
	# Fill the container's Open order (born on the Tank In bon); a tank without one gets a
	# fresh, hand-made Leak Check.
	from container_depot.container_depot.doctype.leak_check.leak_check import open_leak_check

	name = name or open_leak_check(container)
	doc = frappe.get_doc("Leak Check", name) if name else frappe.new_doc("Leak Check")
	if doc.get("status") == "Completed":
		frappe.throw(_("Leak Check {0} sudah selesai.").format(doc.name))
	doc.container = container
	doc.remarks = (str(remarks).strip() if remarks else "") or None
	doc.set("photos", rows)
	doc.save()  # NOT ignore_permissions — DocPerm is the gate.
	return {"success": True, "name": doc.name, "has_leak": doc.has_leak}
