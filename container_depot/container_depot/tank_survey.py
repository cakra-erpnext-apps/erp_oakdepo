"""The Tank Out field survey: one Survey Order per outbound booking, one row per tank.

Deliberately free of ``@frappe.whitelist`` so the exact same functions back both the ESS PWA
wrappers (``ess/tank_survey.py``) and any Desk / automation caller — the endpoint layer only
adds auth + whitelisting.

THE CHAIN
---------
Saving a Container Booking (Tank Out) provisions the whole thing::

    Container Booking (Tank Out, survey_date)
        -> Survey Order                    one per booking: the day's field job
            -> Survey Order Tank           one row per tank, Waiting Lowering
                -> mark_lowered()          Kalmar, or a surveyor already at the tank
                -> finish_survey()         Surveyor only -> raises the tank's EIR-Out

LOWERING COMES FIRST, AND WHY THAT IS A REVERSAL
------------------------------------------------
This workflow used to run surveyor-then-Kalmar: the surveyor wrote down where the tank was and
the Kalmar operator confirmed "udah turun" afterwards. That is backwards on the ground. A tank
stacked three high cannot be inspected at all, so the survey is not possible until the lowering
has already happened. Recording it the other way round produced "surveyed" tanks nobody had
been able to look at.

WHERE THE TANK IS DOES NOT LIVE HERE
------------------------------------
Position is a fact about the tank, recorded by anyone at any time (``container_position``) and
mirrored onto the ``Container`` master with the moment it was taken. Every list and detail
below JOINS it in live rather than storing a copy, and carries the timestamp with it — the age
of the answer is half of what the operator needs. :func:`mark_lowered` can file a fresh reading
in the same press, because the person who just put the tank on the ground is the one who knows.

NO REVIEW STEP, AND WHY THE REOPEN IS NOT OPTIONAL
--------------------------------------------------
Cleaning and M&R park a finished job in ``Pending Review`` so Admin Ops can check it. This
workflow has no such step: it carries no money and touches no invoice. The price of dropping
the review is that the field must be able to undo its own step, so :func:`reopen_lowering` and
:func:`reopen_survey` push a finished tank back — clearing exactly the stamps of the step being
redone and nothing else.

NO CLAIM / "MULAI" PRESS
------------------------
Both presses are single, instantaneous acts performed by someone already standing at the tank.
There is no interval to claim, and the status check already makes a second press a no-op.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, get_first_day, get_last_day, getdate, now_datetime, today

from container_depot.container_depot.container_position import _age, _attach_photos
from container_depot.container_depot.doctype.survey_order.survey_order import (
	COMPLETED,
	IN_PROGRESS,
	SCHEDULED,
	refresh_progress,
)
from container_depot.container_depot.exceptions import AlreadySettled
from container_depot.container_depot.notify import (
	notify_position_lowered,
	notify_survey_done,
	notify_survey_order_scheduled,
	notify_waiting_lowering,
)
from container_depot.container_depot.user_branch import assert_in_user_branch, get_user_depots
from container_depot.container_depot.worklist import sort_by_priority

SCHEDULE = "Survey Order"
ROW = "Survey Order Tank"

WAITING = "Waiting Lowering"
LOWERED = "Lowered"
DONE = "Survey Done"
CANCELLED = "Cancelled"

# Only an outbound booking schedules a survey. A Tank In is the tank ARRIVING; there is nothing
# standing in the yard to go and find.
OUTBOUND = "Tank Out"

# The tank facts every screen wants beside a row, read from the master rather than stored.
_TANK_FIELDS = ["container_no", "principal", "current_location", "location_updated_on",
				"location_updated_by", "status"]


def _depot_filter(filters: dict) -> dict:
	"""Scope a query to the depots the caller's branch may see. ``None`` = unrestricted."""
	depots = get_user_depots()
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]  # restricted user: only their depots
	return filters


def _attach_positions(rows) -> list:
	"""Join each row's live location off the Container master, in ONE query for the page.

	Row-by-row lookups are what make a 50-tank day feel slow on a handset, and the answer is
	the same shape for every row. ``located`` / ``fresh`` / ``hours`` come along because every
	screen that shows a position also has to say how much to trust it.
	"""
	names = [r.get("container") for r in rows if r.get("container")]
	tanks = {}
	if names:
		tanks = {
			t.name: t
			for t in frappe.get_all(
				"Container", filters={"name": ["in", list(set(names))]},
				fields=["name"] + _TANK_FIELDS,
			)
		}
	for r in rows:
		t = tanks.get(r.get("container")) or frappe._dict()
		r["container_no"] = r.get("container_no") or t.get("container_no")
		r["principal"] = t.get("principal")
		r["tank_status"] = t.get("status")
		r["location_note"] = t.get("current_location")
		r["located"] = bool(t.get("current_location"))
		r["location_updated_by"] = t.get("location_updated_by")
		r.update(_age(t.get("location_updated_on")))
		r["location_updated_on"] = str(t["location_updated_on"]) if t.get("location_updated_on") else None
		for k in ("target_lift_on", "lowered_on", "surveyed_on"):
			if r.get(k):
				r[k] = str(r[k])
	return rows


# ---------------------------------------------------------------------------
# Provisioning — Container Booking (Tank Out) save hook
# ---------------------------------------------------------------------------
def provision_survey_order_for_booking(booking_name: str) -> dict:
	"""Keep one ``Survey Order`` and one tank row per container in step with a Tank Out booking.

	Runs from the DRAFT, not from submit: getting a tank down out of a full stack is
	preparation, and preparation that starts at Submit starts too late — an outbound booking is
	written days ahead precisely so the yard can get ready.

	Idempotent and re-runnable: the schedule is created once and then UPDATED (a moved
	``survey_date`` moves the whole day), rows are added for containers that have none and are
	never duplicated. Best-effort — a failure is logged and never blocks saving the booking.

	Returns ``{"survey_order": name|None, "tanks": [container, ...]}``. The schedule is ``None``
	when the booking has no ``survey_date`` yet: there is no day to put on a calendar.
	"""
	booking = frappe.db.get_value(
		"Container Booking",
		booking_name,
		["name", "direction", "booking_status", "docstatus", "depot", "branch",
		 "survey_date", "plan_date", "principal", "surveyor"],
		as_dict=True,
	)
	if not booking or booking.direction != OUTBOUND:
		return {"survey_order": None, "tanks": []}

	dead = booking.booking_status == "Cancelled" or int(booking.docstatus or 0) == 2
	existing = frappe.db.get_value(SCHEDULE, {"booking": booking.name, "docstatus": ["!=", 2]}, "name")

	if dead:
		# A called-off day is marked, never deleted: the rows underneath are the record that
		# somebody walked the yard, and a job that was cancelled is worth being able to see.
		if existing:
			frappe.db.set_value(SCHEDULE, existing, "status", CANCELLED, update_modified=False)
			frappe.db.set_value(
				ROW, {"parent": existing, "status": ["!=", DONE]}, "status", CANCELLED,
				update_modified=False,
			)
		return {"survey_order": existing, "tanks": []}
	if not booking.survey_date:
		return {"survey_order": existing, "tanks": []}

	containers = [
		r.container for r in frappe.get_all(
			"Container Booking Item",
			filters={"parent": booking.name, "parenttype": "Container Booking"},
			fields=["container"],
		) if r.container
	]

	try:
		doc = frappe.get_doc(SCHEDULE, existing) if existing else frappe.new_doc(SCHEDULE)
		doc.booking = booking.name
		doc.survey_date = getdate(booking.survey_date)
		doc.plan_date = booking.plan_date
		doc.principal = booking.principal
		doc.surveyor = booking.surveyor
		doc.branch = booking.branch
		doc.depot = booking.depot
		if not existing:
			doc.status = "Scheduled"

		listed = {r.container for r in (doc.tanks or [])}
		added = []
		for container in containers:
			if container in listed:
				continue
			doc.append("tanks", {
				"container": container,
				"status": WAITING,
				# Every tank starts stacked as far as this document is concerned — the honest
				# default even for one already on the ground, because nobody has yet said so.
				"depot": frappe.db.get_value("Container", container, "depot") or booking.depot,
				"target_lift_on": booking.plan_date,
			})
			added.append(container)

		# A submitted schedule (every tank finished) cannot take a plain save; nothing about a
		# re-saved booking should reopen a finished day, so the header sync is dropped rather
		# than forced through. Rows for genuinely new containers still have to land, and they
		# do on the next reopen — a finished day that gains a tank is a corrected booking, and
		# ``refresh_progress`` reopens it from the row that is not done.
		if doc.docstatus == 1 and not added:
			return {"survey_order": doc.name, "tanks": []}
		if doc.docstatus == 1:
			frappe.db.set_value(SCHEDULE, doc.name, "docstatus", 0, update_modified=False)
			doc.reload()
			for container in added:
				doc.append("tanks", {
					"container": container, "status": WAITING,
					"depot": frappe.db.get_value("Container", container, "depot") or booking.depot,
					"target_lift_on": booking.plan_date,
				})

		is_new = doc.is_new()
		doc.save(ignore_permissions=True)  # system automation on booking save
		refresh_progress(doc.name)
		if is_new:
			notify_survey_order_scheduled(doc)
		return {"survey_order": doc.name, "tanks": added}
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"provision survey order for {booking_name}")
		return {"survey_order": existing, "tanks": []}


# ---------------------------------------------------------------------------
# The calendar — Jadwal Survey
# ---------------------------------------------------------------------------
def survey_calendar(month: str | None = None) -> dict:
	"""Per-day survey counts for one month, for the PWA calendar's dots.

	``month`` is any date inside the wanted month (``YYYY-MM-DD``); defaults to today. Returns
	``{"month", "from_date", "to_date", "days": {date: {orders, tanks, done}}}`` — one entry per
	day that actually has something on it, so the client paints a dot only where there is work.

	Counted off the TANK ROWS rather than the schedules: a day's weight to a surveyor is how
	many tanks they have to walk to, not how many bookings those tanks came in on.
	"""
	anchor = getdate(month or today())
	start, end = get_first_day(anchor), get_last_day(anchor)
	orders = frappe.get_all(
		SCHEDULE,
		filters=_depot_filter({
			"survey_date": ["between", [start, end]],
			"status": ["!=", CANCELLED],
		}),
		fields=["name", "survey_date"],
		limit_page_length=0,
	)
	if not orders:
		return {"month": str(start), "from_date": str(start), "to_date": str(end), "days": {}}

	by_order = {o.name: o.survey_date for o in orders}
	rows = frappe.get_all(
		ROW,
		filters={"parent": ["in", list(by_order)], "parenttype": SCHEDULE, "status": ["!=", CANCELLED]},
		fields=["parent", "status"],
		limit_page_length=0,
	)
	days: dict = {}
	for r in rows:
		day = days.setdefault(str(by_order[r.parent]), {"orders": set(), "tanks": 0, "done": 0})
		day["orders"].add(r.parent)
		day["tanks"] += 1
		if r.status == DONE:
			day["done"] += 1
	return {
		"month": str(start),
		"from_date": str(start),
		"to_date": str(end),
		"days": {d: {**v, "orders": len(v["orders"])} for d, v in days.items()},
	}


def list_survey_orders(date: str | None = None, start=0, page_length=20) -> dict:
	"""The survey schedules on one day — the calendar's day list.

	Ordered by principal so the cards group the way the yard reads them (one principal's tanks
	are collected together), then by creation for a stable tie-break.
	"""
	day = getdate(date or today())
	filters = _depot_filter({"survey_date": day, "status": ["!=", CANCELLED]})
	items = frappe.get_all(
		SCHEDULE,
		filters=filters,
		fields=[
			"name", "booking", "principal", "surveyor", "status", "survey_date", "plan_date",
			"depot", "branch", "tank_count", "lowered_count", "survey_done_count",
			"per_surveyed", "container_summary",
		],
		order_by="principal asc, creation asc",
		limit_start=cint(start),
		limit_page_length=cint(page_length),
	)
	for it in items:
		# What the card shows as the amber number: tanks nobody has dropped yet.
		it["waiting_count"] = max((it.get("tank_count") or 0) - (it.get("lowered_count") or 0), 0)
		it["survey_date"] = str(it["survey_date"]) if it.get("survey_date") else None
		it["plan_date"] = str(it["plan_date"]) if it.get("plan_date") else None
	return {"items": items, "total": frappe.db.count(SCHEDULE, filters), "date": str(day)}


SCHEDULE_STATUSES = (SCHEDULED, IN_PROGRESS, COMPLETED, CANCELLED)


def list_all_survey_orders(status=None, from_date=None, to_date=None, search=None,
						   start=0, page_length=20) -> dict:
	"""Every Survey Order, filterable — the standalone Jadwal Survey list.

	Separate from :func:`list_survey_orders` (which answers "what is on THIS day" for the
	calendar) because the two questions are not the same one narrowed. A surveyor uses the
	calendar to plan a day and this list to FIND a schedule — "that Pertamina job last week",
	"everything still open" — and a month grid cannot answer either of those.

	Cancelled and completed schedules are included on purpose. Hiding them would make this a
	worklist wearing a list's clothes, and the first thing anyone asks a list is what happened
	to something that is no longer open.

	Search covers the schedule's own identifiers AND its tank numbers. The tank numbers matter
	most and are the one thing ``container_summary`` cannot be trusted for: it truncates with a
	``(+N)`` marker on a long booking, so the 12th tank of a 20-tank day would be unfindable.
	Hence the child-table pass.
	"""
	filters = _depot_filter({})
	if status and status in SCHEDULE_STATUSES:
		filters["status"] = status
	if from_date:
		filters["survey_date"] = [">=", str(getdate(from_date))]
	if to_date:
		# Two bounds on one field cannot both live in a dict, so a range becomes `between`.
		filters["survey_date"] = (
			["between", [str(getdate(from_date)), str(getdate(to_date))]]
			if from_date else ["<=", str(getdate(to_date))]
		)

	or_filters = None
	search = (search or "").strip()
	if search and search.lower() not in ("undefined", "null", "none"):
		like = f"%{search}%"
		or_filters = [
			[SCHEDULE, "name", "like", like],
			[SCHEDULE, "principal", "like", like],
			[SCHEDULE, "booking", "like", like],
		]
		parents = frappe.get_all(
			ROW,
			filters={"parenttype": SCHEDULE, "container_no": ["like", like]},
			pluck="parent",
			limit_page_length=0,
		)
		if parents:
			# The list form of or_filters, not the dict form, precisely so `name` can carry
			# two alternatives at once.
			or_filters.append([SCHEDULE, "name", "in", list(set(parents))])

	items = frappe.get_all(
		SCHEDULE,
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name", "booking", "principal", "surveyor", "status", "survey_date", "plan_date",
			"depot", "branch", "tank_count", "lowered_count", "survey_done_count",
			"per_surveyed", "container_summary", "docstatus",
		],
		# Newest day first: a list is browsed backwards from now, unlike the calendar which is
		# read forwards from a date the user picked.
		order_by="survey_date desc, creation desc",
		limit_start=cint(start),
		limit_page_length=cint(page_length),
	)
	for it in items:
		it["waiting_count"] = max((it.get("tank_count") or 0) - (it.get("lowered_count") or 0), 0)
		for k in ("survey_date", "plan_date"):
			it[k] = str(it[k]) if it.get(k) else None

	# `frappe.db.count` takes no or_filters, and faking the total from the page size breaks the
	# "Muat lagi" button precisely when it is needed: a full page would report total == loaded
	# and the button would vanish with results still unseen. A search does its own count.
	if or_filters:
		total = len(frappe.get_all(
			SCHEDULE, filters=filters, or_filters=or_filters, pluck="name", limit_page_length=0
		))
	else:
		total = frappe.db.count(SCHEDULE, filters)

	return {"items": items, "total": total, "counts": _status_counts()}


def _status_counts() -> dict:
	"""How many schedules sit in each status, for the filter chips.

	Unfiltered by date and by search on purpose: the chips are how the user CHANGES the
	filter, so counting them through the current filter would make them all read 0 the moment
	a search narrowed things — the one moment they are most needed.
	"""
	# One column, tallied in Python: `frappe.get_all` refuses a `count(...)` string in SELECT,
	# and a schedule table is small enough that a raw-SQL detour would buy nothing.
	rows = frappe.get_all(
		SCHEDULE, filters=_depot_filter({}), fields=["status"], limit_page_length=0
	)
	counts: dict = {}
	for r in rows:
		if r.status:
			counts[r.status] = counts.get(r.status, 0) + 1
	return counts


def get_survey_order_detail(name: str) -> dict:
	"""One schedule's header + every tank on it, each with its LIVE location from the master.

	Waiting-lowering tanks first: they are what is still blocking the day, and a surveyor
	opening this screen is looking for what is left, not for what is finished.
	"""
	doc = frappe.get_doc(SCHEDULE, name)
	assert_in_user_branch(depot=doc.depot)
	tanks = _attach_positions([
		{
			"name": r.name, "container": r.container, "container_no": r.container_no,
			"status": r.status, "depot": r.depot, "target_lift_on": r.target_lift_on,
			"lowered_by": r.lowered_by, "lowered_on": r.lowered_on,
			"surveyed_by": r.surveyed_by, "surveyed_on": r.surveyed_on,
			"reopen_note": r.reopen_note, "eir_out": r.eir_out, "idx": r.idx,
		}
		for r in (doc.tanks or [])
	])
	rank = {WAITING: 0, LOWERED: 1, DONE: 2, CANCELLED: 3}
	tanks.sort(key=lambda r: (rank.get(r.get("status"), 9), r.get("idx") or 0))
	return {
		"name": doc.name,
		"booking": doc.booking,
		"principal": doc.principal,
		"surveyor": doc.surveyor,
		"status": doc.status,
		"docstatus": doc.docstatus,
		"survey_date": str(doc.survey_date) if doc.survey_date else None,
		"plan_date": str(doc.plan_date) if doc.plan_date else None,
		"depot": doc.depot,
		"branch": doc.branch,
		"tank_count": doc.tank_count,
		"lowered_count": doc.lowered_count,
		"survey_done_count": doc.survey_done_count,
		"waiting_count": max((doc.tank_count or 0) - (doc.lowered_count or 0), 0),
		"per_surveyed": doc.per_surveyed,
		"tanks": tanks,
	}


# ---------------------------------------------------------------------------
# Worklists — the flat queues, one per step
# ---------------------------------------------------------------------------
def _list_rows(status, start=0, page_length=20, search=None) -> dict:
	"""Tank rows in one status across every open schedule, depot-scoped, searchable, paginated.

	Ordered by the customer's pickup date (``worklist.sort_by_priority``): a wash finished a day
	late on a tank nobody is coming for costs nothing, the same day lost on a tank on a truck's
	schedule costs a truck.
	"""
	filters = _depot_filter({"status": status, "parenttype": SCHEDULE})
	or_filters = None
	search = (search or "").strip()
	if search and search.lower() not in ("undefined", "null", "none"):
		or_filters = {"container_no": ["like", f"%{search}%"], "parent": ["like", f"%{search}%"]}
	rows = frappe.get_all(
		ROW,
		filters=filters,
		or_filters=or_filters,
		fields=["name", "parent", "container", "container_no", "status", "depot",
				"target_lift_on", "lowered_by", "lowered_on", "reopen_note", "creation"],
		# Whole list, then sort, then slice: the priority order is decided in Python, so SQL
		# cannot page it. Bounded by the tanks actually standing in the yard.
		order_by="creation asc",
		limit_page_length=0,
	)
	# A row whose schedule was cancelled is not work, even if the row itself was missed.
	live = set(frappe.get_all(
		SCHEDULE,
		filters={"name": ["in", list({r.parent for r in rows}) or [""]], "status": ["!=", CANCELLED]},
		pluck="name",
	))
	rows = [r for r in rows if r.parent in live]
	total = len(rows)
	rows = sort_by_priority(rows, lambda r: False, start, page_length)
	return {"items": _attach_positions(rows), "total": total}


def list_waiting_lowering(start=0, page_length=20, search=None) -> dict:
	"""Operator Kalmar worklist — tanks still stacked, nearest lift-on first."""
	return _list_rows(WAITING, start=start, page_length=page_length, search=search)


def list_ready_to_survey(start=0, page_length=20, search=None) -> dict:
	"""Surveyor worklist — tanks already on the ground, waiting for the survey to be closed.

	The flat companion to the calendar: a surveyor mid-round wants "what can I do right now"
	across every schedule, not one day's card at a time.
	"""
	return _list_rows(LOWERED, start=start, page_length=page_length, search=search)


def list_survey_history(start=0, page_length=10, search=None) -> dict:
	"""Finished tanks (Survey Done / Cancelled) — the PWA "Riwayat" feed, newest first."""
	filters = _depot_filter({"status": ["in", [DONE, CANCELLED]], "parenttype": SCHEDULE})
	or_filters = None
	search = (search or "").strip()
	if search and search.lower() not in ("undefined", "null", "none"):
		or_filters = {"container_no": ["like", f"%{search}%"], "parent": ["like", f"%{search}%"]}
	rows = frappe.get_all(
		ROW,
		filters=filters,
		or_filters=or_filters,
		fields=["name", "parent", "container", "container_no", "status", "depot",
				"target_lift_on", "lowered_by", "lowered_on", "surveyed_by", "surveyed_on",
				"survey_notes", "eir_out", "reopen_note", "creation"],
		order_by="surveyed_on desc, creation desc",
		limit_start=cint(start),
		limit_page_length=cint(page_length),
	)
	return {"items": _attach_positions(rows), "total": frappe.db.count(ROW, filters)}


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------
def get_tank_detail(name: str) -> dict:
	"""One tank row: its two steps, its schedule, and its live location + how old that is."""
	row = frappe.db.get_value(
		ROW, name,
		["name", "parent", "container", "container_no", "status", "depot", "target_lift_on",
		 "lowered_by", "lowered_on", "lowering_note", "surveyed_by", "surveyed_on",
		 "survey_notes", "eir_out", "reopen_note"],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Tank {0} tidak ada di jadwal survey manapun.").format(name))
	assert_in_user_branch(depot=row.depot or frappe.db.get_value("Container", row.container, "depot"))

	out = _attach_positions([dict(row)])[0]
	out["survey_order"] = row.parent
	out["schedule"] = frappe.db.get_value(
		SCHEDULE, row.parent,
		["name", "booking", "principal", "surveyor", "survey_date", "plan_date", "status"],
		as_dict=True,
	)
	if out["schedule"]:
		for k in ("survey_date", "plan_date"):
			out["schedule"][k] = str(out["schedule"][k]) if out["schedule"][k] else None
	# The readings behind the current position, so the operator can see whether the tank has
	# been reported in three different blocks this morning.
	out["position_history"] = frappe.get_all(
		"Container Position",
		filters={"container": row.container},
		fields=["name", "location_note", "recorded_by", "recorded_on"],
		order_by="recorded_on desc, creation desc",
		limit_page_length=3,
	)
	for h in out["position_history"]:
		h["recorded_on"] = str(h["recorded_on"]) if h["recorded_on"] else None
	# With their photos: a surveyor deciding which stack to walk to is the reader who most
	# needs the picture, and this is the same history the Letak Tank screen shows.
	_attach_photos(out["position_history"])
	return out


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
def _open_row(name, statuses, ptype):
	"""Load a tank row, check the branch, the permission and the status.

	In that order, and it matters: someone outside the branch is told so rather than being
	handed a status message about a tank they should not be able to see.

	The permission is checked BY HAND because every write below goes through
	``frappe.db.set_value`` on a child row rather than through the parent's ``save()`` — child
	rows carry no DocPerm of their own, and a raw write checks nothing at all. ``write`` is the
	lowering, ``submit`` is the closing; that split over this one doctype is what separates the
	two PWA menus (``ess.context._MENU``).
	"""
	row = frappe.db.get_value(
		ROW, name,
		["name", "parent", "container", "container_no", "status", "depot",
		 "lowered_by", "lowered_on", "surveyed_by", "surveyed_on", "eir_out"],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Tank {0} tidak ada di jadwal survey manapun.").format(name))
	assert_in_user_branch(depot=row.depot or frappe.db.get_value("Container", row.container, "depot"))
	if not frappe.has_permission(SCHEDULE, ptype):
		raise frappe.PermissionError(
			_("Tidak boleh {0} Survey Order.").format(ptype)
		)
	if row.status not in statuses:
		frappe.throw(_("Tank {0} statusnya {1}, bukan {2}.").format(
			row.container_no or name, row.status, " / ".join(statuses)
		))
	return row


def _write(name, values, parent):
	"""Apply a row change and re-derive the schedule around it."""
	frappe.db.set_value(ROW, name, values, update_modified=False)
	refresh_progress(parent)


def mark_lowered(name, location_note=None, note=None, photos=None) -> dict:
	"""Tandai Lowered: the tank is on the ground (→ ``Lowered``).

	``location_note`` is optional and, when given, is filed as a fresh ``Container Position``
	reading rather than stored on this row — one channel for positions, so the master and its
	timestamp stay the single answer to "where is it". The person who just put the tank down is
	the one who knows, which is why the press offers it at all.

	It becomes REQUIRED for a tank nobody has ever located. "Sudah turun" on its own leaves the
	surveyor with nowhere to walk, and a tank that has just been moved by definition has a new
	position to record.

	Open to both field menus: normally the Kalmar operator on the reachstacker, but a surveyor
	already standing at a tank that is plainly on the ground should not have to wait for
	somebody else before the day can start.

	Pressing it on a tank already lowered is a no-op rather than an error — a retried request
	from a bad signal spot must not read as a failure — but a location given with it is still
	recorded, because a correction is exactly why somebody would press twice.
	"""
	from container_depot.container_depot.container_position import record_position

	row = _open_row(name, (WAITING, LOWERED), "write")
	location_note = (str(location_note).strip() if location_note is not None else "")
	if not location_note and not frappe.db.get_value("Container", row.container, "current_location"):
		frappe.throw(_("Tank ini belum pernah didata letaknya — isi letaknya sekalian."))
	if location_note:
		record_position(row.container, location_note, notes=note, photos=photos)

	if row.status == WAITING:
		_write(name, {
			"status": LOWERED,
			"lowered_by": frappe.session.user,
			"lowered_on": now_datetime(),
			"lowering_note": note,
			# The redo asked for is done; the reason it was sent back stops being news.
			"reopen_note": None,
		}, row.parent)
	notify_position_lowered(_notify_payload(name))

	return {"success": True, "name": name, "status": LOWERED, "location_note": location_note or None}


def finish_survey(name, notes=None) -> dict:
	"""Selesai Survey: the surveyor closes this tank (→ ``Survey Done``).

	Notes are OPTIONAL, unlike the location one step earlier. This press records a judgement —
	"I have looked at this tank" — and demanding evidence for it would only teach the crew to
	type a full stop into the box.

	Closing is what raises the tank's EIR-Out (``eir.provision_eir_out_for_survey``). That draft
	is deliberately born WITHOUT a bon: the bon does not exist yet, and the EIR-Out cannot be
	submitted until it does (``Inspection.before_submit``). Best-effort, so an EIR hiccup never
	costs the surveyor the survey they just finished.
	"""
	if frappe.db.get_value(ROW, name, "status") == DONE:
		# Usually a queued request that left the handset after somebody else closed the same
		# tank. Said plainly, and marked so the offline queue can tell "this is done" from
		# "this is not ready yet".
		frappe.throw(_("Survey tank ini sudah selesai."), exc=AlreadySettled)
	row = _open_row(name, (LOWERED,), "submit")

	_write(name, {
		"status": DONE,
		"surveyed_by": frappe.session.user,
		"surveyed_on": now_datetime(),
		"survey_notes": notes,
		"reopen_note": None,
	}, row.parent)

	eir_out = None
	try:
		from container_depot.container_depot.eir import provision_eir_out_for_survey

		eir_out = provision_eir_out_for_survey(name)
		if eir_out:
			frappe.db.set_value(ROW, name, "eir_out", eir_out, update_modified=False)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"provision EIR-Out for survey tank {name}")
	notify_survey_done(_notify_payload(name), eir_out=eir_out)

	return {"success": True, "name": name, "status": DONE, "eir_out": eir_out}


def _notify_payload(name) -> dict:
	"""What the bell needs about a tank row: its number, its depot, and where it is.

	Read back from the database rather than passed along, so the subject always quotes the state
	the write actually left behind — including the position, which lives on the master and may
	have been written by the very same press.
	"""
	row = frappe.db.get_value(
		ROW, name, ["name", "parent", "container", "container_no", "depot"], as_dict=True
	) or frappe._dict()
	return {
		"name": row.get("name"),
		"survey_order": row.get("parent"),
		"container": row.get("container"),
		"container_no": row.get("container_no"),
		"depot": row.get("depot"),
		"location_note": frappe.db.get_value("Container", row.get("container"), "current_location"),
	}


def _reopen(name, target, sources, clear, note, subject, notifier) -> dict:
	"""Push a finished tank back to an earlier step, clearing the step being redone.

	Written once for both undos because the risky part is identical. ``clear`` names the stamps
	of the step being redone; nothing else is touched. Reopening the survey must not disturb the
	lowering, or the surveyor would be sending a reachstacker back out to re-drop a tank that is
	already on the ground.

	The position is never touched by either. It is not this document's to retract — the tank is
	standing where the last reading says it is, whatever anyone got wrong about the paperwork.
	"""
	from container_depot.container_depot.container_activity import log_doc_note

	row = frappe.db.get_value(
		ROW, name, ["name", "parent", "container", "container_no", "status", "depot", "eir_out"],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Tank {0} tidak ada di jadwal survey manapun.").format(name))
	assert_in_user_branch(depot=row.depot or frappe.db.get_value("Container", row.container, "depot"))
	if row.status == target:
		# Already back in the worklist. A retried request, not a mistake.
		return {"success": True, "name": name, "status": row.status}
	if row.status not in sources:
		# Reopening only ever undoes a step that was actually taken. Without this, "buka lagi
		# survey" on a tank nobody has lowered would drop it into the surveyor's queue.
		frappe.throw(_("Tank {0} statusnya {1} — belum ada yang bisa dibuka lagi.").format(
			row.container_no or name, row.status
		))

	note = (note or "").strip()
	line = _("{0} dibuka lagi oleh {1}").format(subject, frappe.session.user)
	if note:
		line += ": " + note

	_write(name, dict({"status": target, "reopen_note": line}, **clear), row.parent)
	# The row change leaves no Version row of its own, so the schedule's timeline is the only
	# trace the Desk would otherwise have of the reopen.
	log_doc_note(SCHEDULE, row.parent, f"{row.container_no or row.container}: {line}")
	_withdraw_eir_out(name, row.eir_out, line)
	notifier(_notify_payload(name), reopened=True)
	return {"success": True, "name": name, "status": target}


def _withdraw_eir_out(row_name, eir_out, why) -> None:
	"""Take back the EIR-Out a now-reopened survey raised.

	The EIR-Out exists because the survey said the tank had been checked. Reopening withdraws
	that statement, so the paperwork it authorised must not stay standing — an EIR-Out is what
	lets a tank through the gate (``gate.mark_gate_out``), and one left behind by a retracted
	survey is exactly the document nobody would think to look at twice.

	Only an UNTOUCHED draft is deleted. Once a surveyor has started filling it in the work is
	theirs, and it is left alone with a note on its timeline instead — the same rule
	``eir.release_eirs_for_cancelled_order`` applies to a cancelled bon. A submitted EIR-Out is
	never touched at all; by then the tank has been through the gate and history is history.
	"""
	from container_depot.container_depot.container_activity import log_doc_note

	if not eir_out:
		return
	frappe.db.set_value(ROW, row_name, "eir_out", None, update_modified=False)
	row = frappe.db.get_value(
		"Inspection", eir_out, ["name", "docstatus", "work_started_on", "referred_voucher"], as_dict=True
	)
	if not row or row.docstatus != 0:
		return
	try:
		if not row.work_started_on and not row.referred_voucher:
			frappe.delete_doc("Inspection", row.name, ignore_permissions=True)
		else:
			log_doc_note("Inspection", row.name, why)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"withdraw EIR-Out for survey tank {row_name}")


def reopen_lowering(name, note=None) -> dict:
	"""Send a tank all the way back (→ ``Waiting Lowering``): it was never really down.

	Reachable from both menus, and on purpose. The Kalmar operator finds their own mistake in
	Riwayat; the surveyor finds it standing at an empty bay, which is the case that actually
	happens.

	Both steps' stamps are cleared: a survey closed over a tank that was not down was closing
	over nothing, so it does not survive the lowering it was given for.
	"""
	_open_row(name, (LOWERED, DONE, WAITING), "write")
	return _reopen(
		name, WAITING, (LOWERED, DONE),
		{"lowered_by": None, "lowered_on": None, "surveyed_by": None, "surveyed_on": None},
		note, _("Lowering"), notify_waiting_lowering,
	)


def reopen_survey(name, note=None) -> dict:
	"""Send a closed tank back to the surveyor (→ ``Lowered``): it was closed too early.

	Only the closing is cleared. The lowering stamps stay exactly as they were — nobody has to
	move a reachstacker for a button somebody pressed early.
	"""
	_open_row(name, (DONE, LOWERED), "submit")
	return _reopen(
		name, LOWERED, (DONE,),
		{"surveyed_by": None, "surveyed_on": None},
		note, _("Survey"), notify_position_lowered,
	)
