"""Jadwal — the ONE calendar over every kind of planned depot work.

Four doctypes with four different date fields and four different status vocabularies land on
one grid. What is pinned here is the part that is easy to break without noticing:

* a source appears ONLY for an account that can read its doctype — the calendar is filtered by
  permission, never by role, and a team must never learn from the grid that work exists which
  they are not allowed to open;
* the four rows normalise to ONE card shape, so the Vue never has to know which doctype it is
  drawing;
* the dot's colour is about whether anyone still has to go out, not about how much there is.

Self-cleaning: every fixture is hard-deleted in tearDown.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot.container_depot import schedule as sched
from container_depot.tests.test_eir import _make_container
from container_depot.tests.test_work_claim import _user

DEPOT = "OAK1"


class _Base(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._containers = []
		self._docs = []  # (doctype, name)
		# A year out, deliberately: the shared test site carries fixtures from every other
		# module on the next few days, and a calendar test that counts a day has to own that
		# day outright. `_mine` covers what is left.
		self.day = add_days(today(), 365)

	def tearDown(self):
		frappe.set_user("Administrator")
		for dt, name in reversed(self._docs):
			frappe.db.delete(dt, {"name": name})
		if self._containers:
			frappe.db.delete("Container", {"name": ["in", self._containers]})
		frappe.db.commit()
		super().tearDown()

	def _container(self, cno):
		c = _make_container(cno, depot=DEPOT)
		self._containers.append(c)
		return c

	def _insert(self, doctype, **values):
		"""Insert with validation off — this module tests the calendar, not the doctypes."""
		doc = frappe.get_doc({"doctype": doctype, "depot": DEPOT, **values})
		doc.flags.ignore_validate = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		self._docs.append((doctype, doc.name))
		return doc.name

	def _cleaning(self, container, *, plan_date=None, status="Pending"):
		return self._insert(
			"Cleaning Order", container=container, plan_date=plan_date or self.day, status=status
		)

	def _repair(self, container, *, plan_date=None, status="Pending"):
		return self._insert(
			"Repair Order", container=container, plan_date=plan_date or self.day, status=status
		)

	def _booking(self, *, plan_date=None, booking_status="Confirmed"):
		return self._insert(
			"Container Booking", direction="Tank Out",
			plan_date=plan_date or self.day, booking_status=booking_status,
		)

	def _mine(self, items):
		"""Only the rows THIS test created. The site is shared, so an absolute count of a day
		would pass or fail on whatever another module happened to leave behind."""
		names = {name for _dt, name in self._docs}
		return [i for i in items if i["name"] in names]

	def _items(self, date=None):
		return self._mine(sched.schedule_day(date or self.day)["items"])

	def _kinds_on(self, date=None):
		return {i["kind"] for i in self._items(date)}


# ---------------------------------------------------------------------------
class TestWhatLandsOnTheGrid(_Base):
	def test_every_kind_of_planned_work_shows_up_together(self):
		"""The whole point of the rework: one day, four sources, one list."""
		c = self._container("SCHEDALL00001")
		self._cleaning(c)
		self._repair(c)
		self._booking()
		self.assertEqual(self._kinds_on(), {"cleaning", "repair", "booking"})

	def test_a_cancelled_plan_is_not_on_the_calendar_at_all(self):
		"""Called-off work is not something to plan around, so it leaves no trace on the grid.

		Distinct from FINISHED work, which stays — see the next test. Conflating the two is
		what makes a calendar unable to answer "did we actually do it".
		"""
		c = self._container("SCHEDCANC0001")
		self._cleaning(c, status="Cancelled")
		self.assertEqual(self._kinds_on(), set())

	def test_finished_work_stays_but_is_marked_done(self):
		c = self._container("SCHEDDONE0001")
		self._cleaning(c, status="Completed")
		items = self._items()
		self.assertEqual(len(items), 1)
		self.assertTrue(items[0]["done"])

	def test_a_rejected_repair_is_treated_as_called_off(self):
		"""An owner who refused the estimate has not scheduled work. Repair Order is the one
		source with a second way of being off, and it is easy to forget."""
		c = self._container("SCHEDREJ00001")
		self._repair(c, status="Rejected")
		self.assertEqual(self._kinds_on(), set())

	def test_work_planned_for_another_day_stays_on_that_day(self):
		c = self._container("SCHEDDAY00001")
		self._cleaning(c, plan_date=add_days(self.day, 1))
		self.assertEqual(self._kinds_on(self.day), set())
		self.assertEqual(self._kinds_on(add_days(self.day, 1)), {"cleaning"})


# ---------------------------------------------------------------------------
class TestOneCardShape(_Base):
	"""Four doctypes name the same idea four ways. The server normalises; the Vue must not."""

	def test_every_card_carries_the_same_keys(self):
		c = self._container("SCHEDCARD0001")
		self._cleaning(c)
		self._repair(c)
		self._booking()
		for card in self._items():
			for key in ("kind", "name", "title", "status", "done", "route"):
				self.assertIn(key, card, f"{card.get('kind')} card is missing {key}")

	def test_a_booking_card_has_no_route_because_the_pwa_has_no_booking_screen(self):
		"""A tap that lands nowhere teaches the crew that half the calendar is broken, so the
		card says so instead. If a booking screen is ever built, this test is the reminder."""
		self._booking()
		card = self._items()[0]
		self.assertEqual(card["kind"], "booking")
		self.assertIsNone(card["route"])

	def test_the_work_cards_deep_link_to_the_screen_that_owns_them(self):
		"""And to the CURRENT route for it. These strings are the one place the server knows
		about the PWA's URLs, so a renamed route breaks here rather than in a dead tap."""
		c = self._container("SCHEDLINK0001")
		name = self._cleaning(c)
		card = next(i for i in self._items() if i["kind"] == "cleaning")
		self.assertEqual(card["route"], f"/cleaning?o={name}")
		self.assertEqual(
			sched._BY_KIND["survey"]["route"], "/survey-orders/order/{name}",
			"the survey card must point at the survey family's current route",
		)

	def test_open_work_sorts_above_finished_work(self):
		"""A day is read top-down looking for what is left."""
		c1 = self._container("SCHEDSORT0001")
		c2 = self._container("SCHEDSORT0002")
		self._cleaning(c1, status="Completed")
		self._cleaning(c2, status="Pending")
		self.assertEqual([i["done"] for i in self._items()], [0, 1])


# ---------------------------------------------------------------------------
class TestTheDots(_Base):
	def test_a_day_with_anything_open_is_an_open_day(self):
		c1 = self._container("SCHEDDOT00001")
		c2 = self._container("SCHEDDOT00002")
		self._cleaning(c1, status="Completed")
		self._cleaning(c2, status="Pending")
		day = sched.schedule_calendar(self.day)["days"][str(self.day)]
		self.assertEqual(day["total"], 2)
		self.assertEqual(day["open"], 1)

	def test_a_finished_day_is_counted_but_not_open(self):
		c = self._container("SCHEDDOT00003")
		self._cleaning(c, status="Completed")
		day = sched.schedule_calendar(self.day)["days"][str(self.day)]
		self.assertEqual((day["total"], day["open"]), (1, 0))

	def test_the_counts_are_split_by_kind(self):
		c = self._container("SCHEDDOT00004")
		self._cleaning(c)
		self._booking()
		day = sched.schedule_calendar(self.day)["days"][str(self.day)]
		self.assertEqual(day["kinds"], {"cleaning": 1, "booking": 1})


# ---------------------------------------------------------------------------
class TestPermissionIsTheFilter(_Base):
	"""The half of "universal" that is not about breadth.

	One screen, one URL, and what comes back depends entirely on the caller's DocPerms. No role
	name appears in ``container_depot.schedule`` and none should ever need to.
	"""

	def test_a_team_sees_only_the_kind_it_may_read(self):
		c = self._container("SCHEDPERM0001")
		self._cleaning(c)
		self._repair(c)
		self._booking()
		user = _user("sched.cleaning@example.com", "Team Cleaning")
		frappe.set_user(user)
		try:
			# Team Cleaning holds Cleaning Order rwcs and Repair Order nothing (§8.1), so the
			# repair plan and the booking are not merely hidden — they were never queried.
			self.assertEqual(self._kinds_on(), {"cleaning"})
		finally:
			frappe.set_user("Administrator")

	def test_the_source_list_reports_only_what_the_caller_holds(self):
		"""The UI builds its filter chips from this. A chip that can only ever return nothing
		is a worse lie than no chip."""
		user = _user("sched.cleaning@example.com", "Team Cleaning")
		frappe.set_user(user)
		try:
			kinds = {s["kind"] for s in sched.schedule_calendar(self.day)["sources"]}
			self.assertEqual(kinds, {"cleaning"})
		finally:
			frappe.set_user("Administrator")

	def test_asking_for_a_kind_you_may_not_read_returns_nothing_rather_than_everything(self):
		"""`kinds` is a UI filter, never a security one — and a filter must not be able to
		widen what it was pointed at."""
		c = self._container("SCHEDPERM0002")
		self._repair(c)
		user = _user("sched.cleaning@example.com", "Team Cleaning")
		frappe.set_user(user)
		try:
			self.assertEqual(self._mine(sched.schedule_day(self.day, kinds="repair")["items"]), [])
		finally:
			frappe.set_user("Administrator")

	def test_an_unknown_kind_is_dropped_not_treated_as_no_filter(self):
		c = self._container("SCHEDPERM0003")
		self._cleaning(c)
		# "" is what an empty set of known kinds means: no narrowing. A junk kind must not
		# silently become "show me everything".
		self.assertEqual(sched._parse_kinds("nonsense"), set())


# ---------------------------------------------------------------------------
class TestWhatSlippedFromBefore(_Base):
	"""The banner above the day list: work planned BEFORE this day that is still open.

	It is the one thing a day view cannot say on its own — yesterday's truck never came, and
	nothing on today's list mentions it — so what is pinned here is the boundary: only OPEN,
	only BEFORE, and only within the lookback.
	"""

	def _overdue(self, date=None):
		od = sched.schedule_day(date or self.day)["overdue"]
		mine = self._mine(od["items"])
		return od, mine

	def test_open_work_from_a_previous_day_is_reported(self):
		c = self._container("SCHEDOVD00001")
		self._cleaning(c, plan_date=add_days(self.day, -1))
		_od, mine = self._overdue()
		self.assertEqual([i["kind"] for i in mine], ["cleaning"])
		self.assertEqual(mine[0]["date"], str(add_days(self.day, -1)))

	def test_finished_work_from_a_previous_day_is_not_overdue(self):
		"""Done is done. A calendar that nags about completed work stops being read."""
		c = self._container("SCHEDOVD00002")
		self._cleaning(c, plan_date=add_days(self.day, -1), status="Completed")
		_od, mine = self._overdue()
		self.assertEqual(mine, [])

	def test_todays_own_work_is_not_overdue_however_open_it_is(self):
		c = self._container("SCHEDOVD00003")
		self._cleaning(c)
		_od, mine = self._overdue()
		self.assertEqual(mine, [])

	def test_work_older_than_the_lookback_is_left_alone(self):
		"""Beyond the window it is an office data-hygiene problem, not this morning's work —
		and scanning a year of four doctypes on every day-change costs more than it tells."""
		c = self._container("SCHEDOVD00004")
		self._cleaning(c, plan_date=add_days(self.day, -(sched.OVERDUE_LOOKBACK_DAYS + 1)))
		_od, mine = self._overdue()
		self.assertEqual(mine, [])

	def test_the_oldest_day_leads_and_is_reported_as_since(self):
		c = self._container("SCHEDOVD00005")
		self._cleaning(c, plan_date=add_days(self.day, -3))
		self._repair(c, plan_date=add_days(self.day, -1))
		od, mine = self._overdue()
		self.assertEqual([i["kind"] for i in mine], ["cleaning", "repair"])
		# `since` is instance-wide (the site is shared), so it can only be asserted as a bound.
		self.assertLessEqual(od["since"], str(add_days(self.day, -3)))


# ---------------------------------------------------------------------------
class TestTheClockColumn(_Base):
	"""No source in the depot schedules to the HOUR — every date field is a Date. The time a
	card carries is therefore the moment work actually started, and its absence means "not
	started", never "we lost the appointment"."""

	def test_a_card_carries_the_day_it_was_planned_for(self):
		c = self._container("SCHEDTIME0001")
		self._cleaning(c)
		self.assertEqual(self._items()[0]["date"], str(self.day))

	def test_unstarted_work_has_no_time(self):
		c = self._container("SCHEDTIME0002")
		self._cleaning(c)
		self.assertIsNone(self._items()[0]["time"])

	def test_a_started_job_reports_the_hour_it_started(self):
		c = self._container("SCHEDTIME0003")
		name = self._cleaning(c, status="In_Progress")
		frappe.db.set_value("Cleaning Order", name, "cleaning_start", f"{self.day} 08:05:00")
		self.assertEqual(self._items()[0]["time"], "08:05")

	def test_a_booking_never_claims_a_time(self):
		"""Container Booking has no time field at all; the card must say so with None rather
		than with a confident midnight."""
		self._booking()
		self.assertIsNone(self._items()[0]["time"])


# ---------------------------------------------------------------------------
class TestTheMenuGate(FrappeTestCase):
	def test_the_calendar_opens_for_anyone_who_can_read_one_kind(self):
		"""`schedule` is the only _MENU entry keyed on SEVERAL doctypes, and it is an any-of.

		Team Cleaning reads Cleaning Order and nothing else scheduled, which is enough. The
		filtering of WHAT they see is a separate job one layer down.
		"""
		from container_depot.ess.context import SCHEDULE_DOCTYPES, _may

		user = _user("sched.cleaning@example.com", "Team Cleaning")
		frappe.set_user(user)
		try:
			self.assertTrue(_may(SCHEDULE_DOCTYPES, "read"))
			self.assertFalse(_may("Repair Order", "read"))
		finally:
			frappe.set_user("Administrator")
