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
				"""UPDATE `tabContainer` SET lift_on_booking = NULL, target_lift_on = NULL,
				          target_survey_on = NULL, target_urgent_on = NULL
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
				"""UPDATE `tabContainer` SET lift_on_booking = NULL, target_lift_on = NULL,
				          target_survey_on = NULL, target_urgent_on = NULL
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


class TestUrgentPriority(FrappeTestCase):
	"""Prioritas mendesak: satu booking dinaikkan ke atas semua worklist, dan dicabut lagi.

	The sort itself is tested on the pure function in ``test_worklist_order``. What is tested
	here is the other half: that the day reaches the tank and the work already open on it,
	that letting go of it lets go everywhere, and that not everyone may declare one.
	"""

	# Field roles work the yard; they do not decide whose job jumps the queue.
	OUTSIDER = "urgency-outsider@oakdepo.test"

	def setUp(self):
		frappe.set_user("Administrator")
		self._containers = []
		self._bookings = []

	def tearDown(self):
		frappe.set_user("Administrator")
		if self._bookings:
			frappe.db.sql(
				"""UPDATE `tabContainer` SET lift_on_booking = NULL, target_lift_on = NULL,
				          target_survey_on = NULL, target_urgent_on = NULL
				   WHERE lift_on_booking IN %(bookings)s""",
				{"bookings": tuple(self._bookings)},
			)
			# set_urgent writes its audit line on the booking's timeline; the raw deletes
			# below would leave it orphaned.
			frappe.db.delete("Comment", {
				"reference_doctype": "Container Booking",
				"reference_name": ["in", self._bookings],
			})
		for b in self._bookings:
			frappe.db.delete("Container Booking Item", {"parent": b})
			frappe.db.delete("Container Booking", {"name": b})
		if self._containers:
			frappe.db.delete("Cleaning Order", {"container": ["in", self._containers]})
			frappe.db.delete("Survey Order Tank", {"container": ["in", self._containers]})
			frappe.db.delete("Container", {"name": ["in", self._containers]})
		if frappe.db.exists("User", self.OUTSIDER):
			frappe.delete_doc("User", self.OUTSIDER, force=True, ignore_permissions=True)
		frappe.db.commit()
		super().tearDown()

	# --- fixtures -------------------------------------------------------------
	def _container(self, cno):
		c = _make_container(cno, depot=DEPOT)
		self._containers.append(c)
		return c

	def _booking(self, containers, day, survey=None):
		doc = frappe.get_doc({
			"doctype": "Container Booking", "direction": "Tank Out", "depot": DEPOT,
			"plan_date": day, "survey_date": survey,
			"items": [{"container": c} for c in containers],
		})
		doc.flags.ignore_validate = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		self._bookings.append(doc.name)
		return doc

	def _cleaning(self, container):
		return frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "Service Setup",
		}).insert(ignore_permissions=True).name

	def _urgent(self, container):
		return frappe.db.get_value("Container", container, "target_urgent_on")

	def _make_outsider(self):
		frappe.get_doc({
			"doctype": "User", "email": self.OUTSIDER, "first_name": "Urgency Outsider",
			"send_welcome_email": 0, "roles": [{"role": "Team Cleaning"}],
		}).insert(ignore_permissions=True)

	# --- tests ----------------------------------------------------------------
	def test_the_urgent_day_reaches_the_tank_and_the_work_already_open_on_it(self):
		"""Same road as the plan dates: a cleaning raised before anyone declared the job
		urgent cannot inherit the day through fetch_from, so it is pushed onto it."""
		c = self._container("URGENT00001")
		co = self._cleaning(c)
		doc = self._booking([c], add_days(today(), 9))

		day = today()
		lift_on.set_urgent(doc.name, urgent_date=day)

		self.assertEqual(str(self._urgent(c)), day)
		self.assertEqual(str(frappe.db.get_value("Cleaning Order", co, "target_urgent_on")), day)
		self.assertEqual(
			str(frappe.db.get_value("Container Booking", doc.name, "urgent_date")), day
		)

	def test_the_offered_day_is_the_survey_day(self):
		"""Marking a job urgent is rarely about moving its day — it is about saying this day
		matters more than another job's earlier one."""
		c = self._container("URGENT00002")
		survey = add_days(today(), 9)
		doc = self._booking([c], add_days(today(), 10), survey=survey)

		lift_on.set_urgent(doc.name)

		self.assertEqual(str(self._urgent(c)), survey)

	def test_the_reason_lands_on_the_timeline(self):
		"""Whoever is holding the tank will ask why it jumped the queue."""
		c = self._container("URGENT00003")
		doc = self._booking([c], add_days(today(), 4))

		lift_on.set_urgent(doc.name, reason="Kapal maju sehari")

		self.assertEqual(
			frappe.db.get_value("Container Booking", doc.name, "urgent_reason"),
			"Kapal maju sehari",
		)
		self.assertTrue(frappe.db.exists("Comment", {
			"reference_doctype": "Container Booking", "reference_name": doc.name,
			"content": ["like", "%Kapal maju sehari%"],
		}))

	def test_cabut_releases_every_stamp(self):
		"""Total, and that is why the release goes back through the same sync: the orders
		opened while it was urgent have to stop reading urgent too."""
		c = self._container("URGENT00004")
		co = self._cleaning(c)
		doc = self._booking([c], add_days(today(), 3))
		lift_on.set_urgent(doc.name)
		self.assertIsNotNone(self._urgent(c))

		lift_on.clear_urgent(doc.name)

		self.assertIsNone(self._urgent(c))
		self.assertIsNone(frappe.db.get_value("Cleaning Order", co, "target_urgent_on"))
		self.assertIsNone(frappe.db.get_value("Container Booking", doc.name, "urgent_date"))

	def test_the_tank_leaving_drops_the_urgency_with_everything_else(self):
		"""A departed tank at the top of a worklist is worse than one at the bottom."""
		c = self._container("URGENT00005")
		doc = self._booking([c], add_days(today(), 1))
		lift_on.set_urgent(doc.name)

		lift_on.release_on_gate_out(c)

		self.assertIsNone(self._urgent(c))

	def test_a_field_role_may_not_declare_urgency(self):
		"""An urgency every role can grant is one every role will grant, and a queue where
		everything is first is sorted by nothing at all."""
		c = self._container("URGENT00006")
		doc = self._booking([c], add_days(today(), 2))
		self._make_outsider()

		frappe.set_user(self.OUTSIDER)
		try:
			with self.assertRaises(frappe.PermissionError):
				lift_on.set_urgent(doc.name)
			with self.assertRaises(frappe.PermissionError):
				lift_on.clear_urgent(doc.name)
		finally:
			frappe.set_user("Administrator")
		self.assertIsNone(self._urgent(c))

	def test_an_inbound_booking_has_nothing_to_hurry(self):
		"""A Tank In is the tank ARRIVING; the queue this reorders is the one preparing tanks
		to LEAVE."""
		c = self._container("URGENT00007")
		doc = frappe.get_doc({
			"doctype": "Container Booking", "direction": "Tank In", "depot": DEPOT,
			"plan_date": today(), "items": [{"container": c}],
		})
		doc.flags.ignore_validate = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		self._bookings.append(doc.name)

		with self.assertRaises(frappe.ValidationError):
			lift_on.set_urgent(doc.name)


class TestSurveyOrderUrgencyRollup(FrappeTestCase):
	"""Header Survey Order meringkas urgensi tank-tanknya.

	Urgensi hidup di booking dan turun ke BARIS tank. Daftar Jadwal Survey — Desk maupun PWA —
	membaca headernya, jadi tanpa ringkasan ini satu-satunya tempat urgensinya terbaca adalah
	sesudah jadwalnya dibuka, dan daftar itu justru yang paling sering dibaca.
	"""

	def setUp(self):
		frappe.set_user("Administrator")
		self._containers = []
		self._bookings = []
		self._schedules = []

	def tearDown(self):
		frappe.set_user("Administrator")
		for so in self._schedules:
			frappe.db.delete("Survey Order Tank", {"parent": so})
			frappe.db.delete("Survey Order", {"name": so})
		if self._bookings:
			frappe.db.sql(
				"""UPDATE `tabContainer` SET lift_on_booking = NULL, target_lift_on = NULL,
				          target_survey_on = NULL, target_urgent_on = NULL
				   WHERE lift_on_booking IN %(bookings)s""",
				{"bookings": tuple(self._bookings)},
			)
			frappe.db.delete("Comment", {
				"reference_doctype": "Container Booking",
				"reference_name": ["in", self._bookings],
			})
		for b in self._bookings:
			frappe.db.delete("Container Booking Item", {"parent": b})
			frappe.db.delete("Container Booking", {"name": b})
		if self._containers:
			frappe.db.delete("Survey Order Tank", {"container": ["in", self._containers]})
			frappe.db.delete("Container", {"name": ["in", self._containers]})
		frappe.db.commit()
		super().tearDown()

	# --- fixtures -------------------------------------------------------------
	def _container(self, cno):
		c = _make_container(cno, depot=DEPOT)
		self._containers.append(c)
		return c

	def _booking(self, containers, day):
		doc = frappe.get_doc({
			"doctype": "Container Booking", "direction": "Tank Out", "depot": DEPOT,
			"plan_date": day,
			"items": [{"container": c} for c in containers],
		})
		doc.flags.ignore_validate = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		self._bookings.append(doc.name)
		return doc

	def _schedule(self, booking, containers, day):
		doc = frappe.get_doc({
			"doctype": "Survey Order", "booking": booking, "depot": DEPOT,
			"status": "Scheduled", "survey_date": day,
			"tanks": [{"container": c, "status": "Waiting Lowering"} for c in containers],
		})
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		self._schedules.append(doc.name)
		return doc

	def _header(self, schedule):
		return frappe.db.get_value("Survey Order", schedule, "target_urgent_on")

	def _rows(self, schedule):
		return frappe.get_all(
			"Survey Order Tank", filters={"parent": schedule}, fields=["name", "container"],
		)

	# --- tests ----------------------------------------------------------------
	def test_the_header_learns_it_from_its_tanks_and_lets_go_with_them(self):
		c = self._container("URGSO00001")
		day = add_days(today(), 2)
		bk = self._booking([c], add_days(today(), 6))
		so = self._schedule(bk.name, [c], add_days(today(), 5))

		lift_on.set_urgent(bk.name, urgent_date=day)
		self.assertEqual(str(self._header(so.name)), day)

		lift_on.clear_urgent(bk.name)
		self.assertIsNone(self._header(so.name))

	def test_the_nearest_day_sets_the_pace(self):
		"""One tank mendesak sudah cukup membuat harinya mendesak, dan hari yang dihitung
		adalah yang paling dekat — bukan yang terakhir ditulis."""
		from container_depot.container_depot.doctype.survey_order.survey_order import (
			refresh_urgency,
		)

		c1 = self._container("URGSO00002")
		c2 = self._container("URGSO00003")
		bk = self._booking([c1, c2], add_days(today(), 9))
		so = self._schedule(bk.name, [c1, c2], add_days(today(), 8))

		rows = {r.container: r.name for r in self._rows(so.name)}
		frappe.db.set_value("Survey Order Tank", rows[c1], "target_urgent_on", add_days(today(), 4))
		frappe.db.set_value("Survey Order Tank", rows[c2], "target_urgent_on", add_days(today(), 1))
		refresh_urgency(so.name)

		self.assertEqual(str(self._header(so.name)), add_days(today(), 1))

	def test_a_cancelled_tank_no_longer_sets_the_pace(self):
		"""Tank yang dibatalkan bukan pekerjaan, dan tenggatnya tidak lagi mengikat."""
		from container_depot.container_depot.doctype.survey_order.survey_order import (
			refresh_urgency,
		)

		c1 = self._container("URGSO00004")
		c2 = self._container("URGSO00005")
		bk = self._booking([c1, c2], add_days(today(), 9))
		so = self._schedule(bk.name, [c1, c2], add_days(today(), 8))

		rows = {r.container: r.name for r in self._rows(so.name)}
		frappe.db.set_value("Survey Order Tank", rows[c1], "target_urgent_on", add_days(today(), 5))
		frappe.db.set_value("Survey Order Tank", rows[c2], {
			"target_urgent_on": today(), "status": "Cancelled",
		})
		refresh_urgency(so.name)

		self.assertEqual(str(self._header(so.name)), add_days(today(), 5))
