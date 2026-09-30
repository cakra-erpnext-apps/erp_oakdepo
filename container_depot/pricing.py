"""Tariff-driven pricing helpers.

Prices come from the customer's active ``Depot Contract`` tariff lines (the
``Tariff Rate`` child table, keyed by **Item**: item / uom / rate / manhour_rate
/ currency). Billing resolves a negotiated rate by Item code, so a contract change
flows straight through to new orders. The service Items themselves (``Lift On``,
``Lift Off``, ``Storage per Day``, the cleaning grades, …) are the seeded catalog
Items; what each principal pays for one is the contract line that prices it.
"""

from __future__ import annotations

import frappe

# Canonical service Item codes used by the consolidated / monthly billing path.
# These match the codes seeded by patches.v0_11.seed_service_items.
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

# --------------------------------------------------------------------------- #
# Labour (manhour)
#
# What an hour of depot labour costs is on the RATE CARD, per service: ``Tariff Rate.
# manhour_rate`` on the customer's contract. Orders carry it per row ("Tarif Manhour") and
# the invoice carries it per line (Manhour). The invoice sums the lines' tariffs and meets
# them once with the hours worked (Total Jam):
#
#     Total = Total Price + (Biaya Manhour × Total Jam)
#
# (``invoicing.apply_manhour_charge``). Labour is never folded into a service's own rate.
# ``Item.manhour`` (standard hours of a service) is only read by the M&R costing.
# --------------------------------------------------------------------------- #


def manhour_for(item, contract):
	"""Labour TARIFF (money per hour) one rate card charges for a service (0 when none)."""
	from frappe.utils import flt

	from container_depot import pricing_model

	row = pricing_model.tariff_row(item, contract)
	return flt(row.manhour_rate) if row else 0.0


def resolve_tariff_rate(contract, item):
	"""Return the negotiated rate for ``item`` on ``contract`` (0 if none).

	Straight off the contract's own ``Tariff Rate`` line. It used to hop through the Price
	List the contract published and read the rate back out of Item Price — a copy that could
	drift from the agreement it was copied from.
	"""
	if not contract or not item:
		return 0
	from container_depot import pricing_model

	return pricing_model.resolve_price(item, contract) or 0


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
