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

from container_depot.ess.guard import require_menu
from container_depot.ess.idempotency import guarded
from container_depot.container_depot import mr
from container_depot.container_depot.container_activity import log_doc_note

# Allowed Repair Order status transitions — single source of truth in container_depot/mr.py
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
	require_menu("mr")
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
def set_repair_status(repair_order, status, note=None):
	"""Advance a Repair Order to an allowed next status (approval workflow).

	Permission-checked (write on Repair Order). The save triggers the controller,
	which recomputes totals and updates the container — no logic duplicated here.

	``note`` is an optional reason, written to the timeline. Cancelling is the most final
	thing that can happen to an M&R — every other backward step (Reject / Request Revision /
	reopen to Draft) records why, and this one used to be the exception.

	POST /api/method/container_depot.ess.repairs.set_repair_status
	"""
	require_menu("mr")
	frappe.has_permission("Repair Order", doc=repair_order, ptype="write", throw=True)

	doc = frappe.get_doc("Repair Order", repair_order)
	allowed = REPAIR_TRANSITIONS.get(doc.status, [])
	if status not in allowed:
		frappe.throw(
			frappe._("Cannot change status from {0} to {1}.").format(doc.status, status),
			frappe.ValidationError,
		)

	prev = doc.status
	doc.status = status
	doc.save()  # before_save -> calculate_totals() + update_container_status()

	# Audit trail — best-effort, must not block the transition.
	msg = frappe._("Status M&R {0} → {1} oleh {2}").format(prev, status, frappe.session.user)
	if note:
		msg += ": " + (note or "").strip()
	log_doc_note("Repair Order", doc.name, msg)

	# Auditable approval: reflect the decision on the linked EIR. Raw set_value, not
	# doc.save() — approval_status is not allow_on_submit, so saving a submitted EIR would
	# throw; that also means no Version row, hence the explicit timeline note.
	if doc.inspection:
		decision = {"Approved": "Approved", "Cancelled": "Rejected"}.get(status)
		if decision:
			frappe.db.set_value("Inspection", doc.inspection, "approval_status", decision)
			log_doc_note("Inspection", doc.inspection, frappe._(
				"Approval EIR: {0} — dari M&R {1} ({2}) oleh {3}"
			).format(decision, doc.name, status, frappe.session.user))

	return {
		"success": True,
		"repair_order": doc.name,
		"status": doc.status,
		"total_cost": doc.total_cost,
		"next_statuses": REPAIR_TRANSITIONS.get(doc.status, []),
	}


# --- PWA M&R menu (Maintenance & Repair) -------------------------------------
# Thin wrappers over container_depot.mr — the M&R worklist the team works in the PWA
# (auto-created from EIRs with damage). All resolution/build logic lives in mr.py.


# The PWA M&R menu is the field/cleaning division's EXECUTION console: it may only start /
# complete already-approved work. Estimate-building, the offer to the owner and the owner's
# decision live in Desk (ERP). The owner-approval bypass used to be Admin-Ops only; that
# role was deleted on 2026-08-05 pending a role redesign, so the bypass is System Manager
# only until the new model names a replacement — deliberately the narrow side, since this
# skips the tank owner's approval of what they will be charged for.
BYPASS_ROLES = {"System Manager"}


def _require_admin_ops() -> None:
	require_menu("mr")
	if set(frappe.get_roles(frappe.session.user)).isdisjoint(BYPASS_ROLES):
		frappe.throw(
			frappe._("Anda tidak berwenang menyetujui langsung (bypass owner)."),
			frappe.PermissionError,
		)


@frappe.whitelist(methods=["GET"])
def mr_orders(start=0, page_length=20, search=None):
	"""GET /api/v1/ess/mr-orders — open M&R worklist (depot-scoped)."""
	require_menu("mr")
	return mr.list_open_mr_orders(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def mr_execution(start=0, page_length=20, search=None):
	"""GET /api/v1/ess/mr-execution — the PWA execution worklist: Approved / In Progress only."""
	require_menu("mr")
	return mr.list_mr_execution(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def mr_pending_review(start=0, page_length=20, search=None):
	"""GET /api/v1/ess/mr-pending-review — M&R finished in the field, waiting for Desk to
	check the work and close it. Kept out of the worklist: it is no longer the team's turn."""
	require_menu("mr")
	return mr.list_review_mr_orders(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def mr_history(start=0, page_length=10, search=None):
	"""GET /api/v1/ess/mr-history — finished (Completed/Rejected/Cancelled) M&R orders."""
	require_menu("mr")
	return mr.list_mr_history(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def mr_order_detail(repair_order=None):
	"""GET /api/v1/ess/mr-order-detail — one M&R's damages (EIR copy) + used items."""
	require_menu("mr")
	return mr.get_mr_order_detail(repair_order)


@frappe.whitelist(methods=["GET"])
def mr_items(search=None, repair_order=None, start=0, page_length=20):
	"""GET /api/v1/ess/mr-items — Item picker (service or part) priced in the owner's list."""
	require_menu("mr")
	return mr.mr_item_search(search=search, repair_order=repair_order, start=start, page_length=page_length)


@frappe.whitelist()
def mr_item_pricing(repair_order=None, item=None):
	"""Cost breakdown for one item (defaults a Desk line). Whitelisted for GET (PWA) and POST
	(the Desk grid calls it via frappe.call, which defaults to POST)."""
	require_menu("mr")
	frappe.has_permission("Repair Order", doc=repair_order, ptype="read", throw=True)
	return mr.item_pricing(repair_order, item)


@frappe.whitelist(methods=["POST"])
def mr_publish_to_owner(repair_order=None):
	"""POST /api/v1/ess/mr-publish-to-owner — Admin Ops sends the estimate to the customer
	web: Draft / Revision Requested -> Pending Approval. Role-guarded to Admin Ops.

	The old ``mr_submit_approval`` (Draft -> Service Setup) is gone with the staging step it
	fed: Admin Ops is the first pair of eyes on an M&R, so Draft is already their desk."""
	_require_admin_ops()
	frappe.has_permission("Repair Order", doc=repair_order, ptype="write", throw=True)
	return mr.publish_to_owner(repair_order)


@frappe.whitelist(methods=["POST"])
def mr_withdraw_from_owner(repair_order=None, note=None):
	"""POST /api/v1/ess/mr-withdraw-from-owner — Admin Ops pulls the estimate back off the
	customer web ("tarik ulang"): Pending Approval -> Draft. Role-guarded to Admin Ops."""
	_require_admin_ops()
	frappe.has_permission("Repair Order", doc=repair_order, ptype="write", throw=True)
	return mr.withdraw_from_owner(repair_order, note=note)


@frappe.whitelist(methods=["POST"])
def mr_decision(repair_order=None, decision=None, line_decisions=None, note=None):
	"""POST /api/v1/ess/mr-decision — record the owner's decision (Approved / Rejected /
	Revision Requested), with optional per-line decisions (partial approval)."""
	require_menu("mr")
	frappe.has_permission("Repair Order", doc=repair_order, ptype="write", throw=True)
	return mr.record_decision(repair_order, decision, line_decisions=line_decisions, note=note)


@frappe.whitelist(methods=["POST"])
def mr_reopen_draft(repair_order=None, note=None):
	"""POST /api/v1/ess/mr-reopen-draft — Admin Ops rewinds an in-flight M&R back to an
	editable Draft (fix a wrong / missing input), from Pending Approval / Approved / Pending /
	In Progress / Pending Review / Rejected. Role-guarded to Admin Ops."""
	_require_admin_ops()
	frappe.has_permission("Repair Order", doc=repair_order, ptype="write", throw=True)
	return mr.reopen_to_draft(repair_order, note=note)


@frappe.whitelist(methods=["POST"])
def mr_bypass_approval(repair_order=None, note=None):
	"""POST /api/v1/ess/mr-bypass-approval — Admin-Ops direct approval (skip the owner):
	Draft / Revision Requested -> Approved. Role-guarded to Admin Ops."""
	_require_admin_ops()
	frappe.has_permission("Repair Order", doc=repair_order, ptype="write", throw=True)
	return mr.bypass_approval(repair_order, note=note)


@frappe.whitelist(methods=["POST"])
def mr_forward_to_team(repair_order=None):
	"""POST /api/v1/ess/mr-forward-to-team — Admin Ops hands an approved M&R to the workshop:
	Approved -> Pending. Only then does it appear on the PWA worklist."""
	_require_admin_ops()
	frappe.has_permission("Repair Order", doc=repair_order, ptype="write", throw=True)
	return mr.forward_to_team(repair_order)


@frappe.whitelist(methods=["POST"])
def mr_withdraw_review(repair_order=None):
	"""POST /api/v1/ess/mr-withdraw-review — the team pulls a finished job back to fix it:
	Pending Review -> In Progress. Nothing has left the warehouse yet."""
	require_menu("mr")
	frappe.has_permission("Repair Order", doc=repair_order, ptype="write", throw=True)
	return mr.withdraw_review(repair_order)


@frappe.whitelist(methods=["POST"])
def mr_request_revision(repair_order=None, reason=None, request_id=None):
	"""POST /api/v1/ess/mr-request-revision — the field team asks Admin Ops to open a CLOSED
	M&R again. Raises a request (timeline note + flag + notification); it changes no status.

	Menu + write, not Admin Ops: asking is the team's job. Acting on it is not — that is
	``mr_reopen_completed`` below."""
	require_menu("mr")
	frappe.has_permission("Repair Order", doc=repair_order, ptype="write", throw=True)
	return guarded(request_id, lambda: mr.request_revision(repair_order, reason=reason))


@frappe.whitelist(methods=["POST"])
def mr_reopen_completed(repair_order=None, note=None):
	"""POST /api/v1/ess/mr-reopen-completed — Admin Ops opens a closed M&R again:
	Completed -> In Progress. Refused once the order has reached an invoice."""
	_require_admin_ops()
	frappe.has_permission("Repair Order", doc=repair_order, ptype="write", throw=True)
	return mr.reopen_completed(repair_order, note=note)


@frappe.whitelist(methods=["POST"])
def mr_finalize(repair_order=None):
	"""POST /api/v1/ess/mr-finalize — Desk closes the job: Pending Review -> Completed (the
	team reported it done), or Approved -> Completed (it never needed dispatching).

	No stock moves here: the approved parts left the warehouse at approval."""
	require_menu("mr")
	frappe.has_permission("Repair Order", doc=repair_order, ptype="write", throw=True)
	return mr.finalize_repair(repair_order)


@frappe.whitelist(methods=["POST"])
def mr_start(repair_order=None, request_id=None):
	"""POST /api/v1/ess/mr-start — the team picks the job off its worklist: Pending -> In
	Progress. Only a job Admin Ops has handed over (``forward_to_team``) is startable."""
	require_menu("mr")
	return guarded(request_id, lambda: mr.start_repair(repair_order))


@frappe.whitelist(methods=["POST"])
def mr_order_save(
	repair_order=None, used_items=None, work_photos=None, technician=None, reff_doc=None,
	remarks=None, submit=False, request_id=None,
):
	"""POST /api/v1/ess/mr-order-save — save used items + fields. ``submit=1`` hands the
	finished job to Desk for review (In Progress -> Pending Review); it does NOT close the
	order — that is ``mr_finalize``.

	Each used item carries its own gudang; there is no order-level source warehouse to send.
	``work_photos`` is the evidence album — a separate list, editable while the work is live
	(see ``mr.MR_PHOTO_STATUSES``) rather than only while the estimate is.

	``request_id`` makes a replay safe: a lost response followed by a naive retry would
	otherwise raise a second sign-off under a second id — see ``ess/idempotency.py``."""
	require_menu("mr")
	return guarded(request_id, lambda: mr.save_mr_order(
		repair_order=repair_order, used_items=used_items, work_photos=work_photos,
		technician=technician, reff_doc=reff_doc, remarks=remarks, submit=submit,
	))
