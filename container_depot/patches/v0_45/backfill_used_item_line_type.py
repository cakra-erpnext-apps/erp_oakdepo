"""Backfill the Used-Items rows added by the per-row gudang rework.

``Repair Used Item`` gained ``line_type`` (Jasa / Part) and its own ``warehouse``. Existing
rows have neither, which would leave the grid showing a blank Jenis and a blank Gudang on
every historical M&R — and the Stok column silently reading the order-level warehouse.

``line_type`` is derived from the row's ``is_stock_item`` (the Item master is the truth), and
a Part's ``warehouse`` inherits the order's since-removed Source Warehouse, which IS the
gudang it was issued from before rows could differ. That column only exists on sites that ran
the older schema; on a fresh install there is nothing to inherit, so the step is skipped.
"""

import frappe


def execute():
	if not frappe.db.table_exists("Repair Used Item"):
		return

	frappe.db.sql(
		"""UPDATE `tabRepair Used Item`
		   SET line_type = CASE WHEN is_stock_item = 1 THEN 'Part' ELSE 'Jasa' END
		   WHERE line_type IS NULL OR line_type = ''"""
	)
	# Only parts carry a gudang; a service is not taken out of one.
	if "warehouse" in frappe.db.get_table_columns("Repair Order"):
		frappe.db.sql(
			"""UPDATE `tabRepair Used Item` rui
			   JOIN `tabRepair Order` ro ON ro.name = rui.parent
			   SET rui.warehouse = ro.warehouse
			   WHERE rui.line_type = 'Part'
			     AND (rui.warehouse IS NULL OR rui.warehouse = '')
			     AND ro.warehouse IS NOT NULL AND ro.warehouse != ''"""
		)
	frappe.db.sql(
		"""UPDATE `tabRepair Used Item` SET warehouse = NULL WHERE line_type = 'Jasa'"""
	)
