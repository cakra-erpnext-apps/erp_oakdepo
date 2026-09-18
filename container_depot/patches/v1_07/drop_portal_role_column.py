"""Drop the retired `portal_role` column from Customer Portal User.

The field was an intra-company role (Admin / Operations / Finance / Viewer) that nothing
ever read: what a portal account may do is decided by `approval_status` plus the OAK Party
Roles on its Customer master (`customer_scope`), never by this. It was removed from the
doctype on 2026-09-18, and Frappe leaves the column behind when a field goes — so it is
dropped here.

Irreversible, and deliberately so: keeping a column nobody writes is how a dead field comes
back as a live one two migrations later.
"""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.has_column("Customer Portal User", "portal_role"):
		return
	frappe.db.sql_ddl("ALTER TABLE `tabCustomer Portal User` DROP COLUMN `portal_role`")
	frappe.clear_cache(doctype="Customer Portal User")
