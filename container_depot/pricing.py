"""Tariff-driven pricing helpers.

Prices come from the customer's active ``Depot Contract`` tariff lines (the
``Tariff Rate`` child table, keyed by **Item**: item / uom / rate / manhour_rate
/ qty). Billing resolves a negotiated rate by Item code, so a contract change
flows straight through to new orders. The service Items themselves (``Lift On``,
``Lift Off``, ``Storage per Day``, the cleaning grades, …) are the seeded catalog
Items priced per principal via Item Price.
"""

from __future__ import annotations

import frappe

# Order type (portal vocabulary) -> canonical service Item code. None = not
# priced by the contract tariff (the Cashier fills the rate in on the invoice).
ITEM_FOR_ORDER_TYPE = {
	"Lift On": "Lift On",
	"Lift Off": "Lift Off",
	"Periodic Test": "Periodic Test 2.5 Year",
	"Leak Test": "Leak Test 1 Bar",
	"Haulage": None,
}

# Canonical service Item codes used by the consolidated / monthly billing path.
# These match the codes seeded by patches.v0_11.seed_service_items.
LIFT_ON_ITEM = "Lift On"
LIFT_OFF_ITEM = "Lift Off"
STORAGE_ITEM = "Storage per Day"
# Representative cleaning charge billed per Cleaning Order. Adjust to the grade a
# customer's rate card actually negotiates if cleaning is priced per wash type.
CLEANING_ITEM = "Standard Cleaning"

# --------------------------------------------------------------------------- #
# Labour (manhour)
#
# Every line of a contract's Price List carries a **Manhour** next to its Rate
# (``Tariff Rate.manhour_rate``, published onto ``Item Price.manhour_rate``): the labour
# hours that service takes — e.g. Standard Clean 0.5, Lift On 1.5.
#
# The two are deliberately NEVER merged into one rate inside an order: each menu bills its
# tariff and carries its manhour untouched. Billing is where labour is settled — every line
# of the invoice shows the manhour it books, the hours are totalled ONCE in the header, and
# that total is charged as a single amount:
#
#     Total = Total Price + (Total Manhour × Hour)
#
# Note the asymmetry, and that it is deliberate: a RATE is per unit, so the line multiplies
# it by qty; a MANHOUR is not. It is the labour that line books, whatever the quantity, so
# the hours are summed as they stand and only the SUM meets a multiplier — ``Hour``, which
# seeds from :data:`DEFAULT_MANHOUR_HOUR` and stays editable per invoice.
# --------------------------------------------------------------------------- #
DEFAULT_MANHOUR_HOUR = 4.0


def contract_price_list(customer):
	"""Published Price List of the customer's Active Depot Contract (None when none)."""
	if not customer:
		return None
	return (
		frappe.db.get_value(
			"Depot Contract",
			{"customer": customer, "status": "Active"},
			"generated_price_list",
			order_by="valid_from desc",
		)
		or None
	)


def manhour_for(item, price_list):
	"""Labour hours the contract books for one service (0 when it carries none)."""
	from frappe.utils import flt

	if not (item and price_list):
		return 0.0
	return flt(
		frappe.db.get_value(
			"Item Price",
			{"item_code": item, "price_list": price_list, "selling": 1},
			"manhour_rate",
		)
	)


def invoice_manhours(customer, lines):
	"""Manhour each invoice line books, from the customer's contract.

	Returns ``{index: hours_per_unit}`` for the lines the contract books labour for, so the
	caller can stamp each line and let the header total them. Empty when the customer has
	no active contract or nothing billed carries a manhour.
	"""
	price_list = contract_price_list(customer)
	if not price_list:
		return {}
	out = {}
	for i, ln in enumerate(lines):
		hours = manhour_for(ln.get("item_code"), price_list)
		if hours:
			out[i] = hours
	return out


def resolve_tariff_rate(contract, item):
	"""Return the negotiated rate for ``item`` on ``contract`` (0 if none).

	Rates are resolved from Item Price (single source of truth): an Active contract
	publishes its agreed lines to a customer Price List (``generated_price_list``),
	and billing reads that list — the same path walk-in pricing uses.
	"""
	if not contract or not item:
		return 0
	price_list = frappe.db.get_value("Depot Contract", contract, "generated_price_list")
	if not price_list:
		return 0
	from container_depot import pricing_model

	return pricing_model.resolve_price(item, price_list) or 0


def contract_for_order(order):
	"""Resolve the Depot Contract behind an Order Bongkar / Muat via its code."""
	if not order.get("booking_code"):
		return None
	booking = frappe.db.get_value("Booking Code", order.booking_code, "booking")
	if not booking:
		return None
	return frappe.db.get_value("Container Booking", booking, "contract")


def order_amount(order):
	"""(total, unit_rate) for an order. Uses the order's own price_per_container
	when set, else the contract tariff for the mapped service Item."""
	qty = order.get("quantity") or 1
	rate = order.get("price_per_container") or 0
	if not rate:
		contract = contract_for_order(order)
		item = ITEM_FOR_ORDER_TYPE.get(order.get("order_type"))
		rate = resolve_tariff_rate(contract, item)
	return (rate or 0) * qty, (rate or 0)
