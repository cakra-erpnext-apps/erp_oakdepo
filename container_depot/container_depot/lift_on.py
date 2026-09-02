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

# The header's date for the day the tanks are collected — what the whole priority is about.
# On the header, not per line: one booking is one job with one intended day, and the line
# carries the realisation (the day its bon came out) instead — a date that only exists once
# the preparation this deadline drives is already over.
HEADER_DATE = "plan_date"


def _booking_is_live(doc) -> bool:
	"""Does this booking still expect its tanks to leave?

	Cancelled either way — ``booking_status`` (set by ``void_draft`` on a draft) or
	``docstatus`` 2 — owns nothing any more. Everything else does, including a plain draft:
	see the module docstring.
	"""
	return (
		doc.get("direction") == OUTBOUND
		and doc.get("booking_status") != "Cancelled"
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
	for row in doc.get("items") or []:
		if not row.get("container"):
			continue
		listed.add(row.container)
		if live and date:
			set_target(row.container, date, doc.name)
		else:
			clear_target(row.container, doc.name)
	for container in containers_pointing_to(doc.name):
		if container not in listed:
			clear_target(container, doc.name)


def set_target(container: str, date, booking: str) -> None:
	d = getdate(date)
	frappe.db.set_value(
		"Container", container,
		{"target_lift_on": d, CONTAINER_FIELD: booking},
		update_modified=False,
	)
	push_to_open_orders(container, d)


def clear_target(container: str, booking: str) -> None:
	"""Release the stamp only if this container still points at THIS booking — never
	clobber one another booking owns."""
	if frappe.db.get_value("Container", container, CONTAINER_FIELD) != booking:
		return
	frappe.db.set_value(
		"Container", container,
		{"target_lift_on": None, CONTAINER_FIELD: None},
		update_modified=False,
	)
	push_to_open_orders(container, None)


def push_to_open_orders(container: str, date) -> None:
	"""Mirror the container's ``target_lift_on`` onto every order still holding it, so the
	PWA + Desk worklists can sort and badge by it across pagination.

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
	# ...and the open position survey, for the same reason as the EIR-Out: locating the tank
	# is part of getting it OUT, not something standing in the way of it. Its worklist is
	# arguably the one that wants the date most — a surveyor with ten tanks to find should
	# walk to the one on a truck's schedule first.
	targets += [
		("Container Position Survey", name)
		for name in frappe.get_all(
			"Container Position Survey",
			filters={"container": container, "docstatus": 0, "status": ["!=", "Cancelled"]},
			pluck="name",
		)
	]
	for doctype, name in targets:
		if frappe.get_meta(doctype).has_field("target_lift_on"):
			frappe.db.set_value(doctype, name, "target_lift_on", date, update_modified=False)


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
