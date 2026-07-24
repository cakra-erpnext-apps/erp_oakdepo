"""Cleaning Order: drop the Cleanliness Statement / Gas Free / Seal Numbers block.

Ops no longer records those on the cleaning order — the order captures the chosen services
(with their tariff and manhour cost), the remarks and the surveyor's signature, and that is
what proves the tank is clean. Removing a field from the doctype JSON does not drop its DB
column, so this cleans up the leftovers and retires the now-parentless checklist child table.
"""

import frappe

_COLUMNS = [
	"gas_free",
	"o2_percent",
	"lel_percent",
	"seal_manhole",
	"seal_airline",
	"seal_bottom_outlet",
]
_ORPHANED_CHILD = "Cleaning Order Checklist Item"


def execute():
	frappe.reload_doc("operations", "doctype", "cleaning_order_service")
	frappe.reload_doc("operations", "doctype", "cleaning_order")
	_drop_columns()
	_drop_orphaned_child()


def _drop_columns() -> None:
	existing = {c.get("name") for c in frappe.db.get_table_columns_description("tabCleaning Order")}
	for column in _COLUMNS:
		if column in existing:
			frappe.db.sql_ddl(f"ALTER TABLE `tabCleaning Order` DROP COLUMN `{column}`")
			print(f"[container_depot] dropped tabCleaning Order.{column}")


def _drop_orphaned_child() -> None:
	"""The checklist rows hung off Cleaning Order only — with the field gone they are dead."""
	if not frappe.db.exists("DocType", _ORPHANED_CHILD):
		return
	frappe.delete_doc("DocType", _ORPHANED_CHILD, force=True, ignore_permissions=True)
	frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{_ORPHANED_CHILD}`")
	print(f"[container_depot] dropped {_ORPHANED_CHILD} + its table.")
