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
			frappe.db.delete("Survey Order Tank", {"container": ["in", self._containers]})
			frappe.db.delete("Container Position", {"container": ["in", self._containers]})
			frappe.db.delete("Container", {"name": ["in", self._containers]})
		frappe.db.commit()
		super().tearDown()

	# --- fixtures -------------------------------------------------------------
	def _container(self, cno):
		c = _make_container(cno, depot=DEPOT)
		self._containers.append(c)
		return c

	def _booking(self, containers, day, direction="Tank Out"):
		"""Outbound draft for ``containers``, planned for ``day``. One date for the whole
		booking — that is where the deadline lives. Validation is bypassed: pricing and the
		payment gate say nothing about the lift-on stamp."""
		doc = frappe.get_doc({
			"doctype": "Container Booking", "direction": direction, "depot": DEPOT,
			"plan_date": day,
			"items": [{"container": c} for c in containers],
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
		doc = self._booking([c], day)

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
		self._booking([c], day)
		self.assertEqual(str(frappe.db.get_value("Cleaning Order", co, "target_lift_on")), day)

	def test_moving_the_date_moves_it_everywhere(self):
		c = self._container("LIFTON00003")
		co = self._cleaning(c)
		doc = self._booking([c], add_days(today(), 2))

		later = add_days(today(), 8)
		doc.plan_date = later
		doc.save(ignore_permissions=True)

		self.assertEqual(str(self._stamp(c).target_lift_on), later)
		self.assertEqual(str(frappe.db.get_value("Cleaning Order", co, "target_lift_on")), later)

	def test_dropping_the_row_releases_the_tank(self):
		c1 = self._container("LIFTON00004")
		c2 = self._container("LIFTON00005")
		day = add_days(today(), 3)
		doc = self._booking([c1, c2], day)

		doc.items = [r for r in doc.items if r.container == c1]
		doc.save(ignore_permissions=True)

		self.assertEqual(str(self._stamp(c1).target_lift_on), day)
		self.assertIsNone(self._stamp(c2).target_lift_on)
		self.assertIsNone(self._stamp(c2).lift_on_booking)

	def test_a_voided_draft_owns_nothing(self):
		c = self._container("LIFTON00006")
		doc = self._booking([c], add_days(today(), 3))
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
		self._booking([c], add_days(today(), 1))
		lift_on.release_on_gate_out(c)
		self.assertIsNone(self._stamp(c).target_lift_on)

	def test_an_inbound_booking_stamps_nothing(self):
		"""A Tank In is the tank ARRIVING; there is no pickup to prepare for."""
		c = self._container("LIFTON00008")
		self._booking([c], add_days(today(), 3), direction="Tank In")
		self.assertIsNone(self._stamp(c).target_lift_on)

	def test_a_release_never_clobbers_another_bookings_stamp(self):
		"""Two bookings can end up naming one tank (a draft conflict is caught elsewhere, and
		on older data both can exist). Whoever does NOT own the stamp must not clear it."""
		c = self._container("LIFTON00009")
		day = add_days(today(), 5)
		owner = self._booking([c], day)
		other = self._booking([c], add_days(today(), 6))
		# The second save took ownership; the first one releasing must leave it alone.
		self.assertEqual(self._stamp(c).lift_on_booking, other.name)
		lift_on.clear_target(c, owner.name)
		self.assertEqual(self._stamp(c).lift_on_booking, other.name)


class TestOutboundFulfilment(FrappeTestCase):
	"""% Keluar on an outbound booking: how much of it has actually left."""

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
		for b in self._bookings:
			frappe.db.delete("Container Booking Item", {"parent": b})
			frappe.db.delete("Container Booking", {"name": b})
		if self._containers:
			frappe.db.delete("Survey Order Tank", {"container": ["in", self._containers]})
			frappe.db.delete("Container Position", {"container": ["in", self._containers]})
			frappe.db.delete("Container", {"name": ["in", self._containers]})
		frappe.db.commit()
		super().tearDown()

	def _booking(self, containers, *, submitted=True):
		doc = frappe.get_doc({
			"doctype": "Container Booking", "direction": "Tank Out", "depot": DEPOT,
			"booking_status": "Confirmed" if submitted else "Draft",
			"plan_date": today(),
			"items": [{"container": c} for c in containers],
		})
		doc.flags.ignore_validate = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		self._bookings.append(doc.name)
		if submitted:
			frappe.db.set_value("Container Booking", doc.name, "docstatus", 1, update_modified=False)
		return doc.name

	def _container(self, cno):
		c = _make_container(cno, depot=DEPOT)
		self._containers.append(c)
		return c

	def _per(self, booking):
		return frappe.db.get_value(
			"Container Booking", booking, ["per_fulfilled", "booking_status"], as_dict=True
		)

	def test_part_collected_reads_as_progress_and_closes_at_100(self):
		"""A bon carries at most two tanks, so a five-tank lift-on spends most of its life
		part-collected — and used to look exactly like one nobody had started."""
		a, b = self._container("LIFTFUL0001"), self._container("LIFTFUL0002")
		bk = self._booking([a, b])

		lift_on.refresh_fulfilment(bk)
		self.assertEqual(self._per(bk).per_fulfilled, 0)

		frappe.db.set_value("Container", a, "status", "Gate_Out")
		self.assertFalse(lift_on.refresh_fulfilment(bk))
		self.assertEqual(self._per(bk).per_fulfilled, 50)
		self.assertEqual(self._per(bk).booking_status, "Confirmed")

		frappe.db.set_value("Container", b, "status", "Gate_Out")
		self.assertTrue(lift_on.refresh_fulfilment(bk), "reaching 100% closes it")
		state = self._per(bk)
		self.assertEqual(state.per_fulfilled, 100)
		self.assertEqual(state.booking_status, "Completed")

	def test_a_draft_never_closes(self):
		"""Closing is a thing that happens to a booking that started; a draft has not."""
		c = self._container("LIFTFUL0003")
		bk = self._booking([c], submitted=False)
		frappe.db.set_value("Container", c, "status", "Gate_Out")
		self.assertFalse(lift_on.refresh_fulfilment(bk))
		self.assertEqual(self._per(bk).booking_status, "Draft")

	def test_an_inbound_booking_has_no_percentage(self):
		c = self._container("LIFTFUL0004")
		doc = frappe.get_doc({
			"doctype": "Container Booking", "direction": "Tank In", "depot": DEPOT,
			"items": [{"container": c}],
		})
		doc.flags.ignore_validate = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		self._bookings.append(doc.name)
		frappe.db.set_value("Container", c, "status", "Gate_Out")
		self.assertFalse(lift_on.refresh_fulfilment(doc.name))
		self.assertEqual(frappe.db.get_value("Container Booking", doc.name, "per_fulfilled"), 0)
