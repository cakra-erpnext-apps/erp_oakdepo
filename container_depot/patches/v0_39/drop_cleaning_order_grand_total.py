"""Cleaning Order: drop ``grand_total`` — tariff and manhour must not be added together.

The order's Manhour column holds HOURS (what the contract books for that service), not
money, so summing it with the tariff produced a meaningless figure. Labour is settled once
at invoicing: every service billed contributes its hours, they are totalled, and the total
is charged on its own invoice line. Removing the field from the doctype JSON does not drop
its DB column, hence this.
"""

import frappe

_TABLE = "tabCleaning Order"
_COLUMN = "grand_total"


def execute():
	frappe.reload_doc("operations", "doctype", "cleaning_order_service")
	frappe.reload_doc("operations", "doctype", "cleaning_order")
	existing = {c.get("name") for c in frappe.db.get_table_columns_description(_TABLE)}
	if _COLUMN in existing:
		frappe.db.sql_ddl(f"ALTER TABLE `{_TABLE}` DROP COLUMN `{_COLUMN}`")
		print(f"[container_depot] dropped {_TABLE}.{_COLUMN}")
