"""Depot pricing resolution (pricing spec §2).

A single entry point that resolves the effective selling rate of a depot service
Item under a given principal Price List, honouring the dynamic repair formula:

    effective rate = manhour × Price List manhour_rate + material_cost

Fixed-price services (``Item.manhour == 0``) resolve to their flat Item Price in
that list. Because rate lives on the Price List (not baked per-Item), one Item
prices differently per principal — e.g. a repair item is OAK $4.50/hr vs
Bertschi $4.00/hr from the same ``manhour`` + ``material_cost``.

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
	``manhour × Price List manhour_rate + material_cost``; everything else
	resolves to its flat Item Price (0.0 if none).
	"""
	if not item_code:
		return 0.0
	manhour = flt(frappe.db.get_value("Item", item_code, "manhour"))
	if manhour > 0:
		manhour_rate = flt(frappe.db.get_value("Price List", price_list, "manhour_rate"))
		material_cost = flt(frappe.db.get_value("Item", item_code, "material_cost"))
		return manhour * manhour_rate + material_cost
	return flt(item_price_rate(item_code, price_list))


def resolve_price(item_code: str, price_list: str) -> float:
	"""Public entry point billing will call to price a single service line."""
	return effective_item_rate(item_code, price_list)
