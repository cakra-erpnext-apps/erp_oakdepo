"""Depot pricing resolution (pricing spec §2).

A single entry point that resolves the effective selling rate of a depot service
Item under a given principal Price List, honouring the dynamic repair formula:

    effective rate = manhour × Item Price manhour_rate + material_cost

Fixed-price services (``Item.manhour == 0``) resolve to their flat Item Price in
that list. Because the rate lives on each Item Price row (item + price list), one
Item prices differently per principal — e.g. a repair item is OAK $4.50/hr vs
Bertschi $4.00/hr via its Item Price ``manhour_rate`` in each list.

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
	"""Effective per-unit selling rate for a depot service Item in a Price List.

	Repair services (``Item.manhour`` > 0) are priced
	``manhour × Item Price manhour_rate + material_cost``; everything else
	resolves to its flat Item Price (0.0 if none).
	"""
	if not item_code:
		return 0.0
	manhour = flt(frappe.db.get_value("Item", item_code, "manhour"))
	if manhour > 0:
		manhour_rate = flt(
			frappe.db.get_value(
				"Item Price",
				{"item_code": item_code, "price_list": price_list, "selling": 1},
				"manhour_rate",
			)
		)
		material_cost = flt(frappe.db.get_value("Item", item_code, "material_cost"))
		return manhour * manhour_rate + material_cost
	return flt(item_price_rate(item_code, price_list))


def resolve_price(item_code: str, price_list: str) -> float:
	"""Public entry point billing will call to price a single service line."""
	return effective_item_rate(item_code, price_list)


def item_rate_breakdown(item_code: str, price_list: str) -> dict:
	"""The cost components behind a line's per-unit rate, so a Repair Order line can show
	(and let Admin Ops adjust) manhour × manhour_rate + material_cost. A flat-priced part
	(``Item.manhour == 0``) puts its whole Item Price into ``material_cost``.

	``currency`` is read from the Item Price itself (each Item Price carries its own), so a
	Repair Order can mix currencies — it is NOT the site/company default."""
	empty = {"manhour": 0.0, "manhour_rate": 0.0, "material_cost": 0.0, "rate": 0.0, "currency": None}
	if not item_code:
		return empty
	ip = frappe.db.get_value(
		"Item Price",
		{"item_code": item_code, "price_list": price_list, "selling": 1},
		["currency", "price_list_rate", "manhour_rate"],
		as_dict=True,
	) or frappe._dict()
	manhour = flt(frappe.db.get_value("Item", item_code, "manhour"))
	# Always surface the Item Price manhour_rate as a default (even for a currently
	# flat-priced item) so it can be shown and adjusted on the Repair Order line.
	manhour_rate = flt(ip.manhour_rate)
	if manhour > 0:
		material_cost = flt(frappe.db.get_value("Item", item_code, "material_cost"))
	else:
		material_cost = flt(ip.price_list_rate or 0.0)
	return {
		"manhour": manhour,
		"manhour_rate": manhour_rate,
		"material_cost": material_cost,
		"rate": manhour * manhour_rate + material_cost,
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
