"""Remove the standalone Gasket Inventory subsystem.

Gaskets are ordinary spare parts and are already modelled as Items (the M&R
``MR-GSK-*`` seed items priced via Item Price); the separate ``Gasket Inventory``
master + its status report were redundant and never linked into any transactional
flow. This drops them cleanly on every site (dev orphan-removal already deletes the
doctype once its files are gone, but prod may hold rows + Custom DocPerm + hook ToDos
that we tidy here). Idempotent.
"""

from __future__ import annotations

import frappe


def execute():
	# Low-stock hook ToDos left behind by the old GasketInventory.on_update.
	for name in frappe.get_all(
		"ToDo", filters={"reference_type": "Gasket Inventory"}, pluck="name"
	):
		frappe.delete_doc("ToDo", name, force=True, ignore_permissions=True)

	# Custom DocPerm rows the RBAC seeder attached to the doctype.
	for name in frappe.get_all(
		"Custom DocPerm", filters={"parent": "Gasket Inventory"}, pluck="name"
	):
		frappe.delete_doc("Custom DocPerm", name, force=True, ignore_permissions=True)

	if frappe.db.exists("Report", "Gasket Inventory Status"):
		frappe.delete_doc("Report", "Gasket Inventory Status", force=True, ignore_permissions=True)

	# Dropping the DocType drops its table — but on migrate the orphan-removal step
	# may already have deleted the DocType record before this patch runs, leaving the
	# table behind. So delete the record if still present, then drop the table by name.
	if frappe.db.exists("DocType", "Gasket Inventory"):
		frappe.delete_doc("DocType", "Gasket Inventory", force=True, ignore_permissions=True)
	if frappe.db.table_exists("Gasket Inventory"):
		frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabGasket Inventory`")

	frappe.db.commit()
