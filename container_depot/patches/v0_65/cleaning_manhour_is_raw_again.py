"""Cleaning Order: the labour figure is the rate card's, used as it stands — no hours in it.

A cleaning order locks the two RATES that applied at cleaning time (the service tariff and
the labour tariff) and nothing else; how many hours were actually worked is settled at
invoicing. The hours briefly came back onto the order (``Cleaning Order Service.manhour`` /
``manhour_amount``, and ``Cleaning Order.manhour_total``) with the labour total computed as
hours × rate — this undoes that, exactly as ``v0_39.drop_cleaning_order_service_manhour_hours``
did the first time.

Two jobs, because removing fields from the doctype JSON drops neither the columns nor the
figures already stored:

  1. drop the re-added columns, so a future field of the same name cannot inherit them;
  2. recompute ``manhour_charge_total`` on every existing order as the plain SUM of its rows'
     ``manhour_rate`` — a submitted order never re-saves, so its header would otherwise keep
     showing the multiplied number for ever.
"""

import frappe

_ORDER = "tabCleaning Order"
_ROW = "tabCleaning Order Service"
_DEAD = {_ROW: ["manhour", "manhour_amount"], _ORDER: ["manhour_total"]}


def execute():
	frappe.reload_doc("container_depot", "doctype", "cleaning_order_service")
	frappe.reload_doc("container_depot", "doctype", "cleaning_order")

	# 1) Recompute FIRST — the sum reads manhour_rate, which stays, but doing it after the
	#    DDL keeps the two steps independent if this patch is ever re-run mid-way.
	frappe.db.sql(
		f"""
		UPDATE `{_ORDER}` o
		SET o.manhour_charge_total = (
			SELECT IFNULL(SUM(r.manhour_rate), 0) FROM `{_ROW}` r WHERE r.parent = o.name
		)
		"""
	)

	# 2) Drop what no field points at any more.
	for table, columns in _DEAD.items():
		existing = {c.get("name") for c in frappe.db.get_table_columns_description(table)}
		for column in columns:
			if column in existing:
				frappe.db.sql_ddl(f"ALTER TABLE `{table}` DROP COLUMN `{column}`")
				print(f"[container_depot] dropped {table}.{column}")
