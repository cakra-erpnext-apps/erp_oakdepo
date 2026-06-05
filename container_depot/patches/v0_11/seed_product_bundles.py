"""Pricing spec §3.5 — seed Bertschi packages as Product Bundles.

Each Bertschi package is one flat-priced parent Item (``is_depot_package=1``)
whose price lives on its ``Bertschi 2026`` Item Price, plus a Product Bundle
listing the included services for audit. With
``Selling Settings.editable_bundle_item_rates`` OFF (pinned by
install.ensure_selling_settings) the parent's flat Item Price is authoritative
and the components are informational.

Storage per day is intentionally NOT a bundle component: the packages include
"storage free 30 days", after which storage is billed separately via the
standalone "Storage per Day" Item.

ERPNext caveat: a Product Bundle explodes into ``packed_items`` on a Quotation /
Sales Order (audit view) but NOT on a non-stock Sales Invoice with
``update_stock=0`` — there it bills as a single flat line. Use a Quotation /
Sales Order as the audit surface for the component breakdown.

Idempotent: existing package Items / Item Prices / Product Bundles are skipped.
"""

from __future__ import annotations

import frappe

from container_depot.install import setup_custom_fields

BERTSCHI_LIST = "Bertschi 2026"
PACKAGE_GROUP = "Depot Packages"

# item_code -> (flat_price_usd, [component item_codes]). Components are created
# by seed_service_items (which runs first). "Lolo" = Lift On + Lift Off.
PACKAGES = {
	"Empty Clean Tank Package": (85.0, ["EIR", "Lift On", "Lift Off", "Leak Test 1 Bar"]),
	"Light Cleaning Package": (195.0, ["EIR", "Leak Test 1 Bar", "Light Cleaning", "PTFE Gasket"]),
	"Medium Cleaning Package": (215.0, ["EIR", "Leak Test 1 Bar", "Medium Cleaning", "PTFE Gasket"]),
	"Hard Cleaning Package": (255.0, ["EIR", "Leak Test 1 Bar", "Hard Cleaning", "PTFE Gasket"]),
	"EIR & Storage Package": (30.0, ["EIR"]),
}


def _ensure_package_item(item_code):
	if frappe.db.exists("Item", item_code):
		return
	frappe.get_doc({
		"doctype": "Item",
		"item_code": item_code,
		"item_name": item_code,
		"item_group": PACKAGE_GROUP,
		"stock_uom": "Nos",
		"is_stock_item": 0,
		"is_sales_item": 1,
		"is_purchase_item": 0,
		"is_depot_package": 1,
		"service_unit": "tank",
	}).insert(ignore_permissions=True)


def _ensure_item_price(item_code, rate):
	if not frappe.db.exists("Price List", BERTSCHI_LIST):
		print(f"[container_depot] seed_product_bundles: {BERTSCHI_LIST} missing; skipped {item_code} price.")
		return
	if frappe.db.exists("Item Price", {"item_code": item_code, "price_list": BERTSCHI_LIST}):
		return
	frappe.get_doc({
		"doctype": "Item Price",
		"item_code": item_code,
		"price_list": BERTSCHI_LIST,
		"price_list_rate": rate,
		"selling": 1,
	}).insert(ignore_permissions=True)


def _ensure_bundle(parent, components):
	if frappe.db.exists("Product Bundle", {"new_item_code": parent}):
		return
	rows = []
	for c in components:
		if not frappe.db.exists("Item", c):
			print(f"[container_depot] seed_product_bundles: component {c} missing; skipped in {parent}.")
			continue
		rows.append({"item_code": c, "qty": 1, "description": c})
	if not rows:
		return
	frappe.get_doc({
		"doctype": "Product Bundle",
		"new_item_code": parent,
		"description": f"{parent} — included services (audit only; billed at flat price)",
		"items": rows,
	}).insert(ignore_permissions=True)


def execute():
	setup_custom_fields()  # is_depot_package
	for item_code, (price, components) in PACKAGES.items():
		_ensure_package_item(item_code)
		_ensure_item_price(item_code, price)
		_ensure_bundle(item_code, components)
	frappe.db.commit()
	print(f"[container_depot] seed_product_bundles: ensured {len(PACKAGES)} package(s) + bundle(s).")
