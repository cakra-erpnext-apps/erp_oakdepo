"""Pricing spec §3.4 — seed single-service Items + per-principal Item Prices.

Catalogues the depot services as non-stock Items and prices them per principal
via Item Price rows (one Item, many Item Price — a service shared across
principals at different rates is a single Item with one Item Price per list).

Concrete rates are taken from reference/pricing.md §1 (OAK rate card + Bertschi
single services). Repair line-items (valves, gaskets, seals, fittings, frame, …)
are intentionally NOT seeded as fixed catalog items: they are priced per-job at
inspection — HRS entered by the surveyor × the Price List manhour_rate + material
— on the repair estimate, not from a fixed rate card. They are listed in
PER_JOB_REPAIR_ITEMS purely for traceability to §1. Bundle component items with
no standalone price (EIR, the Bertschi cleaning grades, PTFE Gasket) are created
so seed_product_bundles can reference them.

Idempotent: existing Items / Item Prices are skipped. Item Price currency is set
automatically from the Price List by ERPNext.
"""

from __future__ import annotations

import frappe

from container_depot.install import setup_custom_fields

# Item master metadata: item_code -> (item_group, service_unit). Every code used
# below (priced or bundle component) must appear here.
ITEM_META = {
	"Lift On": ("Standard Depot Handling Charge", "move"),
	"Lift Off": ("Standard Depot Handling Charge", "move"),
	"Storage per Day": ("Standard Depot Handling Charge", "day"),
	"EIR": ("Standard Depot Handling Charge", "tank"),
	"Leak Test 1 Bar": ("Testing Charges", "test"),
	"Steam Tube Test": ("Testing Charges", "test"),
	"Periodic Test 2.5 Year": ("Testing Charges", "test"),
	"Periodic Test 5 Year": ("Testing Charges", "test"),
	"Standard Cleaning": ("Cleaning Cost", "tank"),
	"Difficult Cleaning": ("Cleaning Cost", "tank"),
	"Foodgrade Cleaning": ("Cleaning Cost", "tank"),
	"Latex Cleaning": ("Cleaning Cost", "tank"),
	"P&P Wash": ("Cleaning Cost", "tank"),
	"Methanol Rinse": ("Cleaning Cost", "tank"),
	"Steam Wash": ("Cleaning Cost", "tank"),
	"Recleaning": ("Cleaning Cost", "tank"),
	"Exterior Detergent Wash": ("Exterior Cleaning Fee", "tank"),
	"Exterior Chemical Wash": ("Exterior Cleaning Fee", "tank"),
	# Bundle components (no standalone Item Price — covered by the package price).
	"Light Cleaning": ("Cleaning Cost", "tank"),
	"Medium Cleaning": ("Cleaning Cost", "tank"),
	"Hard Cleaning": ("Cleaning Cost", "tank"),
	"PTFE Gasket": ("Repair & Spare Parts", "per"),
}

# OAK 2026 (USD) single-service prices — §1 OAK rate card.
OAK_PRICES = {
	"Lift On": 36.0,
	"Lift Off": 36.0,
	"Storage per Day": 1.5,
	"Leak Test 1 Bar": 23.0,
	"Steam Tube Test": 20.0,
	"Periodic Test 2.5 Year": 170.0,
	"Periodic Test 5 Year": 200.0,
	"Standard Cleaning": 150.0,
	"Difficult Cleaning": 200.0,
	"Foodgrade Cleaning": 170.0,
	"Latex Cleaning": 400.0,
}

# Bertschi 2026 (USD) single services + spares — §1 Bertschi list. The shared
# codes (Steam Tube Test, Periodic Test 2.5/5 Year) reuse the SAME Item created
# for OAK and add a second Item Price here — the "one Item, many Item Price"
# model (OAK $20/$170/$200 vs Bertschi $10/$125/$165).
BERTSCHI_PRICES = {
	"P&P Wash": 80.0,
	"Methanol Rinse": 60.0,
	"Steam Wash": 60.0,
	"Recleaning": 60.0,
	"Exterior Detergent Wash": 25.0,
	"Exterior Chemical Wash": 40.0,
	"Steam Tube Test": 10.0,
	"Periodic Test 2.5 Year": 125.0,
	"Periodic Test 5 Year": 165.0,
}

# Priced per-job, not seeded. §1 names these repair parts but they have no fixed
# rate card: each repair is HRS (entered at inspection) × Price List manhour_rate
# + material on the repair estimate. Listed only for traceability to §1.
PER_JOB_REPAIR_ITEMS = [
	"Manlid Seal", "3.0\" Butterfly Valve (Top & Bottom)", "3.0\" Footvalve",
	"3.0\" Spigot Outlet for Bottom Discharge Valve", "1.5\" Airline Ball Valve",
	"Safety Relief Valve", "GRP/Aluminum - Cladding Patching", "Cladding Insulation",
	"Retainer Strap", "Thermometer", "Document Holder",
	"Emergency Cable Assembly for Footvalve", "Pressure Gauges", "Swingbolts",
	"Frame - Metal Work",
]


def _ensure_item(item_code):
	if frappe.db.exists("Item", item_code):
		return
	item_group, service_unit = ITEM_META[item_code]
	frappe.get_doc({
		"doctype": "Item",
		"item_code": item_code,
		"item_name": item_code,
		"item_group": item_group,
		"stock_uom": "Nos",
		"is_stock_item": 0,
		"is_sales_item": 1,
		"is_purchase_item": 0,
		"is_depot_package": 0,
		"service_unit": service_unit,
	}).insert(ignore_permissions=True)


def _ensure_item_price(item_code, price_list, rate):
	if not frappe.db.exists("Price List", price_list):
		print(f"[container_depot] seed_service_items: price list {price_list} missing; skipped {item_code}.")
		return
	if frappe.db.exists("Item Price", {"item_code": item_code, "price_list": price_list}):
		return
	# currency is copied from the Price List by Item Price.validate().
	frappe.get_doc({
		"doctype": "Item Price",
		"item_code": item_code,
		"price_list": price_list,
		"price_list_rate": rate,
		"selling": 1,
	}).insert(ignore_permissions=True)


def execute():
	# Item custom fields (service_unit, is_depot_package) may not exist yet on a
	# first migrate — post_model_sync runs before the after_migrate hook.
	setup_custom_fields()

	for item_code in ITEM_META:
		_ensure_item(item_code)

	for item_code, rate in OAK_PRICES.items():
		_ensure_item_price(item_code, "OAK 2026", rate)
	for item_code, rate in BERTSCHI_PRICES.items():
		_ensure_item_price(item_code, "Bertschi 2026", rate)

	frappe.db.commit()
	print(
		f"[container_depot] seed_service_items: ensured {len(ITEM_META)} item(s), "
		f"{len(OAK_PRICES)} OAK price(s), {len(BERTSCHI_PRICES)} Bertschi price(s). "
		f"{len(PER_JOB_REPAIR_ITEMS)} repair line-item(s) priced per-job (not seeded)."
	)
