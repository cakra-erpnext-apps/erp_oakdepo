"""Give every Cleaning Order and Repair Order its own date before billing reads it.

Since 2026-10-02 the billing period is the order's own date (``plan_date``: Tanggal Cleaning /
Tanggal M&R), not when the work ended. A Repair Order's ``plan_date`` was never required, so
an old one could be empty and would silently drop out of every billing window. It takes the
date that used to bill it (``completion_date`` / ``cleaning_end``), so nothing moves period.
"""

import frappe


def execute():
	frappe.db.sql(
		"""update `tabRepair Order`
		set plan_date = date(coalesce(completion_date, order_created, creation))
		where plan_date is null"""
	)
	frappe.db.sql(
		"""update `tabCleaning Order`
		set plan_date = date(coalesce(cleaning_end, order_created, creation))
		where plan_date is null"""
	)
