"""Lift-on priority: the outbound booking's date, stamped on the tank and its open work.

The behaviour that used to live in Gate Out Plan. What matters here is WHEN it happens
(from the draft, not at submit) and that it is released again by every road out — the row
dropped, the booking voided, the tank gone.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot.container_depot import lift_on
from container_depot.tests.test_eir import _make_container

DEPOT = "OAK1"


class TestLiftOnPriority(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._containers = []
		self._bookings = []

	def tearDown(self):
		# The stamp is a Link back to the booking, and these purges are raw deletes — release
		# it before the booking row goes or the next save of the tank dies on link validation.
		if self._bookings:
			frappe.db.sql(
				"""UPDATE `tabContainer` SET lift_on_booking = NULL, target_lift_on = NULL
				   WHERE lift_on_booking IN %(bookings)s""",
				{"bookings": tuple(self._bookings)},
			)
		for b in self._bookings:
			frappe.db.delete("Container Booking Item", {"parent": b})
			frappe.db.delete("Container Booking", {"name": b})
		if self._containers:
			frappe.db.delete("Cleaning Order", {"container": ["in", self._containers]})
			frappe.db.delete("Container Position Survey", {"container": ["in", self._containers]})
			frappe.db.delete("Container", {"name": ["in", self._containers]})
		frappe.db.commit()
		super().tearDown()

	# --- fixtures -------------------------------------------------------------
	def _container(self, cno):
		c = _make_container(cno, depot=DEPOT)
		self._containers.append(c)
		return c

	def _booking(self, rows, direction="Tank Out"):
		"""Outbound draft carrying ``[(container, tanggal_muat)]``. Validation is bypassed —
		pricing and the payment gate say nothing about the lift-on stamp."""
		doc = frappe.get_doc({
			"doctype": "Container Booking", "direction": direction, "depot": DEPOT,
			"items": [{"container": c, "tanggal_muat": d} for c, d in rows],
		})
		doc.flags.ignore_validate = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		self._bookings.append(doc.name)
		return doc

	def _stamp(self, container):
		return frappe.db.get_value(
			"Container", container, ["target_lift_on", "lift_on_booking"], as_dict=True
		)

	def _cleaning(self, container):
		return frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "Service Setup",
		}).insert(ignore_permissions=True).name

	# --- tests ----------------------------------------------------------------
	def test_a_draft_already_stamps_the_tank(self):
		"""Not at submit. The booking is written days ahead so the yard can prepare; a
		deadline that only appears at Submit appears after the preparation time is spent."""
		c = self._container("LIFTON00001")
		day = add_days(today(), 4)
		doc = self._booking([(c, day)])

		stamp = self._stamp(c)
		self.assertEqual(str(stamp.target_lift_on), day)
		self.assertEqual(stamp.lift_on_booking, doc.name)
		self.assertEqual(doc.docstatus, 0, "still a draft")

	def test_the_date_reaches_the_work_already_open_on_the_tank(self):
		"""A cleaning raised BEFORE the booking cannot inherit the date through fetch_from —
		it is pushed onto it, which is what puts it at the top of the wash worklist."""
		c = self._container("LIFTON00002")
		co = self._cleaning(c)
		day = add_days(today(), 2)
		self._booking([(c, day)])
		self.assertEqual(str(frappe.db.get_value("Cleaning Order", co, "target_lift_on")), day)

	def test_moving_the_date_moves_it_everywhere(self):
		c = self._container("LIFTON00003")
		co = self._cleaning(c)
		doc = self._booking([(c, add_days(today(), 2))])

		later = add_days(today(), 8)
		doc.items[0].tanggal_muat = later
		doc.save(ignore_permissions=True)

		self.assertEqual(str(self._stamp(c).target_lift_on), later)
		self.assertEqual(str(frappe.db.get_value("Cleaning Order", co, "target_lift_on")), later)

	def test_dropping_the_row_releases_the_tank(self):
		c1 = self._container("LIFTON00004")
		c2 = self._container("LIFTON00005")
		day = add_days(today(), 3)
		doc = self._booking([(c1, day), (c2, day)])

		doc.items = [r for r in doc.items if r.container == c1]
		doc.save(ignore_permissions=True)

		self.assertEqual(str(self._stamp(c1).target_lift_on), day)
		self.assertIsNone(self._stamp(c2).target_lift_on)
		self.assertIsNone(self._stamp(c2).lift_on_booking)

	def test_a_voided_draft_owns_nothing(self):
		c = self._container("LIFTON00006")
		doc = self._booking([(c, add_days(today(), 3))])
		self.assertIsNotNone(self._stamp(c).target_lift_on)

		from container_depot.container_depot.doctype.container_booking.container_booking import (
			void_draft,
		)

		void_draft(doc.name)
		self.assertIsNone(self._stamp(c).target_lift_on)
		self.assertIsNone(self._stamp(c).lift_on_booking)

	def test_gate_out_releases_the_stamp(self):
		"""The pickup happened — a departed tank must stop leading worklists, and the
		customer's next booking has to be able to claim it."""
		c = self._container("LIFTON00007")
		self._booking([(c, add_days(today(), 1))])
		lift_on.release_on_gate_out(c)
		self.assertIsNone(self._stamp(c).target_lift_on)

	def test_an_inbound_booking_stamps_nothing(self):
		"""A Tank In is the tank ARRIVING; there is no pickup to prepare for."""
		c = self._container("LIFTON00008")
		self._booking([(c, add_days(today(), 3))], direction="Tank In")
		self.assertIsNone(self._stamp(c).target_lift_on)

	def test_a_release_never_clobbers_another_bookings_stamp(self):
		"""Two bookings can end up naming one tank (a draft conflict is caught elsewhere, and
		on older data both can exist). Whoever does NOT own the stamp must not clear it."""
		c = self._container("LIFTON00009")
		day = add_days(today(), 5)
		owner = self._booking([(c, day)])
		other = self._booking([(c, add_days(today(), 6))])
		# The second save took ownership; the first one releasing must leave it alone.
		self.assertEqual(self._stamp(c).lift_on_booking, other.name)
		lift_on.clear_target(c, owner.name)
		self.assertEqual(self._stamp(c).lift_on_booking, other.name)
