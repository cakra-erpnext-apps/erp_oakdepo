import frappe


def execute():
	"""EIR status catches up with 2026-10-09: a started draft reads In Progress, and an EIR voided
	from draft (the red Cancel = discard, which skipped on_cancel) reads Cancelled."""
	frappe.db.sql(
		"""UPDATE tabInspection SET status = 'In Progress'
		 WHERE docstatus = 0 AND status = 'Draft' AND work_started_on IS NOT NULL"""
	)
	frappe.db.sql("UPDATE tabInspection SET status = 'Cancelled' WHERE docstatus = 2 AND status != 'Cancelled'")
