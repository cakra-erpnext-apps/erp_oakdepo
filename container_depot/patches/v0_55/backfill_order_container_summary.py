"""Backfill Order Muat / Order Bongkar ``container_summary`` from their container rows.

The field was just added so the two bon lists can show which tank a bon is for (a Desk
list column cannot render a child table). Every existing bon has it empty until re-saved
— and most of them are submitted, so they will never be re-saved. Filling it directly is
the only way the column is not blank for the entire history on the day it ships.

Value-only write, which is why it is safe on submitted documents. Idempotent: recomputing
from the same rows yields the same string.
"""

import frappe

from container_depot.container_depot.doctype.container_booking.container_booking import (
	build_container_summary,
)

# doctype -> its ``containers`` child doctype. The two bons deliberately use different
# child tables (Order Muat has its own thin row; Order Bongkar reuses the booking line),
# so the parenttype filter below is what keeps them from reading each other's rows.
_ORDERS = {
	"Order Muat": "Order Container Item",
	"Order Bongkar": "Container Booking Item",
}


def execute():
	for doctype, child in _ORDERS.items():
		if not frappe.db.has_column(doctype, "container_summary"):
			continue
		for name in frappe.get_all(doctype, pluck="name"):
			nums = frappe.get_all(
				child,
				filters={"parent": name, "parenttype": doctype},
				pluck="container_no",
				order_by="idx",
			)
			# update_modified=False: a backfill must not disturb the bon's timestamp.
			frappe.db.set_value(
				doctype,
				name,
				"container_summary",
				build_container_summary(nums),
				update_modified=False,
			)
	frappe.db.commit()
