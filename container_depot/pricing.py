"""Tariff-driven pricing helpers.

Prices come from the customer's active ``Depot Contract`` tariff lines (the
``Tariff Rate`` child table: service / uom / rate / currency). The portal's
hard-coded price tables are replaced by these lookups so a contract change
flows straight through to new orders.
"""

from __future__ import annotations

import frappe

# Order type (portal vocabulary) -> Tariff Rate service value.
SERVICE_FOR_ORDER_TYPE = {
	"Lift On": "Lift On",
	"Lift Off": "Lift Off",
	"Periodic Test": "Periodic Test",
	"Leak Test": "Other",
	"Haulage": "Other",
}


def resolve_tariff_rate(contract, service):
	"""Return the rate for ``service`` on ``contract`` (0 if none)."""
	if not contract or not service:
		return 0
	rows = frappe.get_all(
		"Tariff Rate",
		filters={"parent": contract, "service": service},
		fields=["rate"],
		limit=1,
	)
	return (rows[0].rate or 0) if rows else 0


def contract_for_order(order):
	"""Resolve the Depot Contract behind an Order Bongkar / Muat via its code."""
	if not order.get("booking_code"):
		return None
	booking = frappe.db.get_value("Booking Code", order.booking_code, "booking")
	if not booking:
		return None
	return frappe.db.get_value("Isotank Booking", booking, "contract")


def order_amount(order):
	"""(total, unit_rate) for an order. Uses the order's own price_per_container
	when set, else the contract tariff for the mapped service."""
	qty = order.get("quantity") or 1
	rate = order.get("price_per_container") or 0
	if not rate:
		contract = contract_for_order(order)
		service = SERVICE_FOR_ORDER_TYPE.get(order.get("order_type"), "Other")
		rate = resolve_tariff_rate(contract, service)
	return (rate or 0) * qty, (rate or 0)
