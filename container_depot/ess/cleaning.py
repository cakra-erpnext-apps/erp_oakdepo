"""ESS PWA Cleaning Order endpoints — thin ``@frappe.whitelist`` wrappers.

Per the integration rule (mirrors ``ess/inspections.py``): endpoints here only add
authentication + whitelisting + GET/POST gating; every bit of resolution/build logic
lives in ``container_depot.operations.cleaning``.
"""

from __future__ import annotations

import frappe

from container_depot.ess.guard import require_menu
from container_depot.operations import cleaning


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
def cleaning_order_detail(cleaning_order=None):
	"""GET /api/v1/ess/cleaning-order-detail — one order's cleanliness state + tank spec."""
	require_menu("cleaning")
	return cleaning.get_cleaning_order_detail(cleaning_order)


@frappe.whitelist(methods=["POST"])
def cleaning_start(cleaning_order=None):
	"""POST /api/v1/ess/cleaning-start — mark a Cleaning Order In_Progress (Mulai)."""
	require_menu("cleaning")
	return cleaning.start_cleaning(cleaning_order)


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
):
	"""POST /api/v1/ess/cleaning-order-save — save the sign-off (submit=1 completes)."""
	require_menu("cleaning")
	return cleaning.save_cleaning_order(
		cleaning_order=cleaning_order,
		cleaning_type=cleaning_type,
		cleaning_items=cleaning_items,
		reff_doc=reff_doc,
		remarks=remarks,
		signature=signature,
		qc_photos=qc_photos,
		submit=submit,
	)
