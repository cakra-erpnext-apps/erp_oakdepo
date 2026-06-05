"""Pricing spec §3.1 — seed the Depot Services Item Group tree.

Creates the parent ``Depot Services`` group plus the child groups that organise
the service catalogue by the headings in the rate card (reference/pricing.md §1),
a ``Repair & Spare Parts`` bucket for the per-part repair line-items, and a
``Depot Packages`` group for the Bertschi Product Bundle parents.

These groups are pure master data; nothing references them until the Item
seeders (seed_service_items / seed_product_bundles) run. Idempotent: existing
groups are skipped.
"""

from __future__ import annotations

import frappe

ROOT = "All Item Groups"  # ERPNext's built-in tree root.
PARENT = "Depot Services"

# Child groups follow the rate-card headings in §1. Individual repair parts
# (valves, gaskets, cladding, frame, fittings, …) live under Repair & Spare
# Parts rather than one group each; Product Bundle parents live under Depot
# Packages.
CHILD_GROUPS = [
	"Standard Depot Handling Charge",
	"Testing Charges",
	"Survey Fee",
	"Exterior Cleaning Fee",
	"Cleaning Cost",
	"Interior Shell - Special Requirement",
	"Repair & Spare Parts",
	"Depot Packages",
]


def _ensure_group(name, parent, is_group):
	if frappe.db.exists("Item Group", name):
		return
	frappe.get_doc({
		"doctype": "Item Group",
		"item_group_name": name,
		"parent_item_group": parent,
		"is_group": is_group,
	}).insert(ignore_permissions=True)


def execute():
	if not frappe.db.exists("Item Group", ROOT):
		# erpnext not installed / no selling masters — nothing to attach to.
		print("[container_depot] seed_item_groups: no 'All Item Groups' root; skipped.")
		return

	_ensure_group(PARENT, ROOT, is_group=1)
	for name in CHILD_GROUPS:
		_ensure_group(name, PARENT, is_group=0)

	frappe.db.commit()
	print(f"[container_depot] seed_item_groups: ensured '{PARENT}' + {len(CHILD_GROUPS)} child group(s).")
