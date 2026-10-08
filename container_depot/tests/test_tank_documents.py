"""The tank dossier behind an outbound booking: what its gate-out asks of each tank.

Ported from the Gate Out Plan tests along with the panel itself. What matters is the split
between the two questions the panel answers side by side — ``open`` (unfinished) and
``blocks`` (unfinished AND standing between the tank and the gate).
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime, today

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
		self._bons = []

	def tearDown(self):
		if self._bookings:
			frappe.db.sql(
				"""UPDATE `tabContainer` SET lift_on_booking = NULL, target_lift_on = NULL
				   WHERE lift_on_booking IN %(bookings)s""",
				{"bookings": tuple(self._bookings)},
			)
			_orders = frappe.get_all("Survey Order", filters={"booking": ["in", self._bookings]}, pluck="name")
			if _orders:
				frappe.db.delete("Survey Order Tank", {"parent": ["in", _orders]})
				frappe.db.delete("Survey Order", {"name": ["in", _orders]})
			frappe.db.delete("Booking Code", {"booking": ["in", self._bookings]})
		for bon in self._bons:
			frappe.db.delete("Order Container Item", {"parent": bon})
			frappe.db.delete("Order Muat", {"name": bon})
		for b in self._bookings:
			frappe.db.delete("Container Booking Item", {"parent": b})
			frappe.db.delete("Container Booking", {"name": b})
		if self._containers:
			# Storage Charge included: creating a tank opens its storage visit, and the
			# row outlives the tank it bills for unless it goes in the same sweep.
			for dt in ("Cleaning Order", "Repair Order", "Inspection", "Storage Charge", "Container Movement"):
				frappe.db.delete(dt, {"container": ["in", self._containers]})
			frappe.db.delete("Gate Entry", {"container_no": ["in", self._containers]})
			frappe.db.delete("Container", {"name": ["in", self._containers]})
		frappe.db.commit()
		super().tearDown()

	def _container(self, cno):
		c = _make_container(cno, depot=DEPOT)
		self._containers.append(c)
		return c

	def _booking(self, container, direction="Tank Out"):
		doc = frappe.get_doc({
			"doctype": "Container Booking", "direction": direction, "depot": DEPOT,
			"plan_date": today(),
			"items": [{"container": container}],
		})
		doc.flags.ignore_validate = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		# Confirmed: a Tank Out raises its EIR-Out / survey day only at Submit (2026-10-08).
		frappe.db.set_value("Container Booking", doc.name, "docstatus", 1, update_modified=False)
		frappe.db.sql("UPDATE `tabContainer Booking Item` SET docstatus=1 WHERE parent=%s", doc.name)
		doc.reload()
		doc._provision_survey_order()
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

	def test_the_survey_order_is_listed_with_this_tank_s_own_progress(self):
		"""A survey covers a whole pickup, so the tank's line reads its ROW, not the parent.

		It was missing from the panel entirely, which is how a booking could show "belum
		selesai" without naming the one document that was actually holding it up.
		"""
		c = self._container("TDOC000005")
		bk = self._booking(c)
		svo = frappe.get_doc({
			"doctype": "Survey Order", "booking": bk, "depot": DEPOT, "survey_date": today(),
			"tanks": [{"container": c, "container_no": c, "status": "Lowered"}],
		})
		svo.flags.ignore_validate = True
		svo.insert(ignore_permissions=True, ignore_mandatory=True)

		_tank, by_name = self._by_name(bk)
		self.assertEqual(by_name[svo.name]["kind"], "Survey")
		self.assertEqual(by_name[svo.name]["status"], "Lowered")
		self.assertTrue(by_name[svo.name]["open"])
		# The EIR-Out may wait for it, but the gate does not (the bon muat is the gate-out,
		# 2026-10-08): listed, open, and holding nothing.
		self.assertFalse(by_name[svo.name]["blocks"])

	def _cleaning(self, container, created=None):
		name = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "Service Setup",
		}).insert(ignore_permissions=True).name
		if created:
			frappe.db.set_value("Cleaning Order", name, "creation", created, update_modified=False)
		return name

	def _gate_out(self, container, at, booking=None):
		"""A departure; with ``booking``, on a bon muat of that booking (``gate.depart_bon``)."""
		bon = None
		if booking:
			from container_depot.tests.test_api import ensure_test_customer
			from container_depot.tests.test_eir import _make_order_muat

			bon = _make_order_muat(ensure_test_customer("Tank Documents Co"), container)
			frappe.db.set_value("Order Muat", bon, "booking", booking, update_modified=False)
			self._bons.append(bon)
		frappe.get_doc({
			"doctype": "Gate Entry", "container_no": container, "status": "Gate_Out_Completed",
			"gate_in_timestamp": add_to_date(at, hours=-1), "gate_out_timestamp": at,
			"order_muat": bon,
		}).insert(ignore_permissions=True)

	def _eir_outs(self, booking):
		return frappe.get_all(
			"Inspection", filters={"inspection_type": "EIR-Out", "container_booking": booking}, pluck="name"
		)

	def test_other_bookings_and_the_eir_in_are_not_listed(self):
		"""Only what THIS booking's gate-out asks for (user, 2026-10-06): the Tank In that
		brought the tank, another Tank Out it sits on and the EIR-In are other stories."""
		c = self._container("TDOC000006")
		bk = self._booking(c)
		other = self._booking(c)
		inbound = self._booking(c, direction="Tank In")
		eir_in = frappe.get_doc({"doctype": "Inspection", "inspection_type": "EIR-In", "container": c})
		eir_in.flags.ignore_validate = True
		eir_in.insert(ignore_permissions=True, ignore_mandatory=True)

		_tank, by_name = self._by_name(bk)
		self.assertTrue(self._eir_outs(bk))
		for name in self._eir_outs(bk):
			self.assertEqual(by_name[name]["kind"], "EIR-Out")
		self.assertFalse({bk, other, inbound, eir_in.name, *self._eir_outs(other)} & set(by_name))
		self.assertNotIn("Container Booking", {o["doctype"] for o in by_name.values()})

	def test_a_previous_visit_s_work_is_not_listed(self):
		c = self._container("TDOC000007")
		old = self._cleaning(c, created=add_to_date(now_datetime(), days=-2))
		self._gate_out(c, add_to_date(now_datetime(), days=-1))
		bk = self._booking(c)
		new = self._cleaning(c)

		_tank, by_name = self._by_name(bk)
		self.assertIn(new, by_name)
		self.assertNotIn(old, by_name)

	def test_a_tank_gone_on_this_booking_keeps_that_stay(self):
		"""Once the tank has left on this booking the panel still shows THAT stay — not the
		next one's work — and nothing on it holds a gate-out any more."""
		c = self._container("TDOC000008")
		bk = self._booking(c)
		stay = self._cleaning(c, created=add_to_date(now_datetime(), hours=-2))
		self._gate_out(c, add_to_date(now_datetime(), hours=-1), booking=bk)
		next_visit = self._cleaning(c)

		tank, by_name = self._by_name(bk)
		self.assertIn(stay, by_name)
		self.assertNotIn(next_visit, by_name)
		self.assertFalse(by_name[stay]["blocks"])
		self.assertEqual(tank["blocking_count"], 0)

	def test_a_tank_with_nothing_open_still_gets_a_row(self):
		""""This one is clear" is an answer the operator came for; a tank that silently
		vanished from the panel would read as one nobody had looked at."""
		c = self._container("TDOC000004")
		bk = self._booking(c)
		tank, _by_name = self._by_name(bk)
		self.assertEqual(tank["container"], c)
		self.assertEqual(tank["blocking_count"], 0)
		self.assertEqual(str(tank["target_lift_on"]), today())
