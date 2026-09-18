"""Take the picked-only masters off the customer's menu, leaving their pickers.

Depot, Cargo, Item and Item Group are masters a portal account PICKS (or has picked FOR it)
and has no reason to browse: OAK's depot list, the site's cargo catalogue and its whole
service catalogue. Frappe separates `select` from `read`
(`db_query.check_read_permission` asks for `select` when that is all a role holds), so
dropping `read` closes the list view and the sidebar entry — a Workspace Sidebar Item is
drawn off `can_read` and has no role field of its own — while the Link field still opens.

The permission seeder is add-only, so the flags on rows that already exist are set here.
Idempotent.
"""

from __future__ import annotations

import frappe

from container_depot.install import CUSTOMER_DESK_ROLE, setup_permissions

SELECT_ONLY = ("Depot", "Cargo", "Item", "Item Group")


def execute():
	setup_permissions()

	for doctype in SELECT_ONLY:
		name = frappe.db.get_value(
			"Custom DocPerm", {"parent": doctype, "role": CUSTOMER_DESK_ROLE}, "name"
		)
		if not name:
			continue
		frappe.db.set_value(
			"Custom DocPerm",
			name,
			{"select": 1, "read": 0, "export": 0, "print": 0, "report": 0},
			update_modified=False,
		)
		frappe.clear_cache(doctype=doctype)

	frappe.clear_cache()
	frappe.db.commit()
