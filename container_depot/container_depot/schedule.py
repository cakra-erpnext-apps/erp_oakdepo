"""Jadwal — ONE calendar over every kind of planned depot work.

WHY THIS IS NOT "THE SURVEY CALENDAR" ANY MORE
-----------------------------------------------
The month grid was built for Survey Order and only ever showed Survey Order, which made it a
calendar that lied by omission: a Kalmar operator planning tomorrow needs to know that four
tanks are booked for washing and a truck is coming at noon, not only that three tanks want
surveying. Everything the depot plans ahead now lands on the same grid, and the crew reads one
screen instead of guessing which of four menus hides the day's other half.

WHAT DECIDES WHAT YOU SEE — PERMISSION, NEVER ROLE
--------------------------------------------------
Each source declares the doctype it reads. A source appears for a caller only when they hold
READ on that doctype, so the same screen is a wash plan for Team Cleaning, a repair plan for
Team Repair, and all four at once for SPV Lapangan — with no role name written anywhere in
this file. Adding a role, or granting an existing role read on one more doctype, changes the
calendar with no deploy. That is the same contract ``ess.context._MENU`` makes for the menu
itself, applied one level down: the menu says whether the calendar opens, the sources say what
is in it.

The consequence to keep in mind: a team with read on NOTHING scheduled gets no menu tile at
all (``_MENU``'s entry for ``schedule`` is an any-of over these four doctypes). Security is in
that position today — they hold Gate Entry and the bons, not the plans behind them. Grant them
read on Container Booking in Permission Manager and the tile appears, showing exactly the one
source they gained. Nothing here needs changing for that.

READ-ONLY, AND WHY
------------------
Nothing on this screen writes. A calendar is where work is FOUND, not done: every card carries
the route to the screen that owns the document, and that screen re-checks the permission. The
one card with no route is Container Booking — the yard has no booking screen, and inventing a
tap that lands nowhere would be worse than a card that plainly does not move.

DEPOT SCOPING
-------------
Every source is filtered through ``get_user_depots`` exactly like the worklists, so a calendar
never widens what a branch-scoped account can see.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, get_first_day, get_last_day, getdate, today

from container_depot.container_depot.user_branch import get_user_depots

# ---------------------------------------------------------------------------
# The sources
# ---------------------------------------------------------------------------
# Each entry is one KIND of planned work. `date_field` is the field that says "this is the day
# it is meant to happen" — deliberately the PLAN, never the deadline: Cleaning Order and Repair
# Order also carry `target_lift_on` (when the tank must be ready to leave), and putting a
# deadline on a calendar of intentions would show work on days nobody agreed to do it.
#
# `done` and `skip` are read against `status_field`:
#   * `skip` — never shown at all (called off; there is nothing to plan around).
#   * `done` — shown, but as finished, so a day of completed work reads green rather than
#     disappearing. A calendar that hides what was done cannot answer "did we do it".
SOURCES = [
	{
		"kind": "survey",
		"doctype": "Survey Order",
		"date_field": "survey_date",
		"status_field": "status",
		"skip": ("Cancelled",),
		"done": ("Completed",),
		"fields": ["name", "principal", "booking", "surveyor", "status", "tank_count",
				   "survey_done_count", "container_summary", "plan_date"],
		"route": "/survey-orders/order/{name}",
	},
	{
		"kind": "cleaning",
		"doctype": "Cleaning Order",
		"date_field": "plan_date",
		"status_field": "status",
		"skip": ("Cancelled",),
		"done": ("Completed",),
		"fields": ["name", "container", "container_no", "container_principal", "status",
				   "cleaning_type", "target_lift_on"],
		"route": "/cleaning?o={name}",
	},
	{
		"kind": "repair",
		"doctype": "Repair Order",
		"date_field": "plan_date",
		"status_field": "status",
		# Rejected joins Cancelled: an owner who refused the estimate has not scheduled work,
		# and leaving it on the grid would have the yard planning around a job that is off.
		"skip": ("Cancelled", "Rejected"),
		"done": ("Completed",),
		"fields": ["name", "container", "container_no", "principal", "status", "job_type",
				   "target_lift_on"],
		"route": "/mr?o={name}",
	},
	{
		"kind": "booking",
		"doctype": "Container Booking",
		"date_field": "plan_date",
		"status_field": "booking_status",
		"skip": ("Cancelled",),
		"done": ("Completed",),
		"fields": ["name", "direction", "principal", "customer", "booking_status",
				   "container_summary", "bon_status", "per_fulfilled"],
		# No PWA screen owns a booking — see the module docstring.
		"route": None,
	},
]

_BY_KIND = {s["kind"]: s for s in SOURCES}


def _visible_sources(kinds=None) -> list:
	"""The sources this caller may read, optionally narrowed to ``kinds``.

	``kinds`` is a UI filter (the chips above the grid), never a security one — a kind the
	caller cannot read is dropped by the permission check whether they asked for it or not.
	"""
	wanted = _parse_kinds(kinds)
	return [
		s for s in SOURCES
		if (not wanted or s["kind"] in wanted) and frappe.has_permission(s["doctype"], "read")
	]


def _parse_kinds(kinds) -> set:
	"""`"survey,cleaning"` / `["survey"]` / None -> a set of known kinds (empty = all)."""
	if not kinds:
		return set()
	if isinstance(kinds, str):
		kinds = [k.strip() for k in kinds.split(",")]
	return {k for k in kinds if k in _BY_KIND}


def _filters(source, start_date, end_date) -> dict:
	"""Date window + not-cancelled + the caller's depots, for one source."""
	f = {
		source["date_field"]: ["between", [str(start_date), str(end_date)]],
		# docstatus 2 is a cancelled document. Its status field usually says so too, but not
		# always — a doc cancelled straight from the Desk keeps whatever status it had.
		"docstatus": ["<", 2],
	}
	if source["skip"]:
		f[source["status_field"]] = ["not in", list(source["skip"])]
	depots = get_user_depots()
	if depots is not None:
		f["depot"] = ["in", depots or [""]]
	return f


# ---------------------------------------------------------------------------
# The month grid — one dot per day
# ---------------------------------------------------------------------------
def schedule_calendar(month=None, kinds=None) -> dict:
	"""Per-day counts for one month, split by kind, for the calendar dots.

	Returns ``{"days": {"2026-09-04": {"total": 5, "open": 2, "kinds": {...}}}, "sources": [...]}``.

	``open`` is what colours the dot: a day with work still to do is not the same day as one
	that is finished, and that difference is the only thing a 40px cell can usefully say.
	``sources`` rides along so the UI can draw its filter chips from what the caller actually
	holds rather than from a hardcoded list that would offer a chip yielding nothing.
	"""
	anchor = getdate(month or today())
	first, last = get_first_day(anchor), get_last_day(anchor)
	days: dict = {}

	for source in _visible_sources(kinds):
		# Two columns and nothing else, tallied in Python. A SQL `count(... ) as n` is refused
		# outright by `frappe.get_all` (v16 rejects function strings in SELECT), and the volume
		# does not justify dropping to raw SQL for it: one depot's month is hundreds of rows of
		# two short columns, and the row bodies are never fetched.
		rows = frappe.get_all(
			source["doctype"],
			filters=_filters(source, first, last),
			fields=[f"{source['date_field']} as d", f"{source['status_field']} as st"],
			limit_page_length=0,
		)
		for r in rows:
			if not r.d:
				continue
			day = days.setdefault(str(r.d), {"total": 0, "open": 0, "kinds": {}})
			day["total"] += 1
			day["kinds"][source["kind"]] = day["kinds"].get(source["kind"], 0) + 1
			if r.st not in source["done"]:
				day["open"] += 1

	return {"days": days, "month": str(first), "sources": _source_meta(kinds)}


def _source_meta(kinds=None) -> list:
	"""What the caller may see, in grid order — the filter chips are built from this."""
	return [{"kind": s["kind"], "doctype": s["doctype"]} for s in _visible_sources(kinds)]


# ---------------------------------------------------------------------------
# One day — the list under the grid
# ---------------------------------------------------------------------------
def schedule_day(date=None, kinds=None) -> dict:
	"""Every planned item on one day, normalised to one card shape across all four sources.

	Open work first, then by kind in the order the yard works a day (survey → cleaning →
	repair → the truck arriving), then by title. A day is read top-down looking for what is
	still outstanding, so finished cards sinking to the bottom is the whole ordering.
	"""
	day = getdate(date or today())
	items = []

	for order, source in enumerate(_visible_sources(kinds)):
		rows = frappe.get_all(
			source["doctype"],
			filters=_filters(source, day, day),
			fields=source["fields"],
			order_by="modified desc",
			limit_page_length=0,
		)
		for r in rows:
			items.append(_card(source, r, order))

	items.sort(key=lambda c: (c["done"], c["_order"], (c["title"] or "").lower()))
	for c in items:
		c.pop("_order", None)
	return {"date": str(day), "items": items, "sources": _source_meta(kinds)}


def _card(source, row, order) -> dict:
	"""One source row -> the single card shape every kind renders through.

	The normalising is the point. Four doctypes name the same idea four ways (`principal` vs
	`container_principal` vs `customer`; `status` vs `booking_status`), and pushing that into
	the Vue would mean four card components that drift apart the first time one is edited.
	"""
	kind = source["kind"]
	status = row.get(source["status_field"])
	card = {
		"kind": kind,
		"name": row.get("name"),
		"status": status,
		"done": 1 if status in source["done"] else 0,
		"route": source["route"].format(name=row.get("name")) if source["route"] else None,
		"_order": order,
	}

	if kind == "survey":
		card.update({
			"title": row.get("principal") or row.get("booking"),
			"subtitle": row.get("container_summary"),
			"meta": row.get("surveyor"),
			# The two numbers a surveyor decides by, same as the schedule card itself shows.
			"count": cint(row.get("tank_count")),
			"count_done": cint(row.get("survey_done_count")),
		})
	elif kind == "cleaning":
		card.update({
			"title": row.get("container_no") or row.get("container"),
			"subtitle": row.get("container_principal"),
			"meta": row.get("cleaning_type"),
			"container": row.get("container"),
		})
	elif kind == "repair":
		card.update({
			"title": row.get("container_no") or row.get("container"),
			"subtitle": row.get("principal"),
			"meta": row.get("job_type"),
			"container": row.get("container"),
		})
	else:  # booking
		card.update({
			"title": row.get("principal") or row.get("customer"),
			"subtitle": row.get("container_summary"),
			# The direction IS the instruction here — "Tank Out" means trucks are coming to
			# collect, "Tank In" means they are coming to drop off, and the yard preps
			# differently for each.
			"meta": row.get("direction"),
			"bon_status": row.get("bon_status"),
			"per_fulfilled": row.get("per_fulfilled"),
		})
	return card
