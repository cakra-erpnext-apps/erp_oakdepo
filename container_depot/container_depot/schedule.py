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
from frappe.utils import add_days, cint, get_first_day, get_last_day, getdate, today

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
				   "survey_done_count", "container_summary", "plan_date", "target_urgent_on"],
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
				   "cleaning_type", "target_lift_on", "target_survey_on", "target_urgent_on",
				   "cleaning_start"],
		# When the job actually started. There is no PLANNED hour anywhere in the depot's
		# scheduling — every source is a date — so the calendar's time column shows the real
		# clock reading once work begins and stays empty before that, rather than inventing
		# an appointment nobody made.
		"time_field": "cleaning_start",
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
				   "target_lift_on", "target_survey_on", "target_urgent_on", "start_date"],
		"time_field": "start_date",
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
				   "container_summary", "bon_status", "per_fulfilled", "urgent_date"],
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


def overdue_summary(date=None, kinds=None) -> dict:
	"""Berapa pekerjaan terencana yang tanggalnya sudah lewat dan belum beres, plus hari
	tertuanya — tanpa kartu-kartunya.

	Pintu publik ke aturan yang sama yang menggambar spanduk "dari kemarin" di kalender,
	untuk pemanggil yang cuma butuh angkanya: Beranda memakainya sebagai satu baris di
	"Menunggu Anda" (``ess/home.py``). Satu aturan, dua layar — kalau keduanya menghitung
	sendiri-sendiri, cepat atau lambat angkanya berselisih dan tidak ada yang tahu mana
	yang benar.
	"""
	over = _overdue(getdate(date or today()), kinds)
	return {"count": over["count"], "since": over["since"], "kinds": over["kinds"]}


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
	items = _cards_between(day, day, kinds)
	items.sort(key=lambda c: (c["done"], c["_order"], (c["title"] or "").lower()))
	for c in items:
		c.pop("_order", None)
	return {
		"date": str(day),
		"items": items,
		"overdue": _overdue(day, kinds),
		"sources": _source_meta(kinds),
	}


def _cards_between(start, end, kinds=None, open_only=False) -> list:
	"""Every visible source's rows in a date window, as cards.

	``open_only`` drops anything already finished as well as anything cancelled — that is
	what makes a card OVERDUE rather than merely past.
	"""
	out = []
	for order, source in enumerate(_visible_sources(kinds)):
		filters = _filters(source, start, end)
		if open_only:
			# Widen the status exclusion the base filter already applies: skipped states are
			# not planned work, and done ones are not outstanding.
			filters[source["status_field"]] = ["not in", list(source["skip"]) + list(source["done"])]
		# The planned day is FILTERED on but was never selected, so the card had nothing to
		# report its own date with — which the overdue banner ("dari kemarin") depends on.
		fields = list(source["fields"])
		if source["date_field"] not in fields:
			fields.append(source["date_field"])
		rows = frappe.get_all(
			source["doctype"],
			filters=filters,
			fields=fields,
			order_by="modified desc",
			limit_page_length=0,
		)
		extras = _booking_extras(rows) if source["kind"] == "booking" else {}
		for r in rows:
			out.append(_card(source, r, order, extras.get(r.get("name")) or {}))
	return out


# How far back the "still not done" banner looks. A booking whose truck never came three
# months ago is a data-hygiene problem for the office, not something the yard can act on
# this morning — and scanning a year of four doctypes on every day-change is a cost with
# nobody to spend it on.
OVERDUE_LOOKBACK_DAYS = 30
# The banner is a nudge, not a worklist. It says how many and shows the oldest few; the rest
# are reached by going to their day.
OVERDUE_SHOWN = 10


def _overdue(day, kinds=None) -> dict:
	"""Planned work from BEFORE this day that is still open.

	The one thing a day view cannot show on its own and the yard most needs told: the truck
	that never came yesterday is still not here, and nothing on today's list says so.

	Counted relative to the SELECTED day rather than to today, so browsing forward answers
	"what will still be hanging over us by Thursday" with the same rule.
	"""
	items = _cards_between(add_days(day, -OVERDUE_LOOKBACK_DAYS), add_days(day, -1), kinds, open_only=True)
	if not items:
		return {"count": 0, "items": [], "kinds": {}, "since": None}
	items.sort(key=lambda c: (c["date"] or "", c["_order"]))
	kinds_count: dict = {}
	for c in items:
		kinds_count[c["kind"]] = kinds_count.get(c["kind"], 0) + 1
	shown = items[:OVERDUE_SHOWN]
	for c in shown:
		c.pop("_order", None)
	return {
		"count": len(items),
		"kinds": kinds_count,
		# The oldest one's day — "dari kemarin" reads very differently from "dari 3 minggu lalu".
		"since": items[0]["date"],
		"items": shown,
	}


def _booking_extras(rows) -> dict:
	"""Cargo and truck per booking, in ONE query for the whole day.

	Both live on the booking's lines, and the calendar row is the place an operator decides
	whether they are ready for this truck — "1,3-Dioxolane, truk L 9021 UT" is what they
	check the yard against. Fetched in a batch rather than per card: a busy day is a dozen
	bookings, and a dozen round-trips for two strings is how a list view gets slow.
	"""
	names = [r.get("name") for r in rows if r.get("name")]
	if not names:
		return {}
	out: dict = {}
	for line in frappe.get_all(
		"Container Booking Item",
		filters={"parent": ["in", names], "parenttype": "Container Booking"},
		fields=["parent", "cargo", "truck_plate"],
		limit_page_length=0,
	):
		slot = out.setdefault(line.parent, {"cargo": [], "truck": []})
		for key, value in (("cargo", line.cargo), ("truck", line.truck_plate)):
			if value and value not in slot[key]:
				slot[key].append(value)
	return {k: {"cargo": ", ".join(v["cargo"]), "truck": ", ".join(v["truck"])} for k, v in out.items()}


def _str_date(value) -> str | None:
	"""Tanggal sebagai string, atau None — JSON tidak punya tipe tanggal sendiri."""
	return str(value) if value else None


def _clock(value) -> str | None:
	"""A Datetime -> ``"08:00"``, or None when there is nothing to show.

	String-sliced rather than formatted through ``get_datetime``: the value arrives from the
	database already in ``YYYY-MM-DD HH:MM:SS``, and a Date field (no time at all) must come
	back as None rather than as a confident "00:00".
	"""
	if not value:
		return None
	text = str(value)
	return text[11:16] if len(text) >= 16 else None


def _card(source, row, order, extras=None) -> dict:
	"""One source row -> the single card shape every kind renders through.

	The normalising is the point. Four doctypes name the same idea four ways (`principal` vs
	`container_principal` vs `customer`; `status` vs `booking_status`), and pushing that into
	the Vue would mean four card components that drift apart the first time one is edited.
	"""
	kind = source["kind"]
	status = row.get(source["status_field"])
	planned = row.get(source["date_field"])
	card = {
		"kind": kind,
		"name": row.get("name"),
		"status": status,
		"done": 1 if status in source["done"] else 0,
		"route": source["route"].format(name=row.get("name")) if source["route"] else None,
		# The day this was planned for. Carried on every card because the same card shape is
		# reused by the overdue banner, where the date is the whole point.
		"date": str(planned) if planned else None,
		# Ditandai MENDESAK? Satu nama untuk keempat sumber, karena kartunya satu bentuk:
		# booking menyimpannya sebagai `urgent_date`, yang lain sebagai `target_urgent_on`
		# (stempel turunan dari booking itu). Kalender adalah daftar rencana, dan yang paling
		# sering ditanyakan ke rencana adalah mana yang harus didahulukan.
		"urgent": _str_date(row.get("urgent_date") or row.get("target_urgent_on")),
		# Clock time, only where one genuinely exists — the moment the crew started. Nothing
		# in the depot is scheduled to the hour, so an empty slot here means "not started",
		# never "we forgot to write the appointment down".
		"time": _clock(row.get(source.get("time_field"))) if source.get("time_field") else None,
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
		extras = extras or {}
		# The TANK leads, not the customer: a booking row is read against what is standing in
		# the yard (or about to be), and every other kind on this calendar is titled by its
		# container too. Whose booking it is moves into the line underneath, next to the two
		# things the crew checks before the truck arrives — what is in it, and which truck.
		card.update({
			"title": row.get("container_summary") or row.get("principal") or row.get("customer"),
			"subtitle": " · ".join(
				x for x in (
					row.get("principal") or row.get("customer"),
					extras.get("cargo"),
					f"truk {extras['truck']}" if extras.get("truck") else None,
				) if x
			),
			# The direction IS the instruction here — "Tank Out" means trucks are coming to
			# collect, "Tank In" means they are coming to drop off, and the yard preps
			# differently for each.
			"meta": row.get("direction"),
			"bon_status": row.get("bon_status"),
			"per_fulfilled": row.get("per_fulfilled"),
		})
	return card
