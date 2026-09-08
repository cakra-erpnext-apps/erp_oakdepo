"""Prioritas lift-on: the outbound booking's date, pushed onto the tank and its open work.

A Container Booking (Tank Out / Lift On) says which tanks a customer is collecting and
when. That date is the only deadline the depot has: a wash finished a day late on a tank
nobody is coming for costs nothing, the same day lost on a tank on a truck's schedule costs
a truck. So the date is stamped onto the ``Container`` and mirrored onto every order still
holding it, and the worklists sort by it (``worklist.sort_by_priority``).

Stamped **from the draft**, deliberately. The booking is written days ahead precisely so the
yard can get the tank ready; waiting for Submit would hand the cleaning queue a deadline
only after the preparation time had already been spent. A draft that is voided releases its
stamps again (:func:`sync_booking_targets` reads the booking's own state, so cancelling is
just another sync).

Ported from the Gate Out Plan, which used to be a separate notice document sitting in front
of the booking. The two said the same thing about the same tanks, and the plan's only real
effect was this stamp — so it moved to the document that actually authorises the lift-on.
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate

from container_depot.container_depot.container_status import container_open_orders

# The Container's back-link: which booking owns the stamp it is carrying. Without it a
# second booking's release would clear a date the first one still needs.
CONTAINER_FIELD = "lift_on_booking"

# Direction that carries a lift-on at all. A Tank In is the tank ARRIVING; there is no
# pickup to prepare for.
OUTBOUND = "Tank Out"

# The two header dates a booking carries, and the order the depot works to.
#
# ``survey_date`` is when the tank is inspected on the ground; ``plan_date`` is when the truck
# comes for it. Preparation — cleaning, M&R, getting the tank down, the EIR-Out — has to be
# finished by the SURVEY, not by the pickup, so the survey date is the deadline every worklist
# sorts by (``worklist.sort_by_priority``). The pickup date stays stamped beside it because it
# is a different fact and the gate and the customer both ask about it; it is also the fallback
# for a booking whose survey day nobody has set yet.
#
# On the header, not per line: one booking is one job with one intended day, and the line
# carries the realisation (the day its bon came out) instead — a date that only exists once
# the preparation these deadlines drive is already over.
HEADER_DATE = "plan_date"
SURVEY_DATE = "survey_date"


# A booking that no longer expects anything to leave: cancelled either way — ``booking_status``
# (set by ``void_draft`` on a draft) or ``docstatus`` 2 — and COMPLETED, which means every tank
# on it has already gone through the gate. Completed matters as much as cancelled: the stamps
# were released tank by tank on the way out (``release_on_gate_out``), so anything that stamps
# from a completed booking hands a deadline back to a tank that is not in the yard any more —
# and the worklists, which now lead with the nearest day, would put it at the very top.
_DEAD_STATUS = ("Cancelled", "Completed")


def _booking_is_live(doc) -> bool:
	"""Does this booking still expect its tanks to leave?

	Everything that is neither cancelled nor completed does, including a plain draft: see the
	module docstring.
	"""
	return (
		doc.get("direction") == OUTBOUND
		and doc.get("booking_status") not in _DEAD_STATUS
		and int(doc.get("docstatus") or 0) != 2
	)


def sync_booking_targets(doc) -> None:
	"""Stamp / release ``target_lift_on`` for every container on one booking.

	Idempotent and total: it writes what the booking says right now and releases whatever
	used to point here and no longer does, so one call after any change to the booking is
	enough — a row deleted, a date moved, a direction flipped, the whole thing voided.
	"""
	listed = set()
	live = _booking_is_live(doc)
	date = doc.get(HEADER_DATE)
	survey = doc.get(SURVEY_DATE)
	for row in doc.get("items") or []:
		if not row.get("container"):
			continue
		listed.add(row.container)
		# Either date is enough to be worth stamping: a booking with only a survey day still
		# has a deadline, and one with only a pickup day still has the fallback.
		if live and (date or survey):
			set_target(row.container, date, survey, doc.name)
		else:
			clear_target(row.container, doc.name)
	for container in containers_pointing_to(doc.name):
		if container not in listed:
			clear_target(container, doc.name)


def set_target(container: str, date, survey, booking: str) -> None:
	d = getdate(date) if date else None
	sd = getdate(survey) if survey else None
	frappe.db.set_value(
		"Container", container,
		{"target_lift_on": d, "target_survey_on": sd, CONTAINER_FIELD: booking},
		update_modified=False,
	)
	push_to_open_orders(container, d, sd)


def clear_target(container: str, booking: str) -> None:
	"""Release the stamp only if this container still points at THIS booking — never
	clobber one another booking owns."""
	if frappe.db.get_value("Container", container, CONTAINER_FIELD) != booking:
		return
	frappe.db.set_value(
		"Container", container,
		{"target_lift_on": None, "target_survey_on": None, CONTAINER_FIELD: None},
		update_modified=False,
	)
	push_to_open_orders(container, None, None)


def push_to_open_orders(container: str, date, survey=None) -> None:
	"""Mirror the container's two dates onto every order still holding it, so the PWA + Desk
	worklists can sort and badge by them across pagination.

	New orders inherit it through ``fetch_from``; this keeps ALREADY-open ones in step when
	the booking changes or closes.

	Driven off :func:`container_open_orders` — the same list the booking's own readiness
	warning reads — rather than a private list of doctypes, so "belum selesai" means one
	thing across the app. Two questions, though, not one: that helper answers "what BLOCKS
	departure" and so leaves EIR-Out out on purpose, while the stamp answers "when is the
	customer coming" — which the outbound worklists want most of all. So the blockers come
	from the shared definition and the outbound pair is added to them here, rather than by
	loosening what "blocking" means for every other caller.

	Guarded by ``has_field`` so a doctype joining that list later cannot break saving a
	booking; it simply carries no stamp until someone gives it the field.
	"""
	targets = [(o["doctype"], o["name"]) for o in container_open_orders(container)]
	targets += [
		("Inspection", name)
		for name in frappe.get_all(
			"Inspection",
			filters={"container": container, "inspection_type": "EIR-Out", "docstatus": 0},
			pluck="name",
		)
	]
	for doctype, name in targets:
		meta = frappe.get_meta(doctype)
		stamp = {}
		if meta.has_field("target_lift_on"):
			stamp["target_lift_on"] = date
		if meta.has_field("target_survey_on"):
			stamp["target_survey_on"] = survey
		if stamp:
			frappe.db.set_value(doctype, name, stamp, update_modified=False)
	# ...and the open survey rows, for the same reason as the EIR-Out: getting the tank down and
	# checked is part of getting it OUT, not something standing in the way of it. Those two
	# worklists are arguably the ones that want the date most — an operator with ten tanks to
	# drop should start with the one on a truck's schedule. Written separately because they are
	# child rows: they carry no ``container`` doctype of their own to loop over above.
	frappe.db.set_value(
		"Survey Order Tank",
		{"container": container, "parenttype": "Survey Order", "status": ["!=", "Cancelled"]},
		{"target_lift_on": date, "target_survey_on": survey}, update_modified=False,
	)


def containers_pointing_to(booking: str) -> list:
	return frappe.get_all("Container", filters={CONTAINER_FIELD: booking}, pluck="name")


def release_on_gate_out(container: str) -> None:
	"""The tank has left: drop its lift-on stamp whichever booking owns it.

	Called from ``gate.mark_gate_out``. The pickup this date was preparing for has happened,
	so leaving the stamp on would keep a departed tank at the top of a worklist it no longer
	belongs to — and would block the customer's NEXT notice from claiming it.
	"""
	booking = frappe.db.get_value("Container", container, CONTAINER_FIELD)
	if booking:
		clear_target(container, booking)


# --- how much of an outbound booking has actually left ------------------------
FULFILLED_STATUS = "Completed"


def refresh_fulfilment(booking: str) -> bool:
	"""Rewrite one outbound booking's ``% Keluar`` from the live Container statuses, and
	close it at 100%. Returns whether this call closed it.

	Modelled on Purchase Receipt's ``% Amount Billed``: a stored percentage saying how much
	of the document is done, so a partly-collected booking reads as progress rather than as
	an open/closed flag. A lift-on is routinely collected over several visits — the bon
	carries at most two tanks — so a five-tank booking spends most of its life somewhere in
	between, and looked exactly like one nobody had started.

	No "was already out" baseline is needed here, unlike the Gate Out Plan this came from: a
	Tank Out booking can only be submitted for tanks that are PRESENT, so a row that reads
	``Gate_Out`` left on this booking's watch.

	Deliberately ``db.set_value`` and never ``doc.save()``: this runs from inside an
	unrelated document's save (the gate-out), where re-running the booking's validation
	could throw on a state that has nothing to do with the tank leaving.
	"""
	row = frappe.db.get_value(
		"Container Booking", booking, ["direction", "booking_status", "docstatus"], as_dict=True
	)
	if not row or row.direction != OUTBOUND:
		return False
	containers = frappe.get_all(
		"Container Booking Item",
		filters={"parent": booking, "parenttype": "Container Booking"},
		pluck="container",
	)
	listed = [c for c in containers if c]
	if not listed:
		frappe.db.set_value("Container Booking", booking, "per_fulfilled", 0, update_modified=False)
		return False
	away = frappe.db.count("Container", {"name": ["in", listed], "status": "Gate_Out"})
	per = round(away * 100.0 / len(listed), 2)
	updates = {"per_fulfilled": per}
	# Only a live, submitted booking closes. A draft has not started, and Cancelled /
	# Completed are already terminal — re-closing would rewrite history on every gate-out of
	# a tank that came back for another visit.
	close = per >= 100 and row.docstatus == 1 and row.booking_status == "Confirmed"
	if close:
		updates["booking_status"] = FULFILLED_STATUS
	# ...and the same door swings both ways. A departure can be TAKEN BACK — the EIR-Out that
	# declared it is reverted or voided (``gate.reverse_gate_out``) — and the tank is then
	# standing in the yard again. Left alone, the booking kept reading Completed at, say, 60%:
	# closed against tanks that had not gone anywhere, and out of every "still to collect"
	# list the yard works from. Only a booking that is still SUBMITTED reopens; a cancelled
	# one is terminal for a different reason and is never touched here.
	elif per < 100 and row.docstatus == 1 and row.booking_status == FULFILLED_STATUS:
		updates["booking_status"] = "Confirmed"
	frappe.db.set_value("Container Booking", booking, updates, update_modified=False)
	return close


def refresh_bookings_for_container(container: str) -> list:
	"""Recompute ``% Keluar`` on every outbound booking listing this tank; returns those it
	closed. Called from ``gate.mark_gate_out`` — the only moment it can change."""
	if not container:
		return []
	bookings = frappe.get_all(
		"Container Booking Item",
		filters={"container": container, "parenttype": "Container Booking"},
		pluck="parent",
		distinct=True,
	)
	return [b for b in bookings if refresh_fulfilment(b)]
