"""ESS PWA repair tracking — Feature F3 (Repair Tracking & Estimate).

Read: list a tank's Repair Orders with their costed estimate lines, server-side
``total_cost``, billing status, and the valid next statuses.

Write: ``set_repair_status`` advances a Repair Order along an allowed transition
and saves it — the Repair Order controller's ``before_save`` recomputes
``total_cost`` and propagates the container status, so the PWA never reimplements
costing or the state machine (PRD §F3). Approving/rejecting also syncs the linked
EIR's ``approval_status`` for auditability.
"""

from __future__ import annotations

import frappe

from container_depot.api import _require_authenticated_user
from container_depot.operations import mr

# Allowed Repair Order status transitions — single source of truth in operations/mr.py
# (the owner-approval state machine, shared by the controller, PWA, and Desk).
REPAIR_TRANSITIONS = mr.MR_TRANSITIONS

_ITEM_FIELDS = [
	"part_description",
	"quantity",
	"unit_price",
	"total_price",
	"labor_hours",
	"labor_rate",
	"labor_total",
]


@frappe.whitelist(methods=["GET"])
def get_tank_repairs(container):
	"""List Repair Orders for a tank with estimate lines + totals (read-only).

	GET /api/method/container_depot.ess.repairs.get_tank_repairs
	"""
	_require_authenticated_user()
	frappe.has_permission("Container", doc=container, ptype="read", throw=True)

	repairs = []
	for r in frappe.get_list(
		"Repair Order",
		filters={"container": container},
		fields=[
			"name",
			"repair_order_id",
			"status",
			"billing_status",
			"technician",
			"total_cost",
			"start_date",
			"completion_date",
			"inspection",
			"creation",
		],
		order_by="creation desc",
		limit_page_length=0,
	):
		items = frappe.get_all(
			"Repair Estimate Item",
			filters={"parent": r.name, "parenttype": "Repair Order"},
			fields=_ITEM_FIELDS,
			order_by="idx asc",
		)
		repairs.append(
			{
				"name": r.name,
				"repair_order_id": r.repair_order_id,
				"status": r.status,
				"billing_status": r.billing_status,  # read-only in ESS
				"technician": r.technician,
				"total_cost": r.total_cost,
				"start_date": str(r.start_date) if r.start_date else None,
				"completion_date": str(r.completion_date) if r.completion_date else None,
				"inspection": r.inspection,
				"next_statuses": REPAIR_TRANSITIONS.get(r.status, []),
				"items": items,
			}
		)

	return {"success": True, "container": container, "repairs": repairs}


@frappe.whitelist(methods=["POST"])
def set_repair_status(repair_order, status):
	"""Advance a Repair Order to an allowed next status (approval workflow).

	Permission-checked (write on Repair Order). The save triggers the controller,
	which recomputes totals and updates the container — no logic duplicated here.

	POST /api/method/container_depot.ess.repairs.set_repair_status
	"""
	_require_authenticated_user()
	frappe.has_permission("Repair Order", doc=repair_order, ptype="write", throw=True)

	doc = frappe.get_doc("Repair Order", repair_order)
	allowed = REPAIR_TRANSITIONS.get(doc.status, [])
	if status not in allowed:
		frappe.throw(
			frappe._("Cannot change status from {0} to {1}.").format(doc.status, status),
			frappe.ValidationError,
		)

	doc.status = status
	doc.save()  # before_save -> calculate_totals() + update_container_status()

	# Auditable approval: reflect the decision on the linked EIR.
	if doc.inspection:
		if status == "Approved":
			frappe.db.set_value("Inspection", doc.inspection, "approval_status", "Approved")
		elif status == "Cancelled":
			frappe.db.set_value("Inspection", doc.inspection, "approval_status", "Rejected")

	return {
		"success": True,
		"repair_order": doc.name,
		"status": doc.status,
		"total_cost": doc.total_cost,
		"next_statuses": REPAIR_TRANSITIONS.get(doc.status, []),
	}


# --- PWA M&R menu (Maintenance & Repair) -------------------------------------
# Thin wrappers over operations.mr — the M&R worklist the team works in the PWA
# (auto-created from EIRs with damage). All resolution/build logic lives in mr.py.


# The PWA M&R menu is the field/cleaning division's EXECUTION console: it may only start /
# complete already-approved work. Estimate-building, the offer to the owner and the owner's
# decision live in Desk (ERP). The bypass is Admin-Ops only.
BYPASS_ROLES = {"Admin Ops", "System Manager"}


def _require_admin_ops() -> None:
	_require_authenticated_user()
	if set(frappe.get_roles(frappe.session.user)).isdisjoint(BYPASS_ROLES):
		frappe.throw(
			frappe._("Hanya Admin Ops yang boleh menyetujui langsung (bypass owner)."),
			frappe.PermissionError,
		)


@frappe.whitelist(methods=["GET"])
def mr_orders(start=0, page_length=20, search=None):
	"""GET /api/v1/ess/mr-orders — open M&R worklist (depot-scoped)."""
	_require_authenticated_user()
	return mr.list_open_mr_orders(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def mr_execution(start=0, page_length=20, search=None):
	"""GET /api/v1/ess/mr-execution — the PWA execution worklist: Approved / In Progress only."""
	_require_authenticated_user()
	return mr.list_mr_execution(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def mr_history(start=0, page_length=10, search=None):
	"""GET /api/v1/ess/mr-history — finished (Completed/Rejected/Cancelled) M&R orders."""
	_require_authenticated_user()
	return mr.list_mr_history(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def mr_order_detail(repair_order=None):
	"""GET /api/v1/ess/mr-order-detail — one M&R's damages (EIR copy) + used items + warehouses."""
	_require_authenticated_user()
	return mr.get_mr_order_detail(repair_order)


@frappe.whitelist(methods=["GET"])
def mr_warehouses(repair_order=None, container=None):
	"""GET /api/v1/ess/mr-warehouses — branch-filtered source-warehouse options."""
	_require_authenticated_user()
	return mr.list_warehouses(repair_order=repair_order, container=container)


@frappe.whitelist(methods=["GET"])
def mr_items(search=None, repair_order=None, start=0, page_length=20):
	"""GET /api/v1/ess/mr-items — Item picker (service or part) priced in the owner's list."""
	_require_authenticated_user()
	return mr.mr_item_search(search=search, repair_order=repair_order, start=start, page_length=page_length)


@frappe.whitelist(methods=["POST"])
def mr_submit_approval(repair_order=None):
	"""POST /api/v1/ess/mr-submit-approval — submit the estimate to the owner (Pending Approval)."""
	_require_authenticated_user()
	frappe.has_permission("Repair Order", doc=repair_order, ptype="write", throw=True)
	return mr.submit_for_approval(repair_order)


@frappe.whitelist(methods=["POST"])
def mr_decision(repair_order=None, decision=None, line_decisions=None, note=None):
	"""POST /api/v1/ess/mr-decision — record the owner's decision (Approved / Rejected /
	Revision Requested), with optional per-line decisions (partial approval)."""
	_require_authenticated_user()
	frappe.has_permission("Repair Order", doc=repair_order, ptype="write", throw=True)
	return mr.record_decision(repair_order, decision, line_decisions=line_decisions, note=note)


@frappe.whitelist(methods=["POST"])
def mr_bypass_approval(repair_order=None, note=None):
	"""POST /api/v1/ess/mr-bypass-approval — Admin-Ops direct approval (skip the owner):
	Draft / Revision Requested -> Approved. Role-guarded to Admin Ops."""
	_require_admin_ops()
	frappe.has_permission("Repair Order", doc=repair_order, ptype="write", throw=True)
	return mr.bypass_approval(repair_order, note=note)


@frappe.whitelist(methods=["POST"])
def mr_start(repair_order=None):
	"""POST /api/v1/ess/mr-start — start the Approved M&R (In Progress)."""
	_require_authenticated_user()
	return mr.start_repair(repair_order)


@frappe.whitelist(methods=["POST"])
def mr_order_save(repair_order=None, used_items=None, technician=None, warehouse=None, reff_doc=None, remarks=None, submit=False):
	"""POST /api/v1/ess/mr-order-save — save used items + fields (submit=1 completes + issues stock)."""
	_require_authenticated_user()
	return mr.save_mr_order(
		repair_order=repair_order, used_items=used_items,
		technician=technician, warehouse=warehouse, reff_doc=reff_doc, remarks=remarks, submit=submit,
	)
