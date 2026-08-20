"""ESS PWA Cleaning Order endpoints — thin ``@frappe.whitelist`` wrappers.

Per the integration rule (mirrors ``ess/inspections.py``): endpoints here only add
authentication + whitelisting + GET/POST gating; every bit of resolution/build logic
lives in ``container_depot.container_depot.cleaning``.
"""

from __future__ import annotations

import frappe

from container_depot.ess.guard import require_menu
from container_depot.ess.idempotency import guarded
from container_depot.container_depot import cleaning


@frappe.whitelist(methods=["GET"])
def cleaning_masters():
	"""GET /api/v1/ess/cleaning-masters — default sign-off remarks."""
	require_menu("cleaning")
	return cleaning.get_cleaning_masters()


@frappe.whitelist(methods=["GET"])
def cleaning_orders(start=0, page_length=20, search=None):
	"""GET /api/v1/ess/cleaning-orders — open Cleaning Orders worklist (depot-scoped)."""
	require_menu("cleaning")
	return cleaning.list_open_cleaning_orders(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def cleaning_history(start=0, page_length=10, search=None):
	"""GET /api/v1/ess/cleaning-history — finished (Completed/Cancelled) cleaning orders."""
	require_menu("cleaning")
	return cleaning.list_cleaning_history(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def cleaning_pending_review(start=0, page_length=20, search=None):
	"""GET /api/v1/ess/cleaning-pending-review — orders finished in the field and waiting for
	Admin Ops to review + Submit on the Desk. Branch-scoped like the worklist."""
	require_menu("cleaning")
	return cleaning.list_review_cleaning_orders(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def cleaning_order_detail(cleaning_order=None):
	"""GET /api/v1/ess/cleaning-order-detail — one order's cleanliness state + tank spec."""
	require_menu("cleaning")
	return cleaning.get_cleaning_order_detail(cleaning_order)


@frappe.whitelist(methods=["POST"])
def cleaning_withdraw_review(cleaning_order=None, request_id=None):
	"""POST /api/v1/ess/cleaning-withdraw-review — pull a "Pending Review" order back to
	In_Progress so the operator can fix it before Admin Ops finalizes."""
	require_menu("cleaning")
	return guarded(request_id, lambda: cleaning.withdraw_review(cleaning_order))


@frappe.whitelist(methods=["POST"])
def cleaning_request_revision(cleaning_order=None, reason=None, request_id=None):
	"""POST /api/v1/ess/cleaning-request-revision — ask Admin Ops to reopen a submitted order.

	Mutating (notifies + drops an audit comment + flags the order), hence POST. Does not edit
	the cleaning work itself.

	``request_id`` stops a replay sending Admin Ops the same request twice."""
	require_menu("cleaning")
	return guarded(request_id, lambda: cleaning.request_revision(cleaning_order=cleaning_order, reason=reason))


@frappe.whitelist(methods=["POST"])
def cleaning_start(cleaning_order=None, request_id=None):
	"""POST /api/v1/ess/cleaning-start — mark a Cleaning Order In_Progress (Mulai)."""
	require_menu("cleaning")
	return guarded(request_id, lambda: cleaning.start_cleaning(cleaning_order))


@frappe.whitelist(methods=["POST"])
def cleaning_order_save(
	cleaning_order=None,
	cleaning_type=None,
	cleaning_items=None,
	reff_doc=None,
	remarks=None,
	signature=None,
	qc_photos=None,
	submit=False,
	request_id=None,
):
	"""POST /api/v1/ess/cleaning-order-save — save the sign-off (submit=1 completes).

	``request_id`` makes a replay safe: a submit whose response was lost in transit would
	otherwise complete the order a second time. See ``ess/idempotency.py``."""
	require_menu("cleaning")
	return guarded(request_id, lambda: cleaning.save_cleaning_order(
		cleaning_order=cleaning_order,
		cleaning_type=cleaning_type,
		cleaning_items=cleaning_items,
		reff_doc=reff_doc,
		remarks=remarks,
		signature=signature,
		qc_photos=qc_photos,
		submit=submit,
	))
