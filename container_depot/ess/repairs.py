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

# Allowed Repair Order status transitions (matches the doctype Select options).
REPAIR_TRANSITIONS = {
	"Draft": ["Pending Approval", "Cancelled"],
	"Pending Approval": ["Approved", "Cancelled"],
	"Approved": ["In Progress", "Cancelled"],
	"In Progress": ["Completed", "Cancelled"],
	"Completed": [],
	"Cancelled": [],
}

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
