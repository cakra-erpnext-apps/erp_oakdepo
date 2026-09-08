"""ESS PWA home-screen endpoint — the one GET behind the Beranda redesign.

Read-only, and deliberately *lean*: this runs on every app open, on a depot handset, so
it never loads a container list. Every number here is a ``COUNT`` (plus one row for the
oldest item in the queue), scoped to the caller's depots.

Two sections, and they answer two different questions:

* ``today``   — "what has the depot done since midnight, and what is still hanging off
  it" — the four tiles at the top of Beranda. Each pairs a headline count with the one
  sub-count that says whether the work behind it is finished.
* ``waiting`` — "what is waiting on ME" — one row per queue that has anything in it, with
  the age of its OLDEST item. Age is the whole point of the section: three cleaning orders
  raised a minute ago are not a problem, one raised at the start of the shift is.

Both sections are gated on ``allowed_menu()`` exactly like
:func:`container_depot.ess.inventory.get_dashboard_summary` — a section is present only
when the caller may open the page behind it, so Team Cleaning gets the cleaning queue and
none of the gate counts. Deriving the gate from the menu (rather than from a second role
table) is what keeps Beranda from drifting away from what the tiles can actually open.

Text lives in the front-end (``frontend/src/utils/labels.js``); this returns numbers and
keys only.
"""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime, time_diff_in_seconds, today

from container_depot.api import _require_authenticated_user
from container_depot.container_depot.container_status import DONE_CLEANING
from container_depot.container_depot.user_branch import get_user_depots

# Cleaning statuses that mean nobody has touched the tank yet. `Service Setup` is the
# state a freshly raised order sits in before its services are picked, so it counts as
# not-started just as much as `Pending` does.
CLEANING_NOT_STARTED = ("Service Setup", "Pending")

# At most this many rows in "Menunggu Anda". A supervisor holds every menu and would
# otherwise get a nine-row wall on the screen that exists to say what is urgent — and
# the rows are already sorted oldest-first, so the cut falls on the least urgent.
MAX_WAITING = 6


def _scoped(filters: dict, allowed) -> dict:
	"""Add the caller's depot scope to a filter dict. ``allowed`` is None = unrestricted."""
	if allowed is not None:
		filters = {**filters, "depot": ["in", allowed or [""]]}
	return filters


def _age_minutes(value) -> int | None:
	"""Whole minutes since ``value``, or None when there is no timestamp to measure."""
	if not value:
		return None
	return max(0, int(time_diff_in_seconds(now_datetime(), value) // 60))


def _queue(key: str, doctype: str, filters: dict, *, ref_field="container_no", time_field="creation"):
	"""One "Menunggu Anda" row, or None when the queue is empty.

	``ref`` is filled only when the queue holds exactly ONE item: naming the container is
	what turns "1 EIR menunggu review" into something an operator recognises, and naming
	one of five would be picking a favourite.
	"""
	count = frappe.db.count(doctype, filters)
	if not count:
		return None
	oldest = frappe.get_all(
		doctype,
		filters=filters,
		fields=[ref_field, time_field],
		order_by=f"{time_field} asc",
		limit=1,
	)
	row = oldest[0] if oldest else {}
	return {
		"key": key,
		"count": count,
		"ref": row.get(ref_field) if count == 1 else None,
		"age": _age_minutes(row.get(time_field)),
	}


def _active_booking_codes(allowed) -> list:
	"""Booking Codes that are cleared and still waiting for their truck at the barrier.

	``Active`` is the payment-cleared signal (``api.validate_qr``), so these are exactly
	the movements the gate is expecting today — and an expired one is not waiting for
	anybody, whether or not the expiry job has run yet.

	Raw SQL because Booking Code carries no ``depot`` of its own: the scope lives on its
	Container Booking, and one join is cheaper than pulling every booking name in the
	branch just to build an ``in`` list.
	"""
	where = ["bc.state = 'Active'", "(bc.expires_at is null or bc.expires_at >= now())"]
	args: dict = {}
	if allowed is not None:
		if not allowed:
			return []
		where.append("b.depot in %(depots)s")
		args["depots"] = allowed
	return frappe.db.sql(
		f"""
		select bc.container_no, bc.direction, bc.issued_at
		from `tabBooking Code` bc
		inner join `tabContainer Booking` b on b.name = bc.booking
		where {' and '.join(where)}
		order by bc.issued_at asc
		""",
		args,
		as_dict=True,
	)


@frappe.whitelist(methods=["GET"])
def get_home_summary():
	"""GET /api/v1/ess/home-summary — ``{success, menu, today, waiting}``.

	A caller with no field role gets ``{"success": True, "menu": []}`` and nothing else:
	the PWA is open to them, it is simply empty, and Beranda already has a card that says
	why.
	"""
	from container_depot.ess.context import allowed_menu

	_require_authenticated_user()
	menu = set(allowed_menu())
	if not menu:
		return {"success": True, "menu": []}

	from container_depot.container_depot import container_position, eir, tank_survey

	allowed = get_user_depots()  # None = unrestricted; [] = no depot at all
	out = {"success": True, "menu": sorted(menu), "today": {}, "waiting": []}
	today_counts = out["today"]
	waiting = out["waiting"]

	# --- Gate: what came in and went out since midnight -----------------------------
	# Read from the Container Activity log rather than from the gate documents, same as
	# the Desk dashboard: it is the one table that records a movement per tank whichever
	# door it came through.
	if "gate" in menu:
		act = _scoped({"activity_time": [">=", today()]}, allowed)
		today_counts["gate_in"] = frappe.db.count(
			"Container Activity", {**act, "activity_type": "Gate In"}
		)
		today_counts["gate_out"] = frappe.db.count(
			"Container Activity", {**act, "activity_type": "Gate Out"}
		)
		codes = _active_booking_codes(allowed)
		# Sub-count under "Tank keluar": bookings cleared to leave whose truck has not
		# arrived. The full list (both directions) is the gate's own queue row below.
		today_counts["booking_out"] = sum(1 for c in codes if c.direction == "Tank Out")
		if codes:
			waiting.append({
				"key": "bookingGate",
				"count": len(codes),
				"ref": codes[0].container_no if len(codes) == 1 else None,
				"age": _age_minutes(codes[0].issued_at),
			})

	# --- EIR: drafts to work, and the ones already done waiting on Admin Ops ---------
	if "eir" in menu:
		eir_open = _scoped(
			{"docstatus": 0, "inspection_type": "EIR-In", "status": ["!=", "Pending Review"]},
			allowed,
		)
		eir_review = _scoped(
			{"docstatus": 0, "inspection_type": "EIR-In", "status": "Pending Review"}, allowed
		)
		# "Belum EIR" under "Tank masuk": every tank that came in still owes one, and this
		# is the same list the EIR worklist opens on (``eir.list_pending_eirs``).
		today_counts["eir_open"] = frappe.db.count("Inspection", eir_open)
		today_counts["eir_review"] = frappe.db.count("Inspection", eir_review)
		review_oldest = frappe.get_all(
			"Inspection", filters=eir_review, fields=["creation"], order_by="creation asc", limit=1
		)
		today_counts["eir_review_age"] = _age_minutes(review_oldest[0].creation) if review_oldest else None
		for row in (
			_queue("eirReview", "Inspection", eir_review),
			_queue("eirOpen", "Inspection", eir_open),
		):
			if row:
				waiting.append(row)
		# EIR-Out rides on the worklist rather than on a filter of our own: which tanks owe
		# an out-inspection is a question about their booking, not about the Inspection
		# table, and that answer lives in one place (``eir.list_pending_eir_out``).
		eir_out = eir.list_pending_eir_out(page_length=1)["total"]
		if eir_out:
			waiting.append({"key": "eirOut", "count": eir_out, "ref": None, "age": None})

	# --- Cleaning: open orders, and how many nobody has started ---------------------
	if "cleaning" in menu:
		clean_open = _scoped(
			{"status": ["not in", DONE_CLEANING], "docstatus": ["<", 2]}, allowed
		)
		clean_idle = _scoped(
			{"status": ["in", CLEANING_NOT_STARTED], "docstatus": ["<", 2]}, allowed
		)
		today_counts["cleaning_open"] = frappe.db.count("Cleaning Order", clean_open)
		today_counts["cleaning_idle"] = frappe.db.count("Cleaning Order", clean_idle)
		row = _queue("cleaningIdle", "Cleaning Order", clean_idle)
		if row:
			waiting.append(row)

	# --- M&R: the queue that is waiting on a human decision, not on a wrench ---------
	if "mr" in menu:
		row = _queue(
			"mrApproval", "Repair Order", _scoped({"status": "Pending Approval"}, allowed)
		)
		if row:
			waiting.append(row)

	# --- Survey family + Letak Tank -------------------------------------------------
	# Counts only: each of these worklists decides its own scope and ordering (a tank is
	# "waiting to be lowered" because of its Survey Order's day, not because of a status
	# on a row), so the totals come from the worklists themselves.
	if "posFix" in menu:
		total = tank_survey.list_waiting_lowering(page_length=1)["total"]
		if total:
			waiting.append({"key": "lowering", "count": total, "ref": None, "age": None})
	if "surveyPos" in menu:
		total = tank_survey.list_ready_to_survey(page_length=1)["total"]
		if total:
			waiting.append({"key": "surveyReady", "count": total, "ref": None, "age": None})
	if "tankPos" in menu:
		total = container_position.search_containers(page_length=1, only_unlocated=1)["total"]
		if total:
			waiting.append({"key": "unlocated", "count": total, "ref": None, "age": None})

	# Oldest first — the section answers "what has been waiting longest", so a queue with
	# no age at all (the survey worklists, which are dated rather than aged) sorts under
	# the timed ones rather than above them.
	waiting.sort(key=lambda r: (r["age"] is None, -(r["age"] or 0), -r["count"]))
	del waiting[MAX_WAITING:]
	return out
