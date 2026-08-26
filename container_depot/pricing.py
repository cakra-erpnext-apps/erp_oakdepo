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
# Storage is priced PER SIZE — a 40ft eats twice the yard slot a 20ft does, so the rate
# cards quote it per size. The generic ``Storage per Day`` above stays as the fallback:
# it is what every existing contract is priced on, and a depot that charges one flat
# storage rate never has to create the size items at all.
STORAGE_ITEM_BY_SIZE = {
	"20'": "Storage per Day 20FT",
	"40'": "Storage per Day 40FT",
	"45'": "Storage per Day 45FT",
}
# Representative cleaning charge billed per Cleaning Order. Adjust to the grade a
# customer's rate card actually negotiates if cleaning is priced per wash type.
CLEANING_ITEM = "Standard Cleaning"

# --------------------------------------------------------------------------- #
# Labour (manhour)
#
# Labour has TWO halves, and they live in two different masters — that is the whole model:
#
#   * **Jam** — how long a service takes. A property of the SERVICE, the same for everyone:
#     ``Item.manhour`` (e.g. Standard Clean 0.5 h, Lift On 1.5 h).
#   * **Tarif per jam** — what an hour of depot labour costs THIS customer. A property of
#     the RATE CARD, negotiated per principal: ``Item Price.manhour_rate``, published from
#     the contract's ``Tariff Rate.manhour_rate`` (e.g. OAK 4.50, Bertschi 4.00).
#
# Labour is never folded into a service's own rate. Each order keeps the two apart and
# billing settles them once, in the invoice header:
#
#     Total = Total Price + (Total Jam × Tarif per Jam)
#
# Note the asymmetry, and that it is deliberate: a RATE is per unit, so the line multiplies
# it by qty; the JAM a line books is the labour that line takes, whatever the quantity, so
# the hours are summed as they stand and only the SUM meets the tariff — ``Tarif per Jam``,
# which seeds from the customer's rate card and stays editable per invoice.
# --------------------------------------------------------------------------- #
# Fallback labour tariff (money per hour) for a customer whose rate card carries none.
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
	"""Labour TARIFF (money per hour) one rate card charges for a service (0 when none).

	This is the price of an hour, not a number of hours — the hours are on the Item
	(:func:`manhour_hours_for`). Held per Item Price so each principal's rate card can carry
	its own figure.
	"""
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


def manhour_hours_for(item) -> float:
	"""Standard labour HOURS one service takes (``Item.manhour``; 0 when it books none).

	The same for every customer — what differs per customer is what an hour costs them
	(:func:`manhour_for`).
	"""
	from frappe.utils import flt

	if not item:
		return 0.0
	return flt(frappe.db.get_value("Item", item, "manhour"))


def manhour_rate_for(customer) -> float:
	"""The labour tariff (money per hour) to charge this customer's invoice.

	A rate card states one price for an hour of depot labour, repeated on every line it
	prices, so any non-zero figure on the customer's published Price List is that price —
	the most common one wins if a stray line disagrees. Falls back to
	:data:`DEFAULT_MANHOUR_HOUR` when the contract prices no labour at all.
	"""
	from collections import Counter

	from frappe.utils import flt

	price_list = contract_price_list(customer)
	if not price_list:
		return 0.0
	rates = [
		flt(r)
		for r in frappe.get_all(
			"Item Price", filters={"price_list": price_list, "selling": 1}, pluck="manhour_rate"
		)
		if flt(r)
	]
	if not rates:
		return DEFAULT_MANHOUR_HOUR
	return Counter(rates).most_common(1)[0][0]


def invoice_manhours(customer, lines):
	"""Labour hours each invoice line books, from the Item master.

	Returns ``{index: hours}`` for the lines that take labour, so the caller can stamp each
	line and let the header total them and meet the tariff once. Empty when the customer has
	no active contract (nobody to charge labour to) or nothing billed books hours.
	"""
	if not contract_price_list(customer):
		return {}
	out = {}
	for i, ln in enumerate(lines):
		hours = manhour_hours_for(ln.get("item_code"))
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


def storage_item_for(size: str | None) -> str:
	"""The storage service Item a container of this size is priced on."""
	return STORAGE_ITEM_BY_SIZE.get(size) or STORAGE_ITEM


def storage_rate_for(contract, size: str | None):
	"""``(rate, item)`` — the storage day-rate for one size on one contract.

	Falls back from the size-specific Item to the generic ``Storage per Day`` whenever the
	rate card prices no size (the normal case until someone fills the size rates in), and
	returns ``(0, item)`` when it prices neither. A zero rate is not an error here: the day
	count is the point, and the money can be filled in later without the days changing.
	"""
	item = storage_item_for(size)
	if item != STORAGE_ITEM:
		rate = resolve_tariff_rate(contract, item)
		if rate:
			return rate, item
	return resolve_tariff_rate(contract, STORAGE_ITEM), STORAGE_ITEM
