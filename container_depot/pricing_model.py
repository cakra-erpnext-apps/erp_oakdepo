"""Depot pricing resolution (pricing spec §2).

A single entry point that resolves the selling rate of a depot service Item under a given
principal Price List: the flat Item Price in that list. Because the rate lives on each Item
Price row (item + price list), one Item prices differently per principal.

Labour is **not** part of that rate. Each Price List line carries a Manhour beside its Rate,
and the two travel separately through every order; billing totals the hours once and charges
them once in the invoice header (see ``invoicing.apply_manhour_charge``).

This module is deliberately standalone: it does NOT touch the live Tariff-Rate
billing path (pricing.py / invoicing.py / monthly_invoicing.py). Wiring billing
onto this helper is a separate later change.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt


def item_price_rate(item_code: str, price_list: str):
	"""Flat selling Item Price rate for (item, price_list), or None if unpriced."""
	if not item_code or not price_list:
		return None
	return frappe.db.get_value(
		"Item Price",
		{"item_code": item_code, "price_list": price_list, "selling": 1},
		"price_list_rate",
	)


def effective_item_rate(item_code: str, price_list: str) -> float:
	"""Flat per-unit selling rate for a depot service Item in a Price List (0.0 if none).

	Labour is deliberately NOT folded in here. Each Price List line carries its Manhour
	beside its Rate, and the two stay apart all the way through the order: billing totals
	the hours once and charges them on their own invoice line
	(:func:`container_depot.invoicing.apply_manhour_charge`). Merging them into one rate would
	bury labour inside every menu's price and then charge it twice at invoicing.
	"""
	if not item_code:
		return 0.0
	return flt(item_price_rate(item_code, price_list))


def resolve_price(item_code: str, price_list: str) -> float:
	"""Public entry point billing will call to price a single service line."""
	return effective_item_rate(item_code, price_list)


def item_rate_breakdown(item_code: str, price_list: str) -> dict:
	"""The cost inputs that default a Repair Order line: ``item_rate`` (what
	the line costs) plus ``manhour`` / ``manhour_rate`` for reference (what the INVOICE will
	book for it — see :func:`container_depot.invoicing.apply_manhour_charge`).

	``item_rate`` is ALWAYS the agreed Item Price rate from the owner's contract list. It
	used to fall back to ``Item.material_cost`` whenever the item booked labour hours —
	a leftover from the old model where a line cost ``manhour × manhour_rate +
	material_cost``. Labour left the order itself long ago (``RepairOrder.calculate_totals``:
	the invoice totals the hours once, in its header), which turned that branch from a split
	into a silent zero: every service on a real rate card carries ``Item.manhour > 0`` and
	``material_cost = 0``, so the agreed Rate never reached the line — and
	``consolidated_billing`` bills straight off ``item_rate``, so the invoice went out at
	zero too. There is no split left to make; the contract Rate IS the line's price.

	``currency`` is read from the Item Price itself (each Item Price carries its own), so a
	Repair Order can mix currencies — it is NOT the site/company default."""
	empty = {"manhour": 0.0, "manhour_rate": 0.0, "item_rate": 0.0, "currency": None}
	if not item_code:
		return empty
	ip = frappe.db.get_value(
		"Item Price",
		{"item_code": item_code, "price_list": price_list, "selling": 1},
		["currency", "price_list_rate", "manhour_rate"],
		as_dict=True,
	) or frappe._dict()
	manhour = flt(frappe.db.get_value("Item", item_code, "manhour"))
	# Reported, never priced in here: the hours are charged once on the invoice header.
	manhour_rate = flt(ip.manhour_rate)
	item_rate = flt(ip.price_list_rate or 0.0)
	return {
		"manhour": manhour,
		"manhour_rate": manhour_rate,
		"item_rate": item_rate,
		"currency": ip.currency,
	}


def price_list_for_customer(customer: str | None) -> str | None:
	"""Resolve the selling Price List to use for a *no-contract* (walk-in) booking.

	A booking backed by a Depot Contract prices from that contract's tariff; a
	walk-in has none, so the rate card falls back to a Price List. Preference:

	  1. the Customer's own ``default_price_list`` (per-principal rate card);
	  2. the site Selling Settings default selling price list;
	  3. ``None`` — caller then leaves the rate 0 for the Cashier to fill in.
	"""
	if customer:
		pl = frappe.db.get_value("Customer", customer, "default_price_list")
		if pl:
			return pl
	return frappe.db.get_single_value("Selling Settings", "selling_price_list") or None
