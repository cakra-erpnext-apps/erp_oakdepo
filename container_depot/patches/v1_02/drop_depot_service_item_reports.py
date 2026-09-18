"""Drop the two read-only catalogue reports, "Depot Service Item" and "Depot Service Item Group".

Both were query reports over `tabItem` / `tabItem Group`, hard-coded to the eight depot
service Item Groups. They showed the service catalogue without the noise of the full ERPNext
Item list, back when a picker would only offer items from those groups.

That filter is gone: since 2026-09-07 every item picker reads the open catalogue ordered by
"most used" (``container_depot.item_catalog``), so the eight-group list the reports hard-code
is no longer the set anybody picks from. A report that answers a question the app stopped
asking is a report that misleads whoever opens it.

Nothing is lost. The Item and Item Group lists show the same rows, live, with filters and
edit rights the reports never had.

Idempotent: every step is a no-op on a site that has already run it.
"""

from __future__ import annotations

import frappe

REPORTS = ["Depot Service Item", "Depot Service Item Group"]


def execute():
	for report in REPORTS:
		# Orphan links first: `bench migrate` rewrites the Workspace from JSON but leaves
		# child rows the JSON no longer carries, and a link to a deleted report breaks the
		# sidebar render.
		frappe.db.delete("Workspace Link", {"link_to": report, "link_type": "Report"})
		if frappe.db.table_exists("Workspace Sidebar Item"):
			frappe.db.delete("Workspace Sidebar Item", {"link_to": report})
		if frappe.db.exists("Report", report):
			frappe.delete_doc("Report", report, force=True, ignore_permissions=True)
	frappe.clear_cache()
	frappe.db.commit()
