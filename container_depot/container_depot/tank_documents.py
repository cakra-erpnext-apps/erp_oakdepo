"""Every document open against a tank, in one list — the dossier behind a lift-on.

"Belum: Cleaning, M&R" says a tank is held up but not by WHAT. This names the document, so
it can be opened instead of hunted for, and it answers the question a Tank Out booking is
opened to ask once the truck is on its way: what still has to happen to these tanks?

Six kinds, in the order an operator thinks about them: the Cleaning / M&R work behind
readiness, the EIRs recording the tank's condition, and the Booking / Bongkar / Muat
paperwork it moves under.

Two different questions are answered side by side and must not be confused:

* ``open``   — unfinished. Everything here is tracked on that basis.
* ``blocks`` — unfinished AND standing between the tank and the gate. Only Cleaning and M&R
  can. A draft EIR is unfinished paperwork; an open Tank Out booking is the very way out.
  Counting either as a blocker would hold up every tank forever.

Read live, never stored: the answer must not be able to age.

Ported from Gate Out Plan, which was a separate notice document sitting in front of the
booking and has been removed — the booking is where this belongs, because the booking is
what the tanks actually leave on.
"""

from __future__ import annotations

import frappe
from frappe import _

# A Cleaning / Repair order in one of these no longer blocks gate-out (work is finished).
_CLEANING_DONE = ("Completed", "Cancelled")
_MR_DONE = ("Completed", "Cancelled", "Rejected")

# Container status meaning the tank has left.
GATE_OUT_STATUS = "Gate_Out"


def _tank_orders(container: str) -> list:
	"""Every Cleaning / M&R order of this tank, newest first, each flagged ``blocks`` while it
	is still open.

	Readiness and the detail list are read off this ONE query, so the Kesiapan column can
	never disagree with the orders shown underneath it. Finished and cancelled orders are
	kept — "which orders touched this tank" is the question, and a cancelled order that used
	to block is worth seeing.
	"""
	out = []
	for kind, doctype, done in (
		("Cleaning", "Cleaning Order", _CLEANING_DONE),
		("M&R", "Repair Order", _MR_DONE),
	):
		for r in frappe.get_all(
			doctype,
			filters={"container": container},
			fields=["name", "status", "docstatus"],
			order_by="creation desc",
		):
			cancelled = r.docstatus == 2
			blocks = not cancelled and r.status not in done
			out.append({
				"kind": kind,
				"doctype": doctype,
				"name": r.name,
				"status": _("Cancelled") if cancelled else r.status,
				# Work that must finish before the tank can leave: open means blocking here.
				"blocks": blocks,
				"open": blocks,
				"done": not blocks and not cancelled,
				"cancelled": cancelled,
			})
	return out


def _tank_eirs(container: str) -> list:
	"""The tank's EIR-In / EIR-Out inspections, newest first — same shape as an order line.

	Never ``blocks``: an EIR is a record of a moment, not work to be finished. EIR-Out in
	particular is written AT the gate on the way out, so it can only ever exist after the
	lift-on this plan is preparing for — treating it as a prerequisite would make every tank
	permanently "not ready". They are here as the condition history behind a lift-on: what the
	tank looked like coming in, and (once it has left) what went out.
	"""
	out = []
	for r in frappe.get_all(
		"Inspection",
		filters={"container": container},
		fields=["name", "inspection_type", "status", "docstatus", "eir_date"],
		order_by="creation desc",
	):
		cancelled = r.docstatus == 2
		done = not cancelled and r.status == "Submitted"
		out.append({
			"kind": r.inspection_type or "EIR",
			"doctype": "Inspection",
			"name": r.name,
			"status": _("Cancelled") if cancelled else r.status,
			"blocks": False,
			# Only a submitted EIR is a finished record; a draft one is still being written —
			# unfinished, and worth tracking, but never a reason a tank cannot leave.
			"open": not cancelled and not done,
			"done": done,
			"cancelled": cancelled,
		})
	return out


# The paperwork a tank moves under: the booking that authorises the visit and the bons that
# work it. None of these hold a lift-on back — a Tank Out booking IS the way out, not an
# obstacle — but an unfinished one is exactly what an operator preparing a pickup needs to
# see, which is why they are tracked here rather than folded into Kesiapan.
#
# (kind, doctype, child doctype, parentfield, status field, direction)
#
# Direction is what says WHICH WAY the tank was meant to move, and that is the only thing
# that can tell whether the document is finished with it. A booking carries its own; a bon
# does not need one — bongkar is unloading (inbound) and muat is loading (outbound), always.
_TANK_JOBS = (
	("Booking", "Container Booking", "Container Booking Item", "items", "booking_status", "p.direction"),
	("Bongkar", "Order Bongkar", "Container Booking Item", "containers", "order_status", "'Tank In'"),
	("Muat", "Order Muat", "Order Container Item", "containers", "order_status", "'Tank Out'"),
)


def _tank_jobs(container: str, tank_status: str | None) -> list:
	"""Bookings and bons this tank sits on, newest first — same line shape as an order.

	They reach the tank through a child table rather than a field of their own, so each is
	one join instead of "read the rows, then read their parents". The row tables are indexed
	on ``container``, so this is a lookup, not a scan.

	Whether one is FINISHED is judged per tank, not per document, because that is the
	question being asked: a booking covering ten tanks is done for the three that have
	arrived and still pending for the seven that have not. See :func:`_job_done`.
	"""
	out = []
	for kind, doctype, child, parentfield, status_field, extra in _TANK_JOBS:
		rows = frappe.db.sql(
			"""
			select p.name, p.docstatus, p.`{status_field}` as status, {extra} as direction
			  from `tab{child}` r
			  join `tab{parent}` p on p.name = r.parent
			 where r.container = %s and r.parenttype = %s and r.parentfield = %s
			 order by p.creation desc
			""".format(child=child, parent=doctype, status_field=status_field, extra=extra),
			(container, doctype, parentfield),
			as_dict=True,
		)
		# A booking is not work until a bon comes off it: the bon is the paper the driver is
		# handed at the gate. Confirmed-but-unbonned is therefore the state an operator
		# preparing a pickup most needs to spot, and it is invisible from the booking's own
		# status (which stops at Confirmed either way).
		awaiting = (
			_bookings_awaiting_bon(container, [r.name for r in rows])
			if doctype == "Container Booking"
			else set()
		)
		for r in rows:
			cancelled = r.docstatus == 2 or r.status == "Cancelled"
			done = False if cancelled else _job_done(r, tank_status)
			detail = None
			if doctype == "Container Booking":
				detail = r.direction
				if not cancelled and r.name in awaiting:
					detail = _("{0} · belum ada bon").format(r.direction or _("Booking"))
			out.append({
				"kind": kind,
				# Which way the booking was going. Only one booking is shown per tank (the
				# latest), so without this the line cannot say whether that last booking
				# brought the tank in or took it out — the first thing asked of it.
				"detail": detail,
				"doctype": doctype,
				"name": r.name,
				"status": _("Cancelled") if cancelled else r.status,
				"blocks": False,
				"open": not cancelled and not done,
				"done": done,
				"cancelled": cancelled,
			})
	return out


def _bookings_awaiting_bon(container: str, bookings: list) -> set:
	"""Of ``bookings``, the ones that still owe THIS tank a bon.

	The Booking Code is the answer: it is issued per container at booking submit and only
	leaves ``Active`` when a bon picks it up (and comes back to ``Active`` when that bon is
	voided). Asked per tank, not per booking, because a booking covering ten tanks is
	routinely bonned two at a time.
	"""
	if not bookings or not container:
		return set()
	return set(
		frappe.get_all(
			"Booking Code",
			filters={"booking": ["in", bookings], "container": container, "state": "Active"},
			pluck="booking",
		)
	)


def _job_done(job, tank_status: str | None) -> bool:
	"""Has this booking / bon finished with THIS tank?

	**The tank moving is what finishes the document, not a status field.** Two of these
	fields do not reliably advance on their own: ``booking_status`` stops at ``Confirmed``
	(approved and paid — where a booking STARTS being work, not where it stops), and an Order
	Bongkar has no auto-complete at all, so it sits at ``Issued`` long after every tank on it
	has been unloaded and parked. Reading either as "still open" leaves finished paperwork
	glowing on the worklist; reading Confirmed as "done" hides bookings that have brought
	nothing in yet. Neither is a state an operator can act on.

	So the rule is the same for all three, and it is about the tank:

	* still a draft → never done, it is still being written;
	* ``Hold`` → never done, that status exists to say something needs attention;
	* ``Completed`` → done, the document says so outright;
	* **inbound** (Tank In / Bongkar) → done once the tank is no longer merely reserved: it
	  has arrived (``In_Depot`` / ``Available``), or has since left again;
	* **outbound** (Tank Out / Muat) → done once the tank has actually left.
	"""
	if job.docstatus != 1:
		return False
	if job.status == "Hold":
		return False
	if job.status == "Completed":
		return True
	if job.direction == "Tank Out":
		return tank_status == GATE_OUT_STATUS
	return tank_status is not None and tank_status != "Booked"




def documents_for(container: str, tank_status: str | None = None) -> list:
	"""The whole dossier for one tank, filtered to what the caller may actually read.

	Counted and filtered on the SERVER: a role that cannot read Cleaning Orders must not be
	told how many of them are open either.
	"""
	if tank_status is None:
		tank_status = frappe.db.get_value("Container", container, "status")
	readable = {
		dt
		for dt in ("Cleaning Order", "Repair Order", "Inspection",
				   "Container Booking", "Order Bongkar", "Order Muat")
		if frappe.has_permission(dt, "read")
	}
	return [
		o
		for o in _tank_orders(container) + _tank_eirs(container) + _tank_jobs(container, tank_status)
		if o["doctype"] in readable
	]


def dossier(rows) -> list:
	"""One entry per listed tank: its live status, its documents, and the two counts.

	``rows``: iterable of dicts carrying ``container`` (+ optionally ``container_no`` and a
	target date), in the order they should be shown.
	"""
	out = []
	for r in rows:
		container = r.get("container")
		if not container:
			continue
		tank_status = frappe.db.get_value("Container", container, "status")
		orders = documents_for(container, tank_status)
		out.append({
			"container": container,
			"container_no": r.get("container_no") or container,
			# Read here rather than off the stored row: this panel is the live answer, and a
			# document's own copy is only as fresh as its last save.
			"status": tank_status,
			"target_lift_on": str(r["target_lift_on"]) if r.get("target_lift_on") else None,
			"open_count": sum(1 for o in orders if o["open"]),
			"blocking_count": sum(1 for o in orders if o["blocks"]),
			"orders": orders,
		})
	return out
