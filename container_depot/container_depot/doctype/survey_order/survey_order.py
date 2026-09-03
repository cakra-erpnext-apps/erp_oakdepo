# Copyright (c) 2026, Oak Depot Team and contributors
# For license information, please see license.txt

"""Survey Order — one outbound booking's field survey, and everything about its progress.

A Container Booking says which tanks a customer is collecting and when. Its ``survey_date``
says when the yard will get them ready. That day's work is this document: one per outbound
booking, created automatically from the DRAFT booking (see
``tank_survey.provision_survey_order_for_booking``), carrying the principal, the appointed
surveyor and the pickup deadline — and, in ``tanks``, every tank with its own two steps::

    Waiting Lowering --(Kalmar / Surveyor)--> Lowered --(Surveyor)--> Survey Done

WHY EVERY STATUS LIVES HERE AND NOT ON THE TANK
------------------------------------------------
Both steps are facts about a PICKUP, not about a tank. A tank collected twice has two
lowerings and two surveys, on two different days, for two different customers — so they
belong to the document that represents the visit. The tank itself only ever has one thing
worth carrying forward, and that is where it is standing.

WHICH IS ALSO WHY THE LOCATION IS NOT COPIED IN HERE
-----------------------------------------------------
Where a tank stands is recorded by ``Container Position`` — a reading anyone in the yard can
add at any time — and mirrored onto the ``Container`` master with the moment it was taken.
Every screen built on this document reads it live from there. A copy on the row would be
frozen at the moment the schedule was written, and would quietly disagree with the master
after the first correction. The freshness matters as much as the place: "blok kanan, dicatat
2 jam lalu" and "blok kanan, dicatat bulan Juni" are not the same instruction.

SUBMITTABLE, AND WHAT THE SUBMIT MEANS
---------------------------------------
The day closes itself: :func:`refresh_progress` submits the schedule once every live tank
reaches Survey Done, and a reopen pushes it back to draft. So docstatus 1 means "this day's
field work is finished", which is also what makes the permission split work — ``surveyPos``
(closing a survey) keys on submit and ``posFix`` (lowering) on write, over this one doctype.
See ``ess.context._MENU``.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document

from container_depot.container_depot.doctype.container_booking.container_booking import (
	build_container_summary,
)

SCHEDULED = "Scheduled"
IN_PROGRESS = "In Progress"
COMPLETED = "Completed"
CANCELLED = "Cancelled"


class SurveyOrder(Document):
	def validate(self):
		# The depot each tank is actually standing in, filled once at insert. Read per ROW and
		# not off the header: an outbound booking may collect from two depots of one branch,
		# and then the header carries no depot at all — and the flat PWA queues scope on this
		# column to keep a branch's operators out of another branch's yard.
		for row in self.tanks or []:
			if row.container and not row.depot:
				row.depot = frappe.db.get_value("Container", row.container, "depot") or self.depot

	def before_cancel(self):
		"""Cancelling the schedule cancels its tanks with it.

		Otherwise a cancelled day leaves live rows behind, and they would keep appearing in
		the lowering queue for a pickup nobody is coming for.
		"""
		for row in self.tanks or []:
			if row.status != "Survey Done":
				row.db_set("status", CANCELLED, update_modified=False)


def refresh_progress(name: str) -> dict:
	"""Recompute one schedule's counts + status from its tank rows. Idempotent.

	Called after anything that can move a tank (provisioning, lowering, closing, reopening,
	cancelling). Written with ``db.set_value`` and never ``doc.save()``: it runs from inside
	an unrelated save, where re-running this document's validation could throw on a state that
	has nothing to do with the tank that just moved.

	``status`` is derived, never typed:

	* no live tanks at all → ``Cancelled`` (the booking dropped its rows);
	* every live tank finished → ``Completed``, and the document is SUBMITTED;
	* at least one tank down → ``In Progress``;
	* otherwise → ``Scheduled``.

	A schedule already ``Cancelled`` is left alone: that status is set deliberately, by the
	booking being voided, and it is not a projection of the tanks — the rows underneath a
	called-off day are untouched, so recomputing from them would put it back on the calendar.
	"""
	from container_depot.container_depot.tank_survey import DONE, LOWERED

	if not name or not frappe.db.exists("Survey Order", name):
		return {}
	current = frappe.db.get_value("Survey Order", name, ["status", "docstatus"], as_dict=True)
	if current.status == CANCELLED:
		return {}

	rows = frappe.get_all(
		"Survey Order Tank",
		filters={"parent": name, "parenttype": "Survey Order"},
		fields=["status", "container_no"],
		order_by="idx asc",
	)
	live = [r for r in rows if r.status != CANCELLED]
	total = len(live)
	done = sum(1 for r in live if r.status == DONE)
	# A finished survey has necessarily been lowered — the status graph allows no other way
	# in — so "sudah turun" is the union, not just the tanks parked at Lowered.
	lowered = sum(1 for r in live if r.status in (LOWERED, DONE))

	if not total:
		status = CANCELLED if rows else SCHEDULED
	elif done == total:
		status = COMPLETED
	elif lowered:
		status = IN_PROGRESS
	else:
		status = SCHEDULED

	values = {
		"tank_count": total,
		"lowered_count": lowered,
		"survey_done_count": done,
		"per_surveyed": round(done * 100.0 / total, 2) if total else 0,
		"status": status,
		"container_summary": build_container_summary([r.container_no for r in live if r.container_no]),
	}
	# The day's own docstatus follows its tanks, both ways. Written raw rather than through
	# doc.submit(): this runs mid-save of another document, and a real submit would re-run
	# validation and fire hooks for a state change that is really just arithmetic.
	values["docstatus"] = 1 if status == COMPLETED else 0
	frappe.db.set_value("Survey Order", name, values, update_modified=False)
	return values
