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
		 "current_location", "location_updated_on", "location_updated_by", "target_lift_on"],
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
		"location_note": tank.current_location,
		"location_updated_on": str(tank.location_updated_on) if tank.location_updated_on else None,
		"location_updated_by": tank.location_updated_by,
		# Never recorded at all is a different state from "recorded a long time ago", and the
		# screen says so differently ("Lokasi belum terdata" vs a stale badge).
		"located": bool(tank.current_location),
		**_age(tank.location_updated_on),
		"history": history,
	}


def search_containers(search=None, start=0, page_length=20, only_unlocated=0) -> dict:
	"""Tank finder: containers in the caller's branch, with their last known place.

	``search`` matches the container number (the only thing anyone standing in a yard has to
	hand). ``only_unlocated`` narrows to tanks nobody has ever recorded — the list to go and
	clear, and the reason the finder exists at all.

	Retired tanks are out: they are not in the yard to be found.
	"""
	filters = {"is_active": 1}
	depots = get_user_depots()
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]  # restricted user: only their depots
	if cint(only_unlocated):
		filters["current_location"] = ["in", [None, ""]]
	search = (search or "").strip()
	if search and search.lower() not in ("undefined", "null", "none"):
		filters["container_no"] = ["like", f"%{search}%"]

	items = frappe.get_all(
		"Container",
		filters=filters,
		fields=["name", "container_no", "principal", "depot", "status", "target_lift_on",
				"current_location", "location_updated_on", "location_updated_by"],
		# Un-located tanks first, then the stalest — which is the order somebody clearing the
		# yard would walk it. Ties fall back to the number so the list does not shuffle.
		order_by="location_updated_on asc, container_no asc",
		limit_start=cint(start),
		limit_page_length=cint(page_length),
	)
	for it in items:
		it["located"] = bool(it.get("current_location"))
		it["target_lift_on"] = str(it["target_lift_on"]) if it.get("target_lift_on") else None
		it.update(_age(it.get("location_updated_on")))
		it["location_updated_on"] = str(it["location_updated_on"]) if it.get("location_updated_on") else None
	return {"items": items, "total": frappe.db.count("Container", filters)}


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
