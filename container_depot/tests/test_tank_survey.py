"""Survey Order + its tank rows — the Tank Out field survey, from schedule to EIR-Out.

Saving an outbound Container Booking schedules a day's work (``Survey Order``) with one row per
tank at ``Waiting Lowering``. An Operator Kalmar — or a surveyor already standing there — drops
the tank (``Lowered``); the surveyor then closes it (``Survey Done``), and THAT is what raises
the tank's EIR-Out.

Two things are pinned here above all, because both were got wrong once:

* **Lowering comes first.** A tank stacked three high cannot be inspected, so the old
  surveyor-then-Kalmar order produced "surveyed" tanks nobody had been able to look at.
* **The location is not stored here.** It belongs to the tank (``Container Position``) and is
  read live off the master, so a correction made anywhere shows up everywhere — and a reopen
  never retracts it.

Self-cleaning: every fixture created here is hard-deleted in tearDown.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot.container_depot import container_position as cp
from container_depot.container_depot import tank_survey as ts
from container_depot.container_depot.exceptions import AlreadySettled
from container_depot.tests.test_eir import _make_container
from container_depot.tests.test_work_claim import _user

DEPOT = "OAK1"
SCHEDULE = "Survey Order"
ROW = "Survey Order Tank"


def _purge(containers, bookings=()):
	"""Delete every row this module can create. Order matters: the bell rows, the timeline
	comments a reopen leaves and the EIR-Out a closed tank raises all outlive the schedule they
	point at, so they go first."""
	containers = [c for c in containers if c] or [""]
	bookings = list(bookings) or [""]
	orders = frappe.get_all(SCHEDULE, filters={"booking": ["in", bookings]}, pluck="name")
	if orders:
		frappe.db.delete("Notification Log", {"document_type": SCHEDULE, "document_name": ["in", orders]})
		frappe.db.delete("Comment", {"reference_doctype": SCHEDULE, "reference_name": ["in", orders]})
		frappe.db.delete(ROW, {"parent": ["in", orders]})
	frappe.db.delete("Inspection", {"container": ["in", containers]})
	frappe.db.delete("Container Position", {"container": ["in", containers]})
	frappe.db.delete(SCHEDULE, {"booking": ["in", bookings]})
	for b in bookings:
		frappe.db.delete("Container Booking Item", {"parent": b})
		frappe.db.delete("Container Booking", {"name": b})
	frappe.db.delete("Container", {"name": ["in", containers]})
	frappe.db.commit()


class _Base(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._containers = []
		self._bookings = []

	def tearDown(self):
		frappe.set_user("Administrator")
		_purge(self._containers, self._bookings)
		super().tearDown()

	def _container(self, cno, *, located="blok kanan"):
		"""A tank, by default with a location already on record.

		Located by default because that is the normal state of a yard and because an unlocated
		tank changes what :func:`ts.mark_lowered` demands — the tests that care about that say
		``located=None`` explicitly.
		"""
		c = _make_container(cno, depot=DEPOT)
		self._containers.append(c)
		if located:
			cp.record_position(c, located)
		return c

	def _booking(self, *containers, survey_date=None, plan_date=None, **extra):
		"""Minimal outbound (Tank Out) Container Booking — validation + mandatory bypassed.

		``survey_date`` defaults to tomorrow: without one the booking schedules no day at all,
		which is its own test rather than the setup for every other one.
		"""
		doc = frappe.get_doc({
			"doctype": "Container Booking", "direction": "Tank Out", "depot": DEPOT,
			"survey_date": add_days(today(), 1) if survey_date is None else survey_date,
			"plan_date": plan_date or add_days(today(), 3),
			"items": [{"container": c} for c in containers],
			**extra,
		})
		doc.flags.ignore_validate = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		self._bookings.append(doc.name)
		return doc.name

	def _order(self, booking):
		return frappe.db.get_value(SCHEDULE, {"booking": booking}, "name")

	def _rows(self, booking):
		return frappe.get_all(
			ROW, filters={"parent": self._order(booking)}, pluck="name", order_by="idx asc"
		)

	def _row(self, booking, index=0):
		return self._rows(booking)[index]

	def _val(self, row, *fields):
		return frappe.db.get_value(ROW, row, list(fields), as_dict=True)

	def _progress(self, booking):
		return frappe.db.get_value(
			SCHEDULE, self._order(booking),
			["status", "tank_count", "lowered_count", "survey_done_count", "per_surveyed", "docstatus"],
			as_dict=True,
		)


# ---------------------------------------------------------------------------
class TestProvisioning(_Base):
	def test_saving_an_outbound_draft_already_schedules_the_day(self):
		"""Provisioning happens on the DRAFT, not at submit. Getting a tank down out of a full
		stack is preparation, and preparation that starts at Submit starts too late."""
		c = self._container("TSVPROV00001")
		bk = self._booking(c)

		order = frappe.db.get_value(
			SCHEDULE, {"booking": bk}, ["name", "survey_date", "status", "tank_count"], as_dict=True
		)
		self.assertIsNotNone(order)
		self.assertEqual(str(order.survey_date), str(add_days(today(), 1)))
		self.assertEqual((order.status, order.tank_count), ("Scheduled", 1))

		row = self._val(self._row(bk), "container", "status", "target_lift_on")
		self.assertEqual(row.container, c)
		# Every tank starts stacked as far as this document is concerned — the honest default
		# even for one already on the ground, because nobody has yet said so on the record.
		self.assertEqual(row.status, ts.WAITING)
		self.assertEqual(str(row.target_lift_on), str(add_days(today(), 3)))

		# Idempotent: calling the provisioner again opens no duplicate.
		self.assertEqual(ts.provision_survey_order_for_booking(bk)["tanks"], [])
		self.assertEqual(frappe.db.count(SCHEDULE, {"booking": bk}), 1)
		self.assertEqual(len(self._rows(bk)), 1)

	def test_the_tank_row_stores_no_location(self):
		"""The whole point of the split. A copy here would be frozen at the moment the schedule
		was written and would start disagreeing with the master on the first correction."""
		self.assertFalse(frappe.get_meta(ROW).has_field("location_note"))
		self.assertFalse(frappe.get_meta(ROW).has_field("current_location"))

	def test_an_inbound_booking_schedules_nothing(self):
		"""A Tank In is the tank ARRIVING; there is nothing standing in the yard to go and find."""
		c = self._container("TSVPROV00002")
		bk = self._booking(c, direction="Tank In")
		self.assertFalse(frappe.db.exists(SCHEDULE, {"booking": bk}))

	def test_a_booking_with_no_survey_date_schedules_no_day(self):
		c = self._container("TSVPROV00003")
		bk = self._booking(c, survey_date="")
		self.assertFalse(frappe.db.exists(SCHEDULE, {"booking": bk}))

	def test_setting_the_date_later_creates_the_day(self):
		c = self._container("TSVPROV00004")
		bk = self._booking(c, survey_date="")
		frappe.db.set_value("Container Booking", bk, "survey_date", add_days(today(), 2))
		ts.provision_survey_order_for_booking(bk)

		self.assertEqual(
			str(frappe.db.get_value(SCHEDULE, {"booking": bk}, "survey_date")),
			str(add_days(today(), 2)),
		)
		self.assertEqual(len(self._rows(bk)), 1)

	def test_moving_the_date_moves_the_whole_day(self):
		c = self._container("TSVPROV00005")
		bk = self._booking(c)
		frappe.db.set_value("Container Booking", bk, "survey_date", add_days(today(), 9))
		ts.provision_survey_order_for_booking(bk)
		self.assertEqual(
			str(frappe.db.get_value(SCHEDULE, {"booking": bk}, "survey_date")),
			str(add_days(today(), 9)),
		)

	def test_adding_a_tank_to_the_booking_adds_a_row(self):
		a = self._container("TSVPROV00006")
		b = self._container("TSVPROV00007")
		bk = self._booking(a)
		self.assertEqual(len(self._rows(bk)), 1)

		# The row is added the way a correction really lands (the booking's own child table),
		# then the provisioner is re-run — which is exactly what Container Booking.on_update
		# does. Re-saving the whole booking here would trip its mandatory fields, which this
		# fixture deliberately bypasses at insert.
		booking = frappe.get_doc("Container Booking", bk)
		booking.append("items", {"container": b})
		booking.flags.ignore_validate = True
		booking.flags.ignore_mandatory = True
		booking.save(ignore_permissions=True)
		ts.provision_survey_order_for_booking(bk)

		self.assertEqual(len(self._rows(bk)), 2)

	def test_a_cancelled_booking_calls_its_day_off_without_deleting_it(self):
		"""The rows underneath are the record that somebody walked the yard, and a job that was
		called off is worth being able to see."""
		c = self._container("TSVPROV00008")
		bk = self._booking(c)
		row = self._row(bk)
		frappe.db.set_value("Container Booking", bk, "booking_status", "Cancelled")
		ts.provision_survey_order_for_booking(bk)

		self.assertEqual(frappe.db.get_value(SCHEDULE, self._order(bk), "status"), "Cancelled")
		self.assertEqual(self._val(row, "status").status, ts.CANCELLED)


# ---------------------------------------------------------------------------
class TestScheduleProgress(_Base):
	def test_progress_and_docstatus_are_a_projection_of_the_tanks(self):
		a = self._container("TSVSCHD00001")
		b = self._container("TSVSCHD00002")
		bk = self._booking(a, b)
		rows = self._rows(bk)

		p = self._progress(bk)
		self.assertEqual((p.status, p.tank_count, p.lowered_count, p.docstatus), ("Scheduled", 2, 0, 0))

		ts.mark_lowered(rows[0])
		p = self._progress(bk)
		self.assertEqual((p.status, p.lowered_count, p.survey_done_count), ("In Progress", 1, 0))

		ts.finish_survey(rows[0])
		p = self._progress(bk)
		# A finished survey has necessarily been lowered, so the "sudah turun" count is the
		# union and not just the tanks parked at Lowered.
		self.assertEqual((p.status, p.lowered_count, p.survey_done_count, p.per_surveyed),
						 ("In Progress", 1, 1, 50.0))

		ts.mark_lowered(rows[1])
		ts.finish_survey(rows[1])
		p = self._progress(bk)
		# The day closes itself, and that submit is what the `surveyPos` menu keys on.
		self.assertEqual((p.status, p.survey_done_count, p.per_surveyed, p.docstatus),
						 ("Completed", 2, 100.0, 1))

	def test_the_calendar_counts_tanks_not_bookings(self):
		"""A day's weight to a surveyor is how many tanks they have to walk to, not how many
		bookings those tanks came in on."""
		day = add_days(today(), 5)
		a = self._container("TSVCAL000001")
		b = self._container("TSVCAL000002")
		c = self._container("TSVCAL000003")
		self._booking(a, b, survey_date=day)
		bk2 = self._booking(c, survey_date=day)

		stats = ts.survey_calendar(day)["days"][str(day)]
		self.assertEqual((stats["orders"], stats["tanks"], stats["done"]), (2, 3, 0))

		row = self._row(bk2)
		ts.mark_lowered(row)
		ts.finish_survey(row)
		self.assertEqual(ts.survey_calendar(day)["days"][str(day)]["done"], 1)

	def test_the_day_list_says_how_many_tanks_are_still_up(self):
		day = add_days(today(), 6)
		a = self._container("TSVCAL000004")
		b = self._container("TSVCAL000005")
		bk = self._booking(a, b, survey_date=day)
		ts.mark_lowered(self._row(bk, 0))

		card = next(o for o in ts.list_survey_orders(day)["items"] if o["name"] == self._order(bk))
		self.assertEqual((card["tank_count"], card["lowered_count"], card["waiting_count"]), (2, 1, 1))

	def test_the_schedule_detail_leads_with_what_is_still_blocking(self):
		"""A surveyor opening this screen is looking for what is LEFT, not for what is finished."""
		a = self._container("TSVCAL000006")
		b = self._container("TSVCAL000007")
		bk = self._booking(a, b)
		rows = self._rows(bk)
		ts.mark_lowered(rows[0])
		ts.finish_survey(rows[0])

		detail = ts.get_survey_order_detail(self._order(bk))
		self.assertEqual([t["status"] for t in detail["tanks"]], [ts.WAITING, ts.DONE])
		self.assertEqual(detail["waiting_count"], 1)


# ---------------------------------------------------------------------------
class TestLocationIsReadNotStored(_Base):
	def test_the_schedule_reads_the_master_and_follows_a_correction(self):
		c = self._container("TSVLOC000001", located="blok kanan B9")
		bk = self._booking(c)

		t = ts.get_survey_order_detail(self._order(bk))["tanks"][0]
		self.assertEqual(t["location_note"], "blok kanan B9")
		self.assertTrue(t["located"])
		self.assertTrue(t["fresh"])

		# Corrected from the Letak Tank menu, with no reference to this schedule at all.
		cp.record_position(c, "ternyata kiri B4")
		t = ts.get_survey_order_detail(self._order(bk))["tanks"][0]
		self.assertEqual(t["location_note"], "ternyata kiri B4")

	def test_a_tank_nobody_has_located_says_so_rather_than_showing_a_blank(self):
		c = self._container("TSVLOC000002", located=None)
		bk = self._booking(c)
		t = ts.get_survey_order_detail(self._order(bk))["tanks"][0]
		self.assertFalse(t["located"])
		self.assertIsNone(t["location_note"])

	def test_lowering_can_file_the_new_position_in_the_same_press(self):
		"""The person who just put the tank on the ground is the one who knows where it now is —
		and it is filed as a Container Position reading, not onto the row."""
		c = self._container("TSVLOC000003", located="masih di atas, blok kanan")
		bk = self._booking(c)
		row = self._row(bk)

		ts.mark_lowered(row, location_note="ground slot depan pos")

		self.assertEqual(
			frappe.db.get_value("Container", c, "current_location"), "ground slot depan pos"
		)
		self.assertEqual(frappe.db.count("Container Position", {"container": c}), 2)

	def test_lowering_demands_a_location_only_for_a_tank_nobody_has_located(self):
		""""Sudah turun" with no place leaves the surveyor nowhere to walk — but a tank whose
		position is already on record does not need it retyped."""
		blank = self._container("TSVLOC000004", located=None)
		known = self._container("TSVLOC000005")
		bk_blank = self._booking(blank)
		bk_known = self._booking(known)

		with self.assertRaises(frappe.ValidationError):
			ts.mark_lowered(self._row(bk_blank))
		self.assertEqual(self._val(self._row(bk_blank), "status").status, ts.WAITING)

		ts.mark_lowered(self._row(bk_known))
		self.assertEqual(self._val(self._row(bk_known), "status").status, ts.LOWERED)


# ---------------------------------------------------------------------------
class TestActions(_Base):
	def test_marking_lowered_stamps_who_and_when(self):
		c = self._container("TSVACT000001")
		bk = self._booking(c)
		row = self._row(bk)

		ts.mark_lowered(row, note="ground slot")
		d = self._val(row, "status", "lowered_by", "lowered_on", "lowering_note", "surveyed_by")
		self.assertEqual(d.status, ts.LOWERED)
		self.assertEqual(d.lowered_by, "Administrator")
		self.assertIsNotNone(d.lowered_on)
		self.assertEqual(d.lowering_note, "ground slot")
		self.assertIsNone(d.surveyed_by)

	def test_lowering_twice_is_a_no_op_that_still_records_a_correction(self):
		"""A retried request from a bad signal spot must not read as a failure — but a correction
		is exactly why somebody would press it twice."""
		c = self._container("TSVACT000002")
		bk = self._booking(c)
		row = self._row(bk)
		ts.mark_lowered(row)
		first = self._val(row, "lowered_on").lowered_on

		ts.mark_lowered(row, location_note="salah baca tadi, kiri B4")
		d = self._val(row, "status", "lowered_on")
		self.assertEqual(d.status, ts.LOWERED)
		self.assertEqual(d.lowered_on, first)
		self.assertEqual(frappe.db.get_value("Container", c, "current_location"), "salah baca tadi, kiri B4")

	def test_a_survey_cannot_be_closed_before_the_tank_is_down(self):
		"""The whole reason the flow was reversed: a tank stacked three high cannot be inspected,
		so there is nothing to close."""
		c = self._container("TSVACT000003")
		bk = self._booking(c)
		with self.assertRaises(frappe.ValidationError):
			ts.finish_survey(self._row(bk))

	def test_closing_the_survey_raises_the_eir_out(self):
		c = self._container("TSVACT000004")
		bk = self._booking(c)
		row = self._row(bk)
		ts.mark_lowered(row)

		res = ts.finish_survey(row, notes="kondisi luar ok")
		self.assertEqual(res["status"], ts.DONE)
		d = self._val(row, "surveyed_by", "survey_notes", "lowered_by", "eir_out")
		self.assertEqual(d.surveyed_by, "Administrator")
		self.assertEqual(d.survey_notes, "kondisi luar ok")
		# The lowering stamps survive — closing does not overwrite who dropped the tank.
		self.assertEqual(d.lowered_by, "Administrator")

		eir = res["eir_out"]
		self.assertTrue(eir)
		self.assertEqual(d.eir_out, eir)
		row_eir = frappe.db.get_value(
			"Inspection", eir,
			["inspection_type", "docstatus", "survey_tank", "survey_order", "referred_voucher"],
			as_dict=True,
		)
		self.assertEqual(row_eir.inspection_type, "EIR-Out")
		self.assertEqual(row_eir.survey_tank, row)
		self.assertEqual(row_eir.survey_order, self._order(bk))
		# Born WITHOUT a bon — that is the whole point of moving it earlier.
		self.assertIsNone(row_eir.referred_voucher)

	def test_closing_a_closed_tank_says_it_is_settled(self):
		c = self._container("TSVACT000005")
		bk = self._booking(c)
		row = self._row(bk)
		ts.mark_lowered(row)
		ts.finish_survey(row)
		with self.assertRaises(AlreadySettled):
			ts.finish_survey(row)

	def test_only_one_eir_out_survives_a_reopen_and_a_reclose(self):
		c = self._container("TSVACT000006")
		bk = self._booking(c)
		row = self._row(bk)
		ts.mark_lowered(row)
		ts.finish_survey(row)
		ts.reopen_survey(row, note="kecepetan")
		ts.finish_survey(row)
		self.assertEqual(
			frappe.db.count("Inspection", {"container": c, "inspection_type": "EIR-Out", "docstatus": ["!=", 2]}),
			1,
		)



# ---------------------------------------------------------------------------
class TestTheStandaloneList(_Base):
	"""``list_all_survey_orders`` — the Survey Order menu, not the calendar's day list.

	The two answer different questions and neither is the other narrowed: the calendar plans a
	day, this FINDS a schedule. So this one includes finished and cancelled days, and searches
	on the tank numbers people actually have to hand.
	"""

	def test_it_lists_schedules_the_calendar_would_have_dropped(self):
		c = self._container("TSVLIST00001")
		bk = self._booking(c)
		frappe.db.set_value(SCHEDULE, self._order(bk), "status", "Cancelled")
		names = [i["name"] for i in ts.list_all_survey_orders()["items"]]
		self.assertIn(self._order(bk), names)

	def test_the_status_filter_narrows_and_the_counts_do_not(self):
		"""The chips are how the filter is CHANGED, so counting them through the current
		filter would make them all read 0 at the moment they are most needed."""
		c = self._container("TSVLIST00002")
		bk = self._booking(c)
		frappe.db.set_value(SCHEDULE, self._order(bk), "status", "Cancelled")
		out = ts.list_all_survey_orders(status="Scheduled")
		self.assertNotIn(self._order(bk), [i["name"] for i in out["items"]])
		self.assertGreaterEqual(out["counts"].get("Cancelled", 0), 1)

	def test_searching_a_tank_number_finds_the_day_it_is_on(self):
		"""Through the CHILD rows, not through `container_summary` — that field truncates with
		a `(+N)` marker, so the 12th tank of a long booking would otherwise be unfindable."""
		c = self._container("TSVLIST00003")
		bk = self._booking(c)
		names = [i["name"] for i in ts.list_all_survey_orders(search="TSVLIST00003")["items"]]
		self.assertEqual(names, [self._order(bk)])

	def test_a_search_that_matches_nothing_returns_nothing(self):
		self._booking(self._container("TSVLIST00004"))
		out = ts.list_all_survey_orders(search="NOSUCHTANK")
		self.assertEqual(out["items"], [])
		# And the total agrees. A search cannot fall back on `frappe.db.count` (which takes no
		# or_filters), and a total faked from the page size would make "Muat lagi" disappear
		# with results still unseen.
		self.assertEqual(out["total"], 0)

	def test_a_date_range_bounds_both_ends(self):
		c1 = self._container("TSVLIST00005")
		c2 = self._container("TSVLIST00006")
		bk_soon = self._booking(c1, survey_date=add_days(today(), 1))
		bk_late = self._booking(c2, survey_date=add_days(today(), 30))
		out = ts.list_all_survey_orders(
			from_date=today(), to_date=add_days(today(), 7)
		)
		names = [i["name"] for i in out["items"]]
		self.assertIn(self._order(bk_soon), names)
		self.assertNotIn(self._order(bk_late), names)

	def test_each_row_carries_what_is_still_waiting(self):
		"""The one number that says whether a day needs somebody to go out."""
		c = self._container("TSVLIST00007")
		bk = self._booking(c)
		row = next(i for i in ts.list_all_survey_orders()["items"] if i["name"] == self._order(bk))
		self.assertEqual(row["waiting_count"], 1)
		ts.mark_lowered(self._row(bk))
		row = next(i for i in ts.list_all_survey_orders()["items"] if i["name"] == self._order(bk))
		self.assertEqual(row["waiting_count"], 0)

# ---------------------------------------------------------------------------
class TestWorklists(_Base):
	def test_each_queue_shows_only_its_own_step(self):
		waiting = self._container("TSVLIST00001")
		lowered = self._container("TSVLIST00002")
		bk_w = self._booking(waiting)
		bk_l = self._booking(lowered)
		down = self._row(bk_l)
		ts.mark_lowered(down)

		self.assertIn(self._row(bk_w), {i["name"] for i in ts.list_waiting_lowering()["items"]})
		self.assertNotIn(down, {i["name"] for i in ts.list_waiting_lowering()["items"]})
		self.assertIn(down, {i["name"] for i in ts.list_ready_to_survey()["items"]})

	def test_the_queue_carries_the_location_so_the_operator_knows_where_to_walk(self):
		c = self._container("TSVLIST00003", located="blok kanan B9")
		bk = self._booking(c)
		item = next(i for i in ts.list_waiting_lowering()["items"] if i["name"] == self._row(bk))
		self.assertEqual(item["location_note"], "blok kanan B9")
		self.assertTrue(item["located"])

	def test_the_queue_leads_with_the_customers_pickup_date(self):
		"""A wash finished a day late on a tank nobody is coming for costs nothing; the same day
		lost on a tank on a truck's schedule costs a truck."""
		far = self._container("TSVSORT00001")
		soon = self._container("TSVSORT00002")
		bk_far = self._booking(far, plan_date=add_days(today(), 9))
		bk_soon = self._booking(soon, plan_date=add_days(today(), 1))
		a, b = self._row(bk_far), self._row(bk_soon)

		order = [i["name"] for i in ts.list_waiting_lowering()["items"] if i["name"] in (a, b)]
		self.assertEqual(order, [b, a])

	def test_a_cancelled_day_leaves_the_queue(self):
		c = self._container("TSVLIST00004")
		bk = self._booking(c)
		row = self._row(bk)
		self.assertIn(row, {i["name"] for i in ts.list_waiting_lowering()["items"]})

		frappe.db.set_value("Container Booking", bk, "booking_status", "Cancelled")
		ts.provision_survey_order_for_booking(bk)
		self.assertNotIn(row, {i["name"] for i in ts.list_waiting_lowering()["items"]})

	def test_riwayat_holds_the_finished_ones(self):
		c = self._container("TSVHIST00001")
		bk = self._booking(c)
		row = self._row(bk)
		ts.mark_lowered(row)
		self.assertNotIn(row, {i["name"] for i in ts.list_survey_history()["items"]})
		ts.finish_survey(row)
		self.assertIn(row, {i["name"] for i in ts.list_survey_history()["items"]})


# ---------------------------------------------------------------------------
class TestReopen(_Base):
	"""The undo this workflow has instead of a review step. With no reviewer standing behind the
	field crew, the alternative is a wrong record nobody can fix."""

	def _closed(self, cno):
		c = self._container(cno)
		bk = self._booking(c)
		row = self._row(bk)
		ts.mark_lowered(row)
		return c, bk, row, ts.finish_survey(row)["eir_out"]

	def test_reopening_the_survey_keeps_the_lowering(self):
		"""The tank was down and where it should be — the survey was just closed too early."""
		_c, _bk, row, _eir = self._closed("TSVREOP00001")
		res = ts.reopen_survey(row, note="kecepetan")
		self.assertEqual(res["status"], ts.LOWERED)

		d = self._val(row, "lowered_by", "surveyed_by", "surveyed_on", "reopen_note")
		self.assertEqual(d.lowered_by, "Administrator")
		self.assertIsNone(d.surveyed_by)
		self.assertIn("kecepetan", d.reopen_note)

	def test_reopening_the_lowering_clears_both_steps(self):
		"""A survey closed over a tank that was not down was closing over nothing."""
		_c, _bk, row, _eir = self._closed("TSVREOP00002")
		res = ts.reopen_lowering(row, note="masih di atas")
		self.assertEqual(res["status"], ts.WAITING)

		d = self._val(row, "lowered_by", "lowered_on", "surveyed_by")
		self.assertIsNone(d.lowered_by)
		self.assertIsNone(d.lowered_on)
		self.assertIsNone(d.surveyed_by)

	def test_a_reopen_never_retracts_the_position(self):
		"""The tank is standing where the last reading says it is, whatever anyone got wrong
		about the paperwork. Retracting it would send the next crew to a stale bay."""
		c, _bk, row, _eir = self._closed("TSVREOP00003")
		cp.record_position(c, "sudah di ground slot")
		ts.reopen_lowering(row, note="masih di atas")

		self.assertEqual(frappe.db.get_value("Container", c, "current_location"), "sudah di ground slot")
		self.assertEqual(frappe.db.count("Container Position", {"container": c}), 2)

	def test_reopening_withdraws_the_untouched_eir_it_authorised(self):
		"""The EIR-Out exists because the survey said the tank had been checked. Reopening
		withdraws that statement, and an EIR-Out is what lets a tank through the gate."""
		_c, _bk, row, eir = self._closed("TSVREOP00004")
		self.assertTrue(frappe.db.exists("Inspection", eir))
		ts.reopen_lowering(row, note="masih di atas")
		self.assertFalse(frappe.db.exists("Inspection", eir))
		self.assertIsNone(self._val(row, "eir_out").eir_out)

	def test_a_started_eir_is_kept_and_only_noted(self):
		"""Once a surveyor has started filling it in the work is theirs. Never silently destroy
		somebody's typing — the same rule a cancelled bon follows."""
		_c, _bk, row, eir = self._closed("TSVREOP00005")
		frappe.db.set_value("Inspection", eir, "work_started_on", frappe.utils.now_datetime())
		ts.reopen_lowering(row, note="masih di atas")
		self.assertTrue(frappe.db.exists("Inspection", eir))

	def test_reopening_refuses_a_step_nobody_took(self):
		c = self._container("TSVREOP00006")
		bk = self._booking(c)
		with self.assertRaises(frappe.ValidationError):
			ts.reopen_survey(self._row(bk))

	def test_a_redone_step_clears_the_reopen_note(self):
		"""The redo asked for is done; the reason it was sent back stops being news."""
		_c, _bk, row, _eir = self._closed("TSVREOP00007")
		ts.reopen_lowering(row, note="masih di atas")
		self.assertTrue(self._val(row, "reopen_note").reopen_note)
		ts.mark_lowered(row)
		self.assertIsNone(self._val(row, "reopen_note").reopen_note)

	def test_the_day_reopens_with_its_tank(self):
		"""``refresh_progress`` submits the schedule when the last tank closes, so a reopen has
		to push the docstatus back or the day would stay locked around an open tank."""
		_c, bk, row, _eir = self._closed("TSVREOP00008")
		self.assertEqual(self._progress(bk).docstatus, 1)
		ts.reopen_lowering(row, note="masih di atas")
		p = self._progress(bk)
		self.assertEqual((p.status, p.docstatus, p.lowered_count, p.survey_done_count),
						 ("Scheduled", 0, 0, 0))


# ---------------------------------------------------------------------------
class TestNotifications(_Base):
	def _fired(self, fn, *args, **kwargs):
		with patch("container_depot.container_depot.notify.notify") as spy:
			fn(*args, **kwargs)
		return [c.kwargs.get("event_key") for c in spy.call_args_list]

	def test_scheduling_a_day_rings_the_surveyor(self):
		c = self._container("TSVNOTIF0001")
		self.assertIn("survey_order_scheduled", self._fired(self._booking, c))

	def test_lowering_rings_the_surveyor(self):
		c = self._container("TSVNOTIF0002")
		bk = self._booking(c)
		self.assertEqual(self._fired(ts.mark_lowered, self._row(bk)), ["position_surveyed"])

	def test_closing_rings_the_eir_team(self):
		"""Closing raises the EIR-Out draft, and that draft is the next person's job — so the
		bell names it rather than letting a document appear unannounced."""
		c = self._container("TSVNOTIF0003")
		bk = self._booking(c)
		row = self._row(bk)
		ts.mark_lowered(row)
		self.assertIn("position_confirmed", self._fired(ts.finish_survey, row))

	def test_a_reopen_rings_the_queue_it_lands_in(self):
		c = self._container("TSVNOTIF0004")
		bk = self._booking(c)
		row = self._row(bk)
		ts.mark_lowered(row)
		ts.finish_survey(row)
		self.assertEqual(self._fired(ts.reopen_lowering, row, note="ulangi"),
						 ["position_survey_pending"])


# ---------------------------------------------------------------------------
class TestMenuGates(FrappeTestCase):
	"""The endpoint layer, not the logic: who may call what.

	One doctype behind two menus is exactly the shape where a gate ends up on the wrong half.
	Since the reversal the split runs the other way round — `posFix` is the lowering queue and
	keys on WRITE, `surveyPos` is the closing press and keys on SUBMIT — so Team Survey
	deliberately holds BOTH and Team Kalmar only the first.
	"""

	SURVEYOR = "tsv-gate-survey@example.com"
	KALMAR = "tsv-gate-kalmar@example.com"
	OUTSIDER = "tsv-gate-none@example.com"

	def setUp(self):
		frappe.set_user("Administrator")
		_user(self.SURVEYOR, "Team Survey")
		_user(self.KALMAR, "Team Kalmar")
		_user(self.OUTSIDER)  # a login with no depot role at all
		self.container = _make_container("TSVGATE00001", depot=DEPOT)
		cp.record_position(self.container, "blok kanan")
		booking = frappe.get_doc({
			"doctype": "Container Booking", "direction": "Tank Out", "depot": DEPOT,
			"survey_date": add_days(today(), 1), "plan_date": add_days(today(), 3),
			"items": [{"container": self.container}],
		})
		booking.flags.ignore_validate = True
		booking.insert(ignore_permissions=True, ignore_mandatory=True)
		self.booking = booking.name
		self.order = frappe.db.get_value(SCHEDULE, {"booking": self.booking}, "name")
		self.row = frappe.get_all(ROW, filters={"parent": self.order}, pluck="name")[0]

	def tearDown(self):
		frappe.set_user("Administrator")
		_purge([self.container], [self.booking])
		for email in (self.SURVEYOR, self.KALMAR, self.OUTSIDER):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, ignore_permissions=True, force=True)
		frappe.db.commit()
		super().tearDown()

	def _refused(self, user, fn, *args, **kwargs):
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			fn(*args, **kwargs)

	def test_a_surveyor_may_lower_a_tank_themselves(self):
		"""Answered 2026-09-03: somebody already standing at a tank that is plainly on the ground
		should not have to wait for an operator to open their phone."""
		from container_depot.ess import tank_survey as ess

		frappe.set_user(self.SURVEYOR)
		self.assertEqual(ess.survey_lowered(name=self.row)["status"], ts.LOWERED)

	def test_a_kalmar_operator_may_lower_but_never_close(self):
		from container_depot.ess import tank_survey as ess

		frappe.set_user(self.KALMAR)
		self.assertEqual(ess.survey_lowered(name=self.row)["status"], ts.LOWERED)
		self._refused(self.KALMAR, ess.survey_finish, name=self.row)

		frappe.set_user(self.SURVEYOR)
		self.assertEqual(ess.survey_finish(name=self.row)["status"], ts.DONE)

	def test_the_reads_and_the_lowering_undo_are_open_to_both_menus(self):
		from container_depot.ess import tank_survey as ess

		for user in (self.SURVEYOR, self.KALMAR):
			with self.subTest(user=user):
				frappe.set_user(user)
				self.assertIn("items", ess.survey_history())
				self.assertIn("items", ess.survey_waiting())
				self.assertIn("items", ess.survey_orders())
				self.assertIn("days", ess.survey_calendar())
				self.assertIn("status", ess.survey_tank_detail(name=self.row))

		# Both may send a tank back to the lowering queue — the surveyor is the one standing at
		# the empty bay, so refusing them would put the undo out of reach.
		frappe.set_user(self.SURVEYOR)
		ess.survey_lowered(name=self.row)
		frappe.set_user(self.KALMAR)
		self.assertEqual(ess.survey_reopen_lowering(name=self.row)["status"], ts.WAITING)

	def test_the_survey_undo_stays_with_the_surveyor(self):
		"""`require_any_menu` must not have leaked into the one that is single-menu."""
		from container_depot.ess import tank_survey as ess

		self._refused(self.KALMAR, ess.survey_reopen_survey, name=self.row)

	def test_an_account_with_no_depot_role_is_refused_everywhere(self):
		from container_depot.ess import tank_survey as ess

		for fn in (ess.survey_history, ess.survey_waiting, ess.survey_ready,
				   ess.survey_orders, ess.survey_calendar):
			with self.subTest(fn=fn.__name__):
				self._refused(self.OUTSIDER, fn)
		self._refused(self.OUTSIDER, ess.survey_tank_detail, name=self.row)
		self._refused(self.OUTSIDER, ess.survey_lowered, name=self.row)
