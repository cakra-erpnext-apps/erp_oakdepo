"""Backfill Jenis (``line_type``) on the Cleaning & Parts rows written before the column existed.

A cleaning line may be a part taken from stock as well as a service, so the grid now shows
Jenis the way the M&R's Service & Parts does. The controller sets it from the Item master on
every save; this fills the rows of orders nobody re-saves, so the list is never blank.
"""

import frappe


def execute():
	frappe.db.sql(
		"""UPDATE `tabCleaning Order Service` s
		JOIN `tabItem` i ON i.name = s.cleaning_item
		SET s.line_type = IF(i.is_stock_item, 'Part', 'Jasa')
		WHERE IFNULL(s.line_type, '') = ''"""
	)
