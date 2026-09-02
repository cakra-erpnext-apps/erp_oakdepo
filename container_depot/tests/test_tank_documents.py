"""The tank dossier behind an outbound booking: every document open against each tank.

Ported from the Gate Out Plan tests along with the panel itself. What matters is the split
between the two questions the panel answers side by side — ``open`` (unfinished) and
``blocks`` (unfinished AND standing between the tank and the gate).
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from container_depot.container_depot.doctype.container_booking.container_booking import (
	related_orders,
)
from container_depot.tests.test_eir import _make_container

DEPOT = "OAK1"


class TestTankDossier(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._containers = []
		self._bookings = []

	def tearDown(self):
		if self._bookings:
			frappe.db.sql(
				"""UPDATE `tabContainer` SET lift_on_booking = NULL, target_lift_on = NULL
				   WHERE lift_on_booking IN %(bookings)s""",
				{"bookings": tuple(self._bookings)},
			)
			frappe.db.delete("Container Position Survey", {"booking": ["in", self._bookings]})
			frappe.db.delete("Booking Code", {"booking": ["in", self._bookings]})
		for b in self._bookings:
			frappe.db.delete("Container Booking Item", {"parent": b})
			frappe.db.delete("Container Booking", {"name": b})
		if self._containers:
			# Storage Charge included: creating a tank opens its storage visit, and the
			# row outlives the tank it bills for unless it goes in the same sweep.
			for dt in ("Cleaning Order", "Repair Order", "Inspection", "Storage Charge"):
				frappe.db.delete(dt, {"container": ["in", self._containers]})
			frappe.db.delete("Container", {"name": ["in", self._containers]})
		frappe.db.commit()
		super().tearDown()

	def _container(self, cno):
		c = _make_container(cno, depot=DEPOT)
		self._containers.append(c)
		return c

	def _booking(self, container):
		doc = frappe.get_doc({
			"doctype": "Container Booking", "direction": "Tank Out", "depot": DEPOT,
			"items": [{"container": container, "estimation_date": today()}],
		})
		doc.flags.ignore_validate = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		self._bookings.append(doc.name)
		return doc.name

	def _by_name(self, booking):
		tanks = related_orders(booking)
		self.assertEqual(len(tanks), 1)
		return tanks[0], {o["name"]: o for o in tanks[0]["orders"]}

	def test_open_cleaning_blocks_and_is_counted_as_such(self):
		c = self._container("TDOC000001")
		bk = self._booking(c)
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": c, "status": "Service Setup",
		}).insert(ignore_permissions=True).name

		tank, by_name = self._by_name(bk)
		self.assertTrue(by_name[co]["open"])
		self.assertTrue(by_name[co]["blocks"])
		self.assertEqual(tank["blocking_count"], 1)

	def test_a_finished_cleaning_stops_blocking_but_stays_as_history(self):
		c = self._container("TDOC000002")
		bk = self._booking(c)
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": c, "status": "Completed",
		}).insert(ignore_permissions=True).name

		tank, by_name = self._by_name(bk)
		self.assertFalse(by_name[co]["open"])
		self.assertFalse(by_name[co]["blocks"])
		self.assertTrue(by_name[co]["done"])
		self.assertEqual(tank["blocking_count"], 0)

	def test_the_booking_itself_is_listed_and_says_its_bon_is_missing(self):
		"""A confirmed booking is not yet paper at the gate — the line says so.

		The tank's Booking Code is issued at submit and only leaves ``Active`` when a bon
		picks it up, so it is what answers "sudah dibonkan belum" per tank.
		"""
		c = self._container("TDOC000003")
		bk = self._booking(c)
		frappe.db.set_value("Container Booking", bk, "docstatus", 1, update_modified=False)
		frappe.get_doc({
			"doctype": "Booking Code", "code": "OAK-TDOCTEST0001", "booking": bk,
			"direction": "Tank Out", "container": c, "container_no": c, "state": "Active",
		}).insert(ignore_permissions=True)

		_tank, by_name = self._by_name(bk)
		self.assertEqual(by_name[bk]["kind"], "Booking")
		self.assertEqual(by_name[bk]["detail"], "Tank Out · belum ada bon")
		# Paperwork is tracked, never a blocker: an outbound booking IS the way out.
		self.assertFalse(by_name[bk]["blocks"])

	def test_a_tank_with_nothing_open_still_gets_a_row(self):
		""""This one is clear" is an answer the operator came for; a tank that silently
		vanished from the panel would read as one nobody had looked at."""
		c = self._container("TDOC000004")
		bk = self._booking(c)
		tank, _by_name = self._by_name(bk)
		self.assertEqual(tank["container"], c)
		self.assertEqual(tank["blocking_count"], 0)
		self.assertEqual(str(tank["target_lift_on"]), today())
