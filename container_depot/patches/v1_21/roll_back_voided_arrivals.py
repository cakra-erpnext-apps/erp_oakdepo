import frappe

from container_depot.container_depot.container_status import PRESENT
from container_depot.container_depot.doctype.order_bongkar.order_bongkar import roll_back_arrival


def execute():
	"""Tanks left in the yard by a voided Order Bongkar (user, 2026-10-09: RLTU 3078578).

	Voiding the bon skipped the roll-back whenever the tank had work on it — a started EIR-In
	draft the cancel itself kept, or any open order. A tank is caught here when it is PRESENT
	and the newest bon that carried it, in or out, is a voided Order Bongkar: nothing live has
	put it in the yard since. Its work is left alone, as the cancel now leaves it."""
	rows = frappe.db.sql(
		"""
		SELECT c.name AS container, c.status, c.ex_vessel,
		       (SELECT b.name FROM `tabContainer Booking Item` i
		          JOIN `tabOrder Bongkar` b ON b.name = i.parent AND i.parenttype = 'Order Bongkar'
		         WHERE i.container = c.name ORDER BY b.creation DESC LIMIT 1) AS bon
		  FROM tabContainer c
		 WHERE c.status IN %(present)s
		""",
		{"present": tuple(PRESENT)},
		as_dict=True,
	)
	for r in rows:
		if not r.bon or frappe.db.get_value("Order Bongkar", r.bon, "docstatus") != 2:
			continue
		bon = frappe.get_doc("Order Bongkar", r.bon)
		later_muat = frappe.db.sql(
			"""SELECT 1 FROM `tabOrder Container Item` i JOIN `tabOrder Muat` m ON m.name = i.parent
			 WHERE i.parenttype = 'Order Muat' AND i.container = %s AND m.docstatus < 2 AND m.creation > %s
			 LIMIT 1""",
			(r.container, bon.creation),
		)
		if later_muat:
			continue
		try:
			back_to = roll_back_arrival(bon, r.container, r)
			frappe.logger().info(f"roll_back_voided_arrivals: {r.container} {r.status} -> {back_to} ({bon.name})")
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"roll_back_voided_arrivals {r.container}")
