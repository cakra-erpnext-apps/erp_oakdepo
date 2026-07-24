"""Cleaning Order Service: drop the hours worked (``manhour``) and its derived amount.

The cleaning order only locks the RATES that applied at cleaning time — the service tariff
and the labour (manhour) rate. How many hours were actually worked is settled at invoicing,
so capturing it on the order was a second source of truth nobody reconciled. Removing the
fields from the doctype JSON does not drop their DB columns, hence this.
"""

import frappe

_TABLE = "tabCleaning Order Service"
_COLUMNS = ["manhour", "manhour_amount"]


def execute():
	frappe.reload_doc("operations", "doctype", "cleaning_order_service")
	frappe.reload_doc("operations", "doctype", "cleaning_order")
	existing = {c.get("name") for c in frappe.db.get_table_columns_description(_TABLE)}
	for column in _COLUMNS:
		if column in existing:
			frappe.db.sql_ddl(f"ALTER TABLE `{_TABLE}` DROP COLUMN `{column}`")
			print(f"[container_depot] dropped {_TABLE}.{column}")
