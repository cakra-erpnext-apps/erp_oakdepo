"""Backfill Container Booking.container_summary from existing item rows.

``container_summary`` was just added to denormalise the child container numbers onto
the Desk list view + search. Existing bookings have it empty until re-saved, so fill
it directly (value-only write, safe on submitted docs). Idempotent: recomputing from
the same rows yields the same string.
"""

import frappe

from container_depot.operations.doctype.container_booking.container_booking import (
	build_container_summary,
)


def execute():
	if not frappe.db.has_column("Container Booking", "container_summary"):
		return
	names = frappe.get_all("Container Booking", pluck="name")
	for name in names:
		nums = frappe.get_all(
			"Container Booking Item",
			filters={"parent": name, "parenttype": "Container Booking"},
			pluck="container_no",
			order_by="idx",
		)
		summary = build_container_summary(nums)
		# update_modified=False: a backfill must not disturb the booking's timestamp.
		frappe.db.set_value(
			"Container Booking", name, "container_summary", summary, update_modified=False
		)
	frappe.db.commit()
