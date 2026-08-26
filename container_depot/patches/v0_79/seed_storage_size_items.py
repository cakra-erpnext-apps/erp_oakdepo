"""Seed the per-size storage service Items (no prices).

Storage is quoted per container size on real rate cards, so each size needs its own Item
to hang an Item Price on. **No rates are seeded**: what each size costs is a commercial
decision per contract, and ``pricing.storage_rate_for`` falls back to the flat
``Storage per Day`` until someone prices them — so these Items change nothing until a
rate card is actually filled in.

The generic ``Storage per Day`` Item is used as the template rather than hard-coded
metadata: it is the same charge at a different size, and its Item Group has already
drifted between sites (``Standard Depot Handling`` vs the seeder's original
``… Charge``), so copying it is the only way the sizes land beside it everywhere.

Idempotent; safe to re-run.
"""

from __future__ import annotations

import frappe

from container_depot.pricing import STORAGE_ITEM, STORAGE_ITEM_BY_SIZE

# Used only when the generic storage Item is absent (a site that never ran the v0_11
# service-item seed). First one that exists wins.
_FALLBACK_GROUPS = ("Standard Depot Handling", "Standard Depot Handling Charge", "Services", "All Item Groups")


def _template():
	"""(item_group, service_unit) to give the size Items."""
	row = frappe.db.get_value("Item", STORAGE_ITEM, ["item_group", "service_unit"], as_dict=True)
	if row and row.item_group:
		return row.item_group, row.service_unit
	group = next((g for g in _FALLBACK_GROUPS if frappe.db.exists("Item Group", g)), None)
	return group, "day"


def execute():
	item_group, service_unit = _template()
	if not item_group:
		print("[container_depot] seed_storage_size_items: no usable Item Group; skipped.")
		return
	created = 0
	for item_code in STORAGE_ITEM_BY_SIZE.values():
		if frappe.db.exists("Item", item_code):
			continue
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
		created += 1
	if created:
		frappe.db.commit()
	print(f"[container_depot] seed_storage_size_items: created {created} item(s) in {item_group}.")
