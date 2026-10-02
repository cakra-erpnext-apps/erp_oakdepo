"""Give every live Tank Out booking its EIR-Out drafts now that they are born with the booking.

Until 2026-10-02 a booking that used a survey got its EIR-Out only when the survey row was
closed, so a survey nobody did left the tank with no EIR-Out at all — no way out of the depot,
and a Used Booking Code that refused the next outbound booking for the same tank
(BKG-OUT-2026-00004 in the first trial week). ``provision_eir_out_for_booking`` now raises them
for every booking; this runs it once over the bookings already confirmed. Idempotent: a tank
that already has an EIR-Out for the booking, or has already left, gets nothing.
"""

import frappe

from container_depot.container_depot.eir import provision_eir_out_for_booking


def execute():
	for name in frappe.get_all(
		"Container Booking",
		filters={
			"direction": "Tank Out",
			"docstatus": 1,
			"booking_status": ["not in", ("Cancelled", "Completed")],
		},
		pluck="name",
	):
		provision_eir_out_for_booking(name)
