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


@frappe.whitelist(methods=["POST"])
def leak_record(container=None, photos=None, remarks=None, request_id=None):
	"""POST — simpan satu Leak Check. ``photos`` = ``[{photo, caption, is_leak}]``.

	``request_id``: endpoint ini INSERT, kiriman ulang di sinyal buruk jangan jadi dua."""
	require_menu(MENU)
	return guarded(request_id, lambda: _record(container, photos, remarks))


def _record(container, photos, remarks=None):
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

	name = open_leak_check(container)
	doc = frappe.get_doc("Leak Check", name) if name else frappe.new_doc("Leak Check")
	doc.container = container
	doc.remarks = (str(remarks).strip() if remarks else "") or None
	doc.set("photos", rows)
	doc.save()  # NOT ignore_permissions — DocPerm is the gate.
	return {"success": True, "name": doc.name, "has_leak": doc.has_leak}
