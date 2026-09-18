"""Section "Container Inventory": five report menus become three.

Two reports go:

* **Container Status Report** — merged INTO ``Container Inventory``. Both were one row per
  Container over the same table, with overlapping filters; the only thing the inventory
  half owned were four columns (Stage, Last Cargo, In Date, Days In Depo), and they now sit
  on the surviving report next to the order columns. Two menus over one table meant two
  answers to "which tanks are in the depo", and they disagreed: the old inventory report
  never filtered ``is_active``, so retired tanks counted as stock.
* **Daily Operations Report** — dropped, not merged. Its four sections (containers by
  status, today's bookings, pending bons, open cleaning) are already Number Cards on the
  Container Inventory workspace, and the card versions are the correct ones: the report
  counted Order Bongkar / Order Muat without a ``docstatus`` filter (drafts and cancelled
  bons included), missed cleaning orders sitting in ``Pending Review``, and counted retired
  tanks. Merging it would only have moved those three bugs somewhere harder to see.

Nothing is lost: every column of both reports is on ``Container Inventory`` or on a card.

Idempotent: every step is a no-op on a site that has already run it.
"""

from __future__ import annotations

import frappe

REPORTS = ["Container Status Report", "Daily Operations Report"]


def execute():
	for report in REPORTS:
		# Orphan links first: `bench migrate` rewrites the Workspace from JSON but leaves
		# child rows the JSON no longer carries, and a link to a deleted report breaks the
		# sidebar render. Shortcuts are a second child table with the same problem.
		frappe.db.delete("Workspace Link", {"link_to": report, "link_type": "Report"})
		frappe.db.delete("Workspace Shortcut", {"link_to": report, "type": "Report"})
		if frappe.db.table_exists("Workspace Sidebar Item"):
			frappe.db.delete("Workspace Sidebar Item", {"link_to": report})
		if frappe.db.exists("Report", report):
			frappe.delete_doc("Report", report, force=True, ignore_permissions=True)
	frappe.clear_cache()
	frappe.db.commit()
