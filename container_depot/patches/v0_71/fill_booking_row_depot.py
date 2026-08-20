"""Fill the depot now mirrored on each Container Booking row.

An outbound booking no longer carries one depot in its header — a branch running two yards
routinely splits one customer's tanks across both — so the depot is read per row, fetched
from the Container master. Rows written before the field existed hold nothing until their
booking happens to be saved again, which for a submitted booking may be never.

The header is deliberately left alone. On these legacy bookings every tank was in one depot
(the old rule refused anything else), so the header is still a true answer for them, and it
is what an EIR raised from such a booking already recorded.
"""

import frappe


def execute():
	frappe.reload_doc("container_depot", "doctype", "container_booking_item")
	rows = frappe.get_all(
		"Container Booking Item",
		filters={
			"parenttype": "Container Booking",
			"container": ["is", "set"],
			"depot": ["is", "not set"],
		},
		fields=["name", "container"],
	)
	if not rows:
		return
	depot = {
		c.name: c.depot
		for c in frappe.get_all(
			"Container",
			filters={"name": ["in", list({r.container for r in rows})]},
			fields=["name", "depot"],
		)
	}
	for r in rows:
		if depot.get(r.container):
			frappe.db.set_value(
				"Container Booking Item", r.name, "depot", depot[r.container],
				update_modified=False,
			)
