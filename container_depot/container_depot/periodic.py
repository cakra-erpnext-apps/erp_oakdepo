"""Periodic Test Order — the M&R-style work / billing flow for a container's periodic
pressure test (2,5Y / 5Y).

Mirrors ``container_depot/mr.py``: an owner-approval status machine (Draft → Service Setup →
Pending Approval → Approved → In Progress → Completed, + Rejected / Revision / Cancelled)
over Used Items priced from the owner's Item Price. On completion the order advances
``Container.next_pt_due`` — so the **Container master is the single source of truth** for
"when is the next test due" (the reminder cron + dashboard KPI read it there), and the
Completed orders themselves are the test history.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, today

from container_depot.container_depot.exceptions import AlreadySettled

# Read helpers shared with M&R (doctype-agnostic): stock on-hand, photo-JSON parse, input
# cleaners, and the tank-spec field list. Reused rather than re-defined so the two flows
# stay byte-for-byte consistent (container_depot/mr.py is the origin).
from container_depot.container_depot.mr import (
	_CONTAINER_FIELDS,
	_as_bool,
	_clean,
	_on_hand,
	_photos_list,
)
from container_depot.container_depot.user_branch import assert_in_user_branch, get_user_depots

# Periodic-test interval, in months, keyed by test type (same as the legacy Periodic Test).
PT_INTERVAL_MONTHS = {"2,5Y": 30, "5Y": 60}

# Owner-approval status machine — identical shape to M&R (container_depot/mr.MR_TRANSITIONS).
# "Draft" appears on every in-flight status so Admin Ops can rewind a mis-entered order
# (reopen_to_draft); Completed is terminal (parts issued + due-date pushed → Cancel instead).
PT_TRANSITIONS = {
	"Draft": ["Service Setup", "Approved", "Cancelled"],
	"Revision Requested": ["Service Setup", "Approved", "Draft", "Cancelled"],
	"Service Setup": ["Pending Approval", "Draft", "Approved", "Cancelled"],
	"Pending Approval": ["Approved", "Rejected", "Revision Requested", "Service Setup", "Draft", "Cancelled"],
	"Approved": ["In Progress", "Draft", "Cancelled"],
	"In Progress": ["Completed", "Draft", "Cancelled"],
	"Completed": [],
	"Rejected": ["Draft"],
	"Cancelled": [],
}

# Statuses the depot may still edit the estimate in (mirrors MR_EDITABLE_STATUSES).
PT_EDITABLE_STATUSES = ("Draft", "Revision Requested", "Service Setup")
# The PWA Periodic Test menu is an EXECUTION console: it only shows work already approved
# (Approved / In Progress), exactly like the M&R PWA. Estimate-building + the owner decision
# live in Desk.
PT_EXECUTION_STATUSES = ["Approved", "In Progress"]
# Open = everything not yet finished; History = the finished/terminal set.
PT_OPEN_STATUSES = ["Draft", "Revision Requested", "Service Setup", "Pending Approval", "Approved", "In Progress"]
PT_HISTORY_STATUSES = ["Completed", "Rejected", "Cancelled"]

# Worklist columns (the container_no / principal / test_type / due_date the card shows).
_LIST_FIELDS = [
	"name", "container", "container_no", "status", "principal", "depot",
	"test_type", "periodic_date", "due_date", "total_cost", "creation",
]


def _resolve_company():
	return frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")


def issue_parts_stock(order):
	"""Issue the order's approved stockable Used Items (Jenis = Part) out of each row's gudang
	as a Material Issue. Returns the Stock Entry name, or None when nothing is stockable.
	Mirrors ``container_depot/mr._issue_parts_stock`` (per-row warehouse). Most periodic lines are
	Jasa (test fee / cert survey) with nothing to issue — this is a no-op then."""
	lines = []
	for r in order.used_items or []:
		if (r.get("decision") or "Pending") == "Rejected":
			continue
		if not r.item or flt(r.quantity) <= 0:
			continue
		item = frappe.db.get_value("Item", r.item, ["is_stock_item", "stock_uom"], as_dict=True)
		if not item or not item.is_stock_item:
			continue
		wh = r.get("warehouse")
		if not wh:
			frappe.throw(_("Baris {0} ({1}) belum punya Gudang. Pilih gudangnya dulu.").format(r.idx, r.item))
		lines.append((r.item, flt(r.quantity), item.stock_uom, wh))
	if not lines:
		return None

	company = _resolve_company()
	if not company:
		frappe.throw(_("Tidak ada Company default untuk mengeluarkan part dari stok."))
	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Material Issue"
	se.company = company
	warehouses = {wh for *_, wh in lines}
	if len(warehouses) == 1:
		se.from_warehouse = next(iter(warehouses))
	se.remarks = f"Periodic Test {order.name} • {order.container_no or order.container}"
	for item_code, qty, uom, wh in lines:
		se.append("items", {
			"item_code": item_code, "qty": qty, "s_warehouse": wh,
			"uom": uom, "stock_uom": uom, "conversion_factor": 1,
		})
	se.insert(ignore_permissions=True)
	se.submit()
	return se.name


def reopen_to_draft(periodic_test_order, note=None):
	"""Admin-Ops rewind of an in-flight order back to an editable Draft (fix a wrong input),
	from Service Setup / Pending Approval / Approved / In Progress / Rejected / Revision.
	Blocked once Completed (parts issued + due-date pushed → Cancel instead). Mirrors
	``container_depot/mr.reopen_to_draft``."""
	REOPENABLE = ("Service Setup", "Pending Approval", "Approved", "In Progress", "Rejected", "Revision Requested")
	doc = frappe.get_doc("Periodic Test Order", periodic_test_order)
	if doc.status not in REOPENABLE:
		frappe.throw(_("Periodic Test {0} tidak bisa dikembalikan ke Draft dari status {1}.").format(doc.name, doc.status))
	for row in doc.used_items or []:
		row.decision = "Pending"
		row.owner_remark = None
	doc.status = "Draft"
	doc.requested_on = doc.decided_on = doc.decided_by = None
	doc.save(ignore_permissions=True)
	doc.add_comment("Comment", _("Dikembalikan ke Draft") + (f": {note}" if note else ""))
	return {"success": True, "name": doc.name, "status": doc.status}


# --- PWA execution console (mirrors container_depot/mr.py) ------------------------
# The functions below back the ESS PWA wrappers (ess/periodic.py). Kept free of
# @frappe.whitelist like container_depot/mr.py — the endpoint layer adds auth + whitelisting.


def _guard(container) -> None:
	"""Block Periodic Test actions on a container outside the caller's branch."""
	assert_in_user_branch(depot=frappe.db.get_value("Container", container, "depot"))


def _worklist(statuses, order_by, start, page_length, search, history=False) -> dict:
	"""Depot-scoped, searchable, paginated Periodic Test Order list. Shared by the open /
	execution / history feeds — they differ only in the status set + sort direction."""
	filters = {"status": ["in", statuses]}
	depots = get_user_depots()
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]
	or_filters = None
	search = (search or "").strip()
	if search and search.lower() != "undefined":
		or_filters = {"container_no": ["like", f"%{search}%"], "name": ["like", f"%{search}%"]}
	fields = list(_LIST_FIELDS)
	if history:
		fields.append("completion_date")
	items = frappe.get_all(
		"Periodic Test Order", filters=filters, or_filters=or_filters,
		fields=fields, order_by=order_by,
		limit_start=cint(start), limit_page_length=cint(page_length),
	)
	return {"items": items, "total": frappe.db.count("Periodic Test Order", filters)}


def list_open_pt_orders(start=0, page_length=20, search=None) -> dict:
	"""All in-flight Periodic Test Orders (Draft … In Progress) — the full worklist. FIFO."""
	return _worklist(PT_OPEN_STATUSES, "creation asc", start, page_length, search)


def list_pt_execution(start=0, page_length=20, search=None) -> dict:
	"""Approved / In Progress Periodic Test Orders — the PWA execution worklist (start -> done)."""
	return _worklist(PT_EXECUTION_STATUSES, "creation asc", start, page_length, search)


def list_pt_history(start=0, page_length=10, search=None) -> dict:
	"""Finished Periodic Test Orders (Completed / Rejected / Cancelled) — newest first."""
	return _worklist(PT_HISTORY_STATUSES, "creation desc", start, page_length, search, history=True)


def get_pt_order_detail(periodic_test_order) -> dict:
	"""Everything the PWA form needs: the test info (type / date / next due), the Used Items
	(service or part, qty, gudang, decision, photos) and the tank spec. No EIR damages — a
	periodic test has none (that is the one shape difference from the M&R detail)."""
	doc = frappe.get_doc("Periodic Test Order", periodic_test_order)
	_guard(doc.container)
	c = frappe.db.get_value("Container", doc.container, _CONTAINER_FIELDS, as_dict=True) or frappe._dict()

	used_items = [{
		"item": r.item, "item_name": r.item_name, "is_stock_item": r.is_stock_item,
		"line_type": r.line_type, "quantity": r.quantity, "remark": r.remark,
		"warehouse": r.warehouse,
		"decision": r.decision or "Pending", "owner_remark": r.owner_remark,
		"item_rate": r.item_rate, "item_amount": r.item_amount,
		"amount": r.amount, "currency": r.currency,
		"photos": _photos_list(r.photos),
		"on_hand": _on_hand(r.item, r.warehouse) if r.item and r.is_stock_item and r.warehouse else None,
	} for r in doc.used_items]

	return {
		"name": doc.name,
		"status": doc.status,
		"actions": PT_TRANSITIONS.get(doc.status, []),
		"container": doc.container,
		"container_no": doc.container_no or c.container_no,
		"technician": doc.technician,
		"reff_doc": doc.reff_doc,
		"remarks": doc.remarks,
		"stock_entry": doc.stock_entry,
		# Test info (the periodic-specific surface).
		"test_type": doc.test_type,
		"periodic_date": str(doc.periodic_date) if doc.periodic_date else None,
		"due_date": str(doc.due_date) if doc.due_date else None,
		"last_pt_type": doc.last_pt_type,
		"last_pt_date": str(doc.last_pt_date) if doc.last_pt_date else None,
		# Owner-approval surface.
		"total_cost": doc.total_cost,
		"owner_note": doc.owner_note,
		"requested_on": str(doc.requested_on) if doc.requested_on else None,
		"decided_on": str(doc.decided_on) if doc.decided_on else None,
		"revision_no": doc.revision_no,
		# Tank spec (read-only).
		"tank_type": c.container_type,
		"client": c.principal,
		"capacity": c.capacity,
		"tare": c.tare_weight,
		"mgw": c.max_gross_weight,
		"previous_cargo": c.last_cargo,
		"date_of_manufacture": c.manufacture_date,
		"last_test_date": c.last_test_date,
		"used_items": used_items,
	}


def start_test(periodic_test_order):
	"""Move an Approved Periodic Test into work (In Progress). Approval is mandatory, so only
	Approved may start — mirrors ``mr.start_repair``."""
	doc = frappe.get_doc("Periodic Test Order", periodic_test_order)
	_guard(doc.container)
	if doc.status != "Approved":
		frappe.throw(_("Periodic Test harus Approved sebelum dimulai (status: {0}).").format(doc.status))
	doc.status = "In Progress"
	if not doc.start_date:
		doc.start_date = now_datetime()
	doc.save()
	return {"success": True, "name": doc.name, "status": doc.status}


def save_pt_order(periodic_test_order=None, periodic_date=None, technician=None, reff_doc=None, remarks=None, submit=False) -> dict:
	"""Record the test's outcome fields and, when ``submit`` is true, complete it — which fires
	the controller's ``_complete`` (issue approved parts, push ``Container.next_pt_due``, log the
	milestone). Completion is only allowed from In Progress. The Used Items themselves are
	read-only here (decided in Desk), exactly like the M&R execution console.

	``periodic_date`` (the date the test was actually done) drives the next due-date, so it
	defaults to today on completion when the tech has not set one — otherwise the due-date, and
	the whole reminder chain that reads it off the Container, would never advance."""
	if not periodic_test_order:
		frappe.throw(_("periodic_test_order is required."))
	doc = frappe.get_doc("Periodic Test Order", periodic_test_order)
	if doc.status in ("Completed", "Cancelled", "Rejected"):
		frappe.throw(_("Periodic Test sudah {0}.").format(doc.status), exc=AlreadySettled)
	_guard(doc.container)

	submitting = _as_bool(submit)
	if submitting and doc.status != "In Progress":
		frappe.throw(_("Periodic Test harus In Progress untuk diselesaikan (status: {0}).").format(doc.status))

	if periodic_date is not None:
		doc.periodic_date = periodic_date
	if technician is not None:
		doc.technician = _clean(technician)
	if reff_doc is not None:
		doc.reff_doc = reff_doc
	if remarks is not None:
		doc.remarks = remarks

	if submitting:
		if not doc.periodic_date:
			doc.periodic_date = getdate(today())
		doc.status = "Completed"
		if not doc.completion_date:
			doc.completion_date = now_datetime()

	# before_save -> _compute_due_date + calculate_totals; on_update -> _complete on Completed
	# (issue parts, push next_pt_due to the Container, log the activity).
	doc.save()
	return {
		"success": True,
		"name": doc.name,
		"status": doc.status,
		"total_cost": doc.total_cost,
		"stock_entry": doc.get("stock_entry"),
	}
