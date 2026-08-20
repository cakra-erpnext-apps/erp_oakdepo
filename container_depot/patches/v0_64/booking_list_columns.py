import json

import frappe

DOCTYPE = "Container Booking"
# Left to right, after the fixed Customer (title) column and before the auto-appended ID.
# `status_field` is Frappe's own indicator column — one Status, driven by booking_status
# (see container_booking_list.js), instead of the docstatus badge AND a Booking Status
# column saying the same thing twice.
FIELDS = [
	("branch", "Branch"),
	("depot", "Depot"),
	("direction", "Direction"),
	("status_field", "Status"),
	("payment_status", "Payment Status"),
	("container_summary", "Containers"),
]


def execute():
	"""Set the booking list's column order so it reads the same way as the filter row.

	Column order normally follows `field_order`, and that is spoken for: the FORM wants
	Direction first (it decides which fields are asked for at all), while the LIST reads
	better grouped by place — Branch, Depot, then Direction. `List View Settings` is the
	only lever that separates the two.

	Created ONCE and never overwritten: the same record is what the "Pilih Kolom" dialog
	writes, so re-applying our order on every migrate would quietly undo whatever the depot
	arranged for itself.
	"""
	if frappe.db.exists("List View Settings", DOCTYPE):
		return
	frappe.get_doc({
		"doctype": "List View Settings",
		"name": DOCTYPE,
		"fields": json.dumps([{"fieldname": f, "label": label} for f, label in FIELDS]),
	}).insert(ignore_permissions=True)
