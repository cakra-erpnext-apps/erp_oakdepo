"""Where each tank stands — recording it, reading it back, and finding the ones nobody knows.

Deliberately free of ``@frappe.whitelist`` so the exact same functions back both the ESS PWA
wrappers (``ess/container_position.py``) and any Desk / automation caller.

THE SHAPE OF THIS FEATURE
-------------------------
A tank's position is a fact about the TANK, not about a booking. It changes because a
reachstacker moved it, and the next person who needs it may be a surveyor, a washer, a
mechanic or the gate. So it is recorded on its own, by anyone, at any time::

    Container Position (one reading)  ->  Container.current_location
                                          Container.location_updated_on
                                          Container.location_updated_by

Everything else READS the master — the Survey Order screen above all, which shows each tank's
last known place next to when it was last checked. Nothing copies the location into its own
document, because a copy is frozen at the moment it was taken and starts lying on the first
correction.

The age travels with the answer everywhere, and that is not decoration. "Blok kanan, dicatat
2 jam lalu" is an instruction; "blok kanan, dicatat bulan Juni" is a guess. A screen that
shows only the place cannot tell an operator which one they are holding.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, now_datetime, time_diff_in_seconds

from container_depot.container_depot.user_branch import assert_in_user_branch, get_user_depots

DOCTYPE = "Container Position"

# How long a reading stays "fresh" on the screens, in hours. Not a rule the server enforces —
# nothing is refused for being stale — just the line the UI draws between an answer to act on
# and one to double-check. A shift is 8 hours; a position that survived a whole shift without
# anybody contradicting it is still the best thing anyone knows.
FRESH_HOURS = 12


def _coerce_photos(photos) -> list:
	"""Normalise the ``photos`` payload (JSON string or list of urls / {photo}) → url list."""
	if photos is None:
		return []
	if isinstance(photos, str):
		try:
			photos = json.loads(photos)
		except json.JSONDecodeError:
			frappe.throw(_("photos must be a JSON array."))
	if not isinstance(photos, list):
		frappe.throw(_("photos must be a list."))
	out = []
	for p in photos:
		url = (p.get("photo") if isinstance(p, dict) else p) or ""
		url = str(url).strip()
		if url:
			out.append(url)
	return out


def _attach_photos(rows) -> list:
	"""Hang each reading's photos off it, in ONE query for the whole page.

	Photos are the half of a position that cannot be argued with. "Blok kanan tumpukan 2" is
	somebody's description; the picture is what the next person matches against the stack in
	front of them, and it is what settles a tank reported in two places on the same morning.
	So every read that returns readings returns their pictures — a history of bare sentences
	makes the operator open each row to find out whether there is anything to look at.

	Row-by-row lookups are what make a long history feel slow on a handset, hence the single
	``in`` query and the grouping here.
	"""
	names = [r.get("name") for r in rows if r.get("name")]
	by_parent: dict = {}
	if names:
		for ph in frappe.get_all(
			"Container Position Photo",
			filters={"parent": ["in", names], "parenttype": DOCTYPE},
			fields=["parent", "photo"],
			order_by="idx asc",
		):
			if ph.photo:
				by_parent.setdefault(ph.parent, []).append(ph.photo)
	for r in rows:
		r["photos"] = by_parent.get(r.get("name"), [])
	return rows


def _guard_container_branch(container) -> None:
	"""Block reads/writes on a tank whose depot is outside the caller's branch."""
	assert_in_user_branch(depot=frappe.db.get_value("Container", container, "depot"))


def _age(recorded_on) -> dict:
	"""``{"hours": float|None, "fresh": bool}`` for a reading's timestamp.

	Returned rather than formatted: the phrasing ("2 jam lalu", "Sejak 09:12") is the
	screen's business, and two screens already want it two different ways.
	"""
	if not recorded_on:
		return {"hours": None, "fresh": False}
	hours = time_diff_in_seconds(now_datetime(), recorded_on) / 3600.0
	return {"hours": round(hours, 2), "fresh": hours <= FRESH_HOURS}


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------
def record_position(container, location_note, notes=None, photos=None) -> dict:
	"""File one reading of where ``container`` is standing, and push it onto the master.

	Always an INSERT, never an update of the last one. A correction typed ten minutes later is
	a second reading, not a redaction of the first — the yard has to be able to see that a tank
	was reported in two places and when the story changed. The master keeps only the newest
	(``ContainerPosition.push_to_container``).

	Permissions are enforced (no bypass): every field role holds create on this doctype, which
	is the whole point — a wrong position costs whoever walks to the wrong stack next,
	whichever crew they are on.
	"""
	if not container:
		frappe.throw(_("Container wajib diisi."))
	_guard_container_branch(container)
	location_note = (str(location_note).strip() if location_note is not None else "")
	if not location_note:
		frappe.throw(_("Isi dulu letak container-nya."))

	doc = frappe.new_doc(DOCTYPE)
	doc.container = container
	doc.location_note = location_note
	doc.notes = notes
	doc.set("position_photos", [{"photo": url} for url in _coerce_photos(photos)])
	doc.insert()  # NOT ignore_permissions — DocPerm is the gate.

	return {
		"success": True,
		"name": doc.name,
		"container": container,
		"location_note": location_note,
		"recorded_on": str(doc.recorded_on),
		"recorded_by": doc.recorded_by,
		# Echoed back so a caller that is not about to re-fetch still knows what landed —
		# and so a `local:` ref that `send` swapped for a real URL is visibly resolved.
		"photos": [row.photo for row in doc.position_photos if row.photo],
	}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def get_container_position(container, history_length=5) -> dict:
	"""One tank's current location, how old it is, and the last few readings behind it.

	The history is what makes the current answer checkable: a tank reported in three different
	blocks this morning is a tank nobody has actually found, and no single "current location"
	can say that.
	"""
	if not container:
		frappe.throw(_("Container wajib diisi."))
	_guard_container_branch(container)
	tank = frappe.db.get_value(
		"Container", container,
		["name", "container_no", "depot", "status", "principal", "container_type",
		 "current_location", "location_updated_on", "location_updated_by", "target_lift_on",
		 "target_survey_on"],
		as_dict=True,
	)
	if not tank:
		frappe.throw(_("Container {0} tidak ditemukan.").format(container))

	history = frappe.get_all(
		DOCTYPE,
		filters={"container": container},
		fields=["name", "location_note", "notes", "recorded_by", "recorded_on"],
		order_by="recorded_on desc, creation desc",
		limit_page_length=cint(history_length),
	)
	for h in history:
		h["recorded_on"] = str(h["recorded_on"]) if h["recorded_on"] else None
	_attach_photos(history)

	return {
		"container": tank.name,
		"container_no": tank.container_no,
		"depot": tank.depot,
		"principal": tank.principal,
		"container_type": tank.container_type,
		"status": tank.status,
		"target_lift_on": str(tank.target_lift_on) if tank.target_lift_on else None,
		"target_survey_on": str(tank.target_survey_on) if tank.target_survey_on else None,
		"location_note": tank.current_location,
		"location_updated_on": str(tank.location_updated_on) if tank.location_updated_on else None,
		"location_updated_by": tank.location_updated_by,
		# Never recorded at all is a different state from "recorded a long time ago", and the
		# screen says so differently ("Lokasi belum terdata" vs a stale badge).
		"located": bool(tank.current_location),
		**_age(tank.location_updated_on),
		"history": history,
	}


# ---------------------------------------------------------------------------
# The queue — tanks whose place has to be known before their survey day
# ---------------------------------------------------------------------------
def needs_position(container) -> bool:
	"""Does this tank still owe an answer about where it is?

	True when nobody has ever recorded it, or when the last reading is OLDER THAN the booking
	that scheduled it. The second half is the whole point: a place written down in June is not
	a wrong answer, it is an answer to a question nobody was asking then — the tank has been
	moved by three reachstackers since, and the survey crew arriving on the day would be
	walking to a memory. Once anybody files a fresh reading the tank leaves the queue by
	itself, which is why the queue needs no document to close.
	"""
	tank = frappe.db.get_value(
		"Container", container,
		["current_location", "location_updated_on", "lift_on_booking"],
		as_dict=True,
	)
	if not tank or not tank.current_location:
		return True
	if not tank.lift_on_booking:
		return False
	since = frappe.db.get_value("Container Booking", tank.lift_on_booking, "creation")
	return bool(since and tank.location_updated_on and tank.location_updated_on < since)


def open_position_orders(start=0, page_length=20) -> dict:
	"""The "cek letak tank" queue: tanks with a survey coming whose place is unknown or stale.

	Derived, not stored — see ``tank_survey._raise_position_orders`` for why there is no order
	document behind this. A tank qualifies when a live outbound booking has stamped a deadline
	on it (``lift_on_booking``) and :func:`needs_position` still says yes; filing one reading
	is what closes it.

	Ordered by the same rule as every other worklist (``worklist.priority_date``): survey day
	first, pickup day when no survey has been set. Branch-scoped like everything else here.
	"""
	from container_depot.container_depot.worklist import sort_by_priority

	filters = {"is_active": 1, "lift_on_booking": ["is", "set"]}
	depots = get_user_depots()
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]

	rows = frappe.get_all(
		"Container",
		filters=filters,
		fields=["name", "container_no", "principal", "depot", "status", "target_lift_on",
				"target_survey_on", "current_location", "location_updated_on",
				"location_updated_by", "lift_on_booking"],
		order_by="container_no asc",
		limit_page_length=0,
	)
	rows = [r for r in rows if needs_position(r.name)]
	total = len(rows)
	# `started` is never true here: there is no half-done state — a tank either has a fresh
	# reading (and has left this list) or it does not.
	rows = sort_by_priority(rows, lambda r: False, cint(start), cint(page_length))
	for it in rows:
		it["located"] = bool(it.get("current_location"))
		for k in ("target_lift_on", "target_survey_on", "location_updated_on"):
			it[k] = str(it[k]) if it.get(k) else None
		it.update(_age(it.get("location_updated_on")))
	return {"items": rows, "total": total}


def search_containers(search=None, start=0, page_length=20, only_unlocated=0) -> dict:
	"""Tank finder: containers in the caller's branch, with their last known place.

	``search`` matches the container number (the only thing anyone standing in a yard has to
	hand). ``only_unlocated`` narrows to tanks nobody has ever recorded — the list to go and
	clear, and the reason the finder exists at all.

	Retired tanks are out: they are not in the yard to be found.

	ORDER — the tanks with a day against them come first, nearest day at the top. A yard has
	hundreds of tanks and only a handful are being waited for; those are the ones whose
	position somebody is about to walk on, so a list that opens on the stalest reading opens
	on the least urgent thing in the depot. The survey day wins over the pickup day, the same
	tie-break every other worklist uses (``worklist.priority_date``). Everything with no day
	at all keeps the old order underneath: never-recorded first, then stalest.

	Raw SQL because that ordering cannot be expressed through ``frappe.get_all`` — it refuses
	any function in ``order_by`` ("Invalid field format in Order By"), and ``target_survey_on
	asc`` alone would sort the NULLs (i.e. every tank nobody is waiting for) to the top, which
	is exactly backwards.
	"""
	where = ["c.is_active = 1"]
	args: dict = {}
	depots = get_user_depots()
	if depots is not None:  # restricted user: only their depots
		where.append("c.depot in %(depots)s")
		args["depots"] = tuple(depots or [""])
	if cint(only_unlocated):
		where.append("ifnull(c.current_location, '') = ''")
	search = (search or "").strip()
	if search and search.lower() not in ("undefined", "null", "none"):
		where.append("c.container_no like %(search)s")
		args["search"] = f"%{search}%"
	clause = " and ".join(where)

	# One expression, written once: the day this tank is wanted, or NULL when nobody is
	# waiting for it.
	due = "coalesce(c.target_survey_on, c.target_lift_on)"
	items = frappe.db.sql(
		f"""
		select c.name, c.container_no, c.principal, c.depot, c.status,
		       c.target_lift_on, c.target_survey_on, c.current_location,
		       c.location_updated_on, c.location_updated_by
		  from `tabContainer` c
		 where {clause}
		 order by ({due} is null) asc, {due} asc, c.location_updated_on asc, c.container_no asc
		 limit %(page_length)s offset %(start)s
		""",
		{**args, "page_length": cint(page_length), "start": cint(start)},
		as_dict=True,
	)
	total = frappe.db.sql(
		f"select count(*) from `tabContainer` c where {clause}", args
	)[0][0]
	for it in items:
		it["located"] = bool(it.get("current_location"))
		it["target_lift_on"] = str(it["target_lift_on"]) if it.get("target_lift_on") else None
		it["target_survey_on"] = str(it["target_survey_on"]) if it.get("target_survey_on") else None
		it.update(_age(it.get("location_updated_on")))
		it["location_updated_on"] = str(it["location_updated_on"]) if it.get("location_updated_on") else None
	return {"items": items, "total": total}


def list_position_history(container=None, start=0, page_length=20, search=None) -> dict:
	"""The readings feed — newest first, branch-scoped, optionally for one tank."""
	filters = {}
	depots = get_user_depots()
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]  # restricted user: only their depots
	if container:
		filters["container"] = container
	search = (search or "").strip()
	if search and search.lower() not in ("undefined", "null", "none"):
		filters["container_no"] = ["like", f"%{search}%"]

	items = frappe.get_all(
		DOCTYPE,
		filters=filters,
		fields=["name", "container", "container_no", "depot", "location_note", "notes",
				"recorded_by", "recorded_on"],
		order_by="recorded_on desc, creation desc",
		limit_start=cint(start),
		limit_page_length=cint(page_length),
	)
	for it in items:
		it["recorded_on"] = str(it["recorded_on"]) if it["recorded_on"] else None
	_attach_photos(items)
	return {"items": items, "total": frappe.db.count(DOCTYPE, filters)}
