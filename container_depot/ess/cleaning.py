"""ESS PWA Cleaning Order endpoints — thin ``@frappe.whitelist`` wrappers.

Per the integration rule (mirrors ``ess/inspections.py``): endpoints here only add
authentication + whitelisting + GET/POST gating; every bit of resolution/build logic
lives in ``container_depot.operations.cleaning``.
"""

from __future__ import annotations

import frappe

from container_depot.api import _require_authenticated_user
from container_depot.operations import cleaning


@frappe.whitelist(methods=["GET"])
def cleaning_masters():
	"""GET /api/v1/ess/cleaning-masters — checklist taxonomy + default remarks."""
	_require_authenticated_user()
	return cleaning.get_cleaning_masters()


@frappe.whitelist(methods=["GET"])
def cleaning_orders(start=0, page_length=20, search=None):
	"""GET /api/v1/ess/cleaning-orders — open Cleaning Orders worklist (depot-scoped)."""
	_require_authenticated_user()
	return cleaning.list_open_cleaning_orders(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def cleaning_history(start=0, page_length=10, search=None):
	"""GET /api/v1/ess/cleaning-history — finished (Completed/Cancelled) cleaning orders."""
	_require_authenticated_user()
	return cleaning.list_cleaning_history(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def cleaning_order_detail(cleaning_order=None):
	"""GET /api/v1/ess/cleaning-order-detail — one order's cleanliness state + tank spec."""
	_require_authenticated_user()
	return cleaning.get_cleaning_order_detail(cleaning_order)


@frappe.whitelist(methods=["POST"])
def cleaning_start(cleaning_order=None):
	"""POST /api/v1/ess/cleaning-start — mark a Cleaning Order In_Progress (Mulai)."""
	_require_authenticated_user()
	return cleaning.start_cleaning(cleaning_order)


@frappe.whitelist(methods=["POST"])
def cleaning_order_save(
	cleaning_order=None,
	cleaning_type=None,
	cleaning_items=None,
	gas_free=None,
	o2_percent=None,
	lel_percent=None,
	seal_manhole=None,
	seal_airline=None,
	seal_bottom_outlet=None,
	remarks=None,
	signature=None,
	results=None,
	submit=False,
):
	"""POST /api/v1/ess/cleaning-order-save — save cleanliness detail (submit=1 completes)."""
	_require_authenticated_user()
	return cleaning.save_cleaning_order(
		cleaning_order=cleaning_order,
		cleaning_type=cleaning_type,
		cleaning_items=cleaning_items,
		gas_free=gas_free,
		o2_percent=o2_percent,
		lel_percent=lel_percent,
		seal_manhole=seal_manhole,
		seal_airline=seal_airline,
		seal_bottom_outlet=seal_bottom_outlet,
		remarks=remarks,
		signature=signature,
		results=results,
		submit=submit,
	)
