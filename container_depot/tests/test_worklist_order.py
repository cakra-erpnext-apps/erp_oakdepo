"""The order every PWA worklist puts its rows in.

Three tiers, in the order an operator asks for them (see
``container_depot.container_depot.worklist``):

1. tanks the customer has given a lift-on date for, nearest first;
2. the job already in this operator's hands;
3. everything else, oldest first.

The rule itself is tested on the pure function — no fixtures, so the tiers can be pinned
exactly, including the tie-breaks. The second test is the one that actually matters over
time: it checks that every worklist still routes through that function. They each carried
their own copy of the sort once, and the copies drifted.
"""

from __future__ import annotations

import pathlib
import re

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot.container_depot.worklist import sort_by_priority


def _row(name, lift=None, started=False):
	return {"name": name, "target_lift_on": lift, "started": started}


class TestWorklistOrder(FrappeTestCase):
	def _order(self, rows, **kw):
		return [r["name"] for r in sort_by_priority(rows, lambda r: r["started"], **kw)]

	def test_gate_out_priority_outranks_work_already_in_hand(self):
		"""The whole point of tier 1: a deadline beats a half-done job without one.

		A wash finished a day late on a tank nobody is coming for costs nothing; the same day
		lost on a tank a truck is booked for costs a truck.
		"""
		rows = [
			_row("in-hand", started=True),
			_row("booked", lift=add_days(today(), 5)),
		]
		self.assertEqual(self._order(rows), ["booked", "in-hand"])

	def test_nearest_lift_on_first(self):
		rows = [
			_row("far", lift=add_days(today(), 9)),
			_row("today", lift=today()),
			_row("soon", lift=add_days(today(), 2)),
		]
		self.assertEqual(self._order(rows), ["today", "soon", "far"])

	def test_an_overdue_pickup_leads(self):
		"""A date that has already passed is the most urgent thing on the list, not the
		least — the truck is waiting now."""
		rows = [
			_row("today", lift=today()),
			_row("late", lift=add_days(today(), -2)),
		]
		self.assertEqual(self._order(rows), ["late", "today"])

	def test_in_hand_before_untouched_within_a_tier(self):
		rows = [_row("belum"), _row("dikerjakan", started=True)]
		self.assertEqual(self._order(rows), ["dikerjakan", "belum"])
		# ...and inside one lift-on date, too.
		d = add_days(today(), 1)
		rows = [_row("belum", lift=d), _row("dikerjakan", lift=d, started=True)]
		self.assertEqual(self._order(rows), ["dikerjakan", "belum"])

	def test_unstamped_rows_sink_rather_than_float(self):
		"""An empty date must not read as "the earliest date" — that is the bug the sentinel
		in the sort key exists to prevent."""
		rows = [_row("no-date"), _row("dated", lift=add_days(today(), 30))]
		self.assertEqual(self._order(rows), ["dated", "no-date"])

	def test_the_querys_own_order_settles_the_rest(self):
		"""Python's sort is stable, so "oldest first" keeps coming from the SQL order_by and
		is not re-implemented here."""
		rows = [_row("first"), _row("second"), _row("third")]
		self.assertEqual(self._order(rows), ["first", "second", "third"])

	def test_paging_happens_after_the_sort_not_before(self):
		"""Page 1 must hold the most urgent rows, not the first rows the query happened to
		return. Sorting a single page would put the priority inside the page only."""
		rows = [
			_row("a"),
			_row("b", lift=add_days(today(), 4)),
			_row("c", lift=add_days(today(), 1)),
		]
		self.assertEqual(self._order(rows, page_length=2), ["c", "b"])
		self.assertEqual(self._order(rows, start=2, page_length=2), ["a"])

	def test_page_length_zero_means_everything(self):
		rows = [_row("a"), _row("b")]
		self.assertEqual(self._order(rows, page_length=0), ["a", "b"])
		self.assertEqual(self._order(rows), ["a", "b"])

	# --- the invariant that actually rots -------------------------------------
	WORKLISTS = [
		("container_depot", "eir.py", "_by_lift_on"),
		("container_depot", "cleaning.py", "list_open_cleaning_orders"),
		("container_depot", "mr.py", "list_open_mr_orders"),
		("container_depot", "tank_survey.py", "_list_rows"),
	]

	def test_every_worklist_sorts_through_the_shared_rule(self):
		"""One habit has to cover every queue: an operator who learns that the top of the
		cleaning list is the next pickup must be able to read the M&R list the same way.

		Checked on the source rather than by building a fixture per doctype, because what
		goes wrong here is not a wrong answer — it is somebody adding a private
		``items.sort(...)`` next to the shared call and nobody noticing for a release.
		"""
		for app_dir, filename, func in self.WORKLISTS:
			with self.subTest(module=filename):
				src = pathlib.Path(
					frappe.get_app_path("container_depot", app_dir, filename)
				).read_text()
				body = self._function_source(src, func)
				self.assertIn(
					"sort_by_priority", body,
					f"{filename}:{func} no longer sorts through worklist.sort_by_priority",
				)
				self.assertNotIn(
					".sort(", body,
					f"{filename}:{func} sorts on its own — that is how the copies drifted last time",
				)

	def _function_source(self, src: str, func: str) -> str:
		"""The lines of one top-level function, up to the next one."""
		m = re.search(rf"^def {re.escape(func)}\(", src, re.M)
		self.assertIsNotNone(m, f"{func} not found — was it renamed?")
		rest = src[m.start():]
		nxt = re.search(r"^def ", rest[1:], re.M)
		return rest[: nxt.start() + 1] if nxt else rest
