"""Order Bongkar (Tank In) must push arrival facts onto the Container master:
the booking's depot (always) and a In_Depot status (-> Incoming stage + movement),
without regressing a tank already further along its lifecycle.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot.container_status import PRESENT
from container_depot.state_machine import stage_for_status
from container_depot.container_depot.order_generation import make_order
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_multi_container_order import _booking_with_codes


def _container(cno, status):
	name = frappe.db.get_value("Container", {"container_no": cno})
	if name:
		frappe.db.set_value("Container", name, "status", status)
		return name
	return (
		frappe.get_doc(
			{
				"doctype": "Container",
				"container_no": cno,
				"container_type": "ISO Tank",
				"status": status,
				"principal": ensure_test_customer("Bongkar Sync Test Principal"),
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


class TestBongkarContainerSync(FrappeTestCase):
	def test_arrival_sets_depot_status_stage_and_movement(self):
		cname = _container("BKRSYNCA001", "Booked")
		booking, codes = _booking_with_codes(
			code_direction="Tank In", count=1, prefix="BKRSA0", containers=[cname]
		)
		depot = frappe.db.get_value("Container Booking", booking, "depot")
		self.assertTrue(depot, "booking should carry a depot")

		make_order(booking, codes, submit=True)

		c = frappe.get_doc("Container", cname)
		self.assertEqual(c.depot, depot)  # the fix: depot now stamped from the booking
		# PRESENT, not In_Depot specifically: arrival settles on the COMPUTED state, so a
		# tank that lands with no open work (no EIR draft in this fixture) reads Available.
		# In_Depot means "here WITH work still open" — see container_status.
		self.assertIn(c.status, PRESENT)
		# The stage follows whatever presence state the arrival settled on (auto via
		# before_save) — "In Depot" while work is open, "Ready" once nothing is.
		self.assertEqual(c.inventory_stage, stage_for_status(c.status))
		self.assertTrue(
			frappe.db.exists("Container Movement", {"container": cname, "to_status": "In_Depot"}),
			"a Status Container Movement should be logged",
		)

	def test_depot_synced_without_regressing_an_in_process_tank(self):
		cname = _container("BKRSYNCB001", "In_Depot")
		booking, codes = _booking_with_codes(
			code_direction="Tank In", count=1, prefix="BKRSB0", containers=[cname]
		)
		depot = frappe.db.get_value("Container Booking", booking, "depot")

		make_order(booking, codes, submit=True)

		c = frappe.get_doc("Container", cname)
		self.assertEqual(c.depot, depot)  # depot still synced
		self.assertIn(c.status, PRESENT)  # and the tank is still in the depot
