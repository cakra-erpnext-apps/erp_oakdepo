"""Give back every ``Booked`` container no live Tank In booking holds.

``Booked`` means "a Tank In booking expects this tank". Two roads left it with no booking
behind it: the Container form let a person pick Booked on a new master (now locked,
``Container.before_insert``), and cancelling a Tank In while a Tank Out also listed the tank
kept the reservation (now Tank In only, ``_container_held_by_other_booking``). Those tanks
read "Dipesan" in every list and were refused by the next booking as already spoken for.

Back to ``Gate_Out`` — the status a never-arrived tank is registered in — through the
document, so each one leaves a Container Movement row saying it was released.
"""

import frappe

from container_depot.container_depot.container_status import GATE_OUT


def execute():
	orphans = frappe.db.sql(
		"""
		SELECT c.name
		FROM `tabContainer` c
		WHERE c.status = 'Booked'
			AND NOT EXISTS (
				SELECT 1
				FROM `tabContainer Booking Item` i
				JOIN `tabContainer Booking` b ON b.name = i.parent
				WHERE i.container = c.name AND b.docstatus < 2
					AND b.direction = 'Tank In' AND IFNULL(b.booking_status, '') != 'Cancelled'
			)
		""",
		pluck=True,
	)
	frappe.flags.in_status_automation = True
	try:
		for name in orphans:
			tank = frappe.get_doc("Container", name)
			tank.status = GATE_OUT
			tank.flags.ignore_links = True
			tank.save(ignore_permissions=True)
	finally:
		frappe.flags.in_status_automation = False
	if orphans:
		print(f"Released {len(orphans)} orphan Booked container(s): {', '.join(orphans[:20])}")
