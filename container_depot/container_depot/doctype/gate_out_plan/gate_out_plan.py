"""Gate Out Plan — a customer's advance lift-on (gate-out) notice, transcribed by OAK.

A customer emails which tanks they will lift on (gate out) and roughly when (H-7 and up).
OAK records that here so the depot can PRIORITISE cleaning / repair on those tanks before
pickup. This is NOT a commercial order: no price list, no invoice, no release authorisation
— the customer's own Release DO stays the paperwork (attached in ``customer_do``).

The only thing this doc "does" is stamp a ``target_lift_on`` date onto each listed
Container while the plan is Open; the cleaning / M&R worklists read that date to float the
most urgent tanks first. Closing the plan (Fulfilled / Cancelled) or dropping a row releases
the stamp — but only if the container still points at THIS plan, so two plans never clobber
each other's stamp.
"""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate, today

from container_depot.container_depot.container_status import DONE_CLEANING, assert_rows_active

# Only an Open plan drives priority; closing it releases the container stamps.
ACTIVE_STATUS = "Open"
FULFILLED_STATUS = "Fulfilled"

# Container status meaning the tank has left — what "fulfilled" is measured against.
GATE_OUT_STATUS = "Gate_Out"

# A Cleaning / Repair order in one of these no longer blocks gate-out (work is finished).
_CLEANING_DONE = ("Completed", "Cancelled")
_MR_DONE = ("Completed", "Cancelled", "Rejected")


class GateOutPlan(Document):
	def validate(self):
		self._fill_rows()
		# A retired tank takes no new lift-on target. Rows already on the plan are
		# untouched — see assert_rows_active.
		assert_rows_active(self, "containers")
		self._assert_rows_match_header()
		self._assert_containers_unique()
		self._set_source()
		self._roll_up()

	def _set_source(self):
		"""Where the notice came in — the system's own note, not an operator field.

		Only a plan seeded from a Communication has an answer (``reff_email``, written by
		``mail_to_order``). A plan typed by hand leaves it blank: stamping "Email" on every
		manual plan told nobody anything and made the field look like an isian. An explicit
		value already set by an API caller (the customer channel, when it lands) stands.
		"""
		if self.reff_email and not self.source:
			self.source = "Email"

	def _fill_rows(self):
		"""Per row: mirror the container number, compute gate-out readiness, and flag the
		tanks that have left since this plan listed them."""
		before = None if self.is_new() else self.get_doc_before_save()
		listed = {r.name: r.container for r in ((before.get("containers") if before else None) or [])}
		for row in self.containers or []:
			if not row.container:
				row.container_no = row.readiness = None
				row.is_ready = row.gated_out = row.was_out = 0
				continue
			cn, status = frappe.db.get_value(
				"Container", row.container, ["container_no", "status"]
			) or (None, None)
			row.container_no = cn
			_set_departure(row, status, newly_listed=listed.get(row.name) != row.container)
			pending = _pending_work(row.container)
			row.is_ready = 0 if pending else 1
			row.readiness = _readiness_label(pending)

	def _roll_up(self):
		"""Header summaries for the list view: containers, X/Y ready, % keluar, nearest date."""
		rows = [r for r in (self.containers or []) if r.container]
		self.container_summary = ", ".join(r.container_no or r.container for r in rows) or None
		if rows:
			ready = sum(1 for r in rows if r.is_ready)
			self.readiness_summary = f"{ready}/{len(rows)} siap"
			self.per_fulfilled = flt(sum(1 for r in rows if r.gated_out) * 100.0 / len(rows), 2)
		else:
			self.readiness_summary = None
			self.per_fulfilled = 0
		dates = [getdate(r.target_lift_on) for r in rows if r.target_lift_on]
		self.next_lift_on = min(dates) if dates else None
		# NOT closed here on purpose: closing belongs to the gate-out event
		# (:func:`refresh_plan_fulfilment`). Doing it on save would slam a brand-new plan shut
		# the moment someone lists a tank that happens to have left on an earlier visit.

	def _assert_rows_match_header(self):
		"""Every tank still to be collected must belong to the header's Principal.

		Ownership is the only thing a plan can insist on. There is no header Depot to match
		against: a lift-on notice is written days ahead, and its tanks are routinely spread
		across depots, still on the road, or carrying no depot at all because they have
		never gated in here. Where each tank stands is the Container master's answer, shown
		per row (``depot``, fetched) rather than declared once for the whole notice.

		The row picker already filters on Principal, so this is the server's own answer to
		what the picker cannot see: an Excel import, an API caller, or a header edited
		*after* the rows were listed. It matters because saving is what stamps
		``target_lift_on`` — another owner's tank would get a lift-on target nobody asked
		for, and float up somebody else's cleaning worklist.

		Rows already gated out are skipped: that tank has left and its row is history. Who
		owns it *now* — a resale — says nothing about the lift-on it was collected under, and
		re-checking it would lock up a partly-collected plan whose remaining tanks are still
		being worked.
		"""
		names = [r.container for r in (self.containers or []) if r.container and not r.gated_out]
		if not names or not self.principal:
			return
		wrong = [
			_("{0}: milik {1}, bukan {2}").format(
				c.container_no or c.name, c.principal or _("(tanpa pemilik)"), self.principal
			)
			for c in frappe.get_all(
				"Container",
				filters={"name": ["in", names], "principal": ["!=", self.principal]},
				fields=["name", "container_no", "principal"],
			)
		]
		if wrong:
			frappe.throw(
				"<br>".join(wrong)
				+ "<br><br>"
				+ _("Ganti Principal di header, atau hapus baris container ini."),
				title=_("Container Tidak Cocok dengan Header"),
			)

	def _assert_containers_unique(self):
		"""A container may be claimed by only ONE active (Open) plan — and only once within
		this plan — so two live plans never fight over the same tank's lift-on priority. A
		closed plan (Fulfilled / Cancelled) releases its containers, freeing them for a new one."""
		seen = set()
		for row in self.containers or []:
			if not row.container:
				continue
			if row.container in seen:
				frappe.throw(
					_("Container {0} tercantum lebih dari sekali di plan ini.").format(
						row.container_no or row.container
					)
				)
			seen.add(row.container)
		# Only an Open plan claims its containers exclusively.
		if self.status != ACTIVE_STATUS or not seen:
			return
		rows = frappe.get_all(
			"Gate Out Plan Item",
			filters={"container": ["in", list(seen)], "parenttype": "Gate Out Plan"},
			fields=["container", "parent"],
		)
		others = {r.parent for r in rows if r.parent != self.name}
		open_others = (
			set(
				frappe.get_all(
					"Gate Out Plan",
					filters={"name": ["in", list(others)], "status": ACTIVE_STATUS},
					pluck="name",
				)
			)
			if others
			else set()
		)
		for r in rows:
			if r.parent in open_others:
				frappe.throw(
					_(
						"Container {0} sudah ada di Gate Out Plan {1} yang masih Open. "
						"Selesaikan / batalkan plan itu dulu, atau hapus container-nya dari sana."
					).format(r.container, r.parent)
				)

	def on_update(self):
		self._sync_container_targets()

	def on_trash(self):
		for cn in _containers_pointing_to(self.name):
			_clear_target(cn, self.name)

	def _sync_container_targets(self):
		"""Stamp target_lift_on onto each listed container while Open; release it when the
		plan is closed or a container is dropped from the list."""
		active = self.status == ACTIVE_STATUS
		listed = set()
		for row in self.containers or []:
			if not row.container:
				continue
			listed.add(row.container)
			if active and row.target_lift_on:
				_set_target(row.container, row.target_lift_on, self.name)
			else:
				_clear_target(row.container, self.name)
		# Containers that used to point here but are no longer listed → release.
		for cn in _containers_pointing_to(self.name):
			if cn not in listed:
				_clear_target(cn, self.name)


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
		for r in rows:
			cancelled = r.docstatus == 2 or r.status == "Cancelled"
			done = False if cancelled else _job_done(r, tank_status)
			out.append({
				"kind": kind,
				# Which way the booking was going. Only one booking is shown per tank (the
				# latest), so without this the line cannot say whether that last booking
				# brought the tank in or took it out — the first thing asked of it.
				"detail": r.direction if doctype == "Container Booking" else None,
				"doctype": doctype,
				"name": r.name,
				"status": _("Cancelled") if cancelled else r.status,
				"blocks": False,
				"open": not cancelled and not done,
				"done": done,
				"cancelled": cancelled,
			})
	return out


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


def _set_departure(row, status: str | None, *, newly_listed: bool) -> None:
	"""Decide whether this row's tank has left FOR THIS PLAN, and keep its baseline honest.

	``Gate_Out`` on a Container means "not in my yard" — which covers a tank that just rolled
	out the gate AND a tank that was never here in the first place (the doctype's own default,
	and what a bulk-injected master carries until it gates in). Reading that status flat would
	mark a plan 100% collected the moment it lists such a tank, and a plan that starts at 100%
	can never be worked: no booking button, and the auto-close only fires on a real gate-out
	that will never come.

	So the row remembers where the tank STOOD when it was listed (``was_out``) and reports
	only the change:

	* tank present  → the baseline is spent; clear it (a tank that came back and leaves again
	  counts, which is the whole point of listing it).
	* tank away, just listed → baseline set; this departure predates the plan.
	* tank away, listed earlier with a clear baseline → it left on this plan's watch.

	Deliberately NOT keyed on a Gate Entry: tanks that arrive by data import have no gate
	record at all, and their presence is carried by ``status`` alone.
	"""
	if status != GATE_OUT_STATUS:
		row.was_out = 0
	elif newly_listed:
		row.was_out = 1
	row.gated_out = 1 if status == GATE_OUT_STATUS and not cint(row.was_out) else 0


def _pending_work(container: str) -> list:
	"""Open work that must finish before this tank can gate out (readiness = its blockers)."""
	kinds = [o["kind"] for o in _tank_orders(container) if o["blocks"]]
	return list(dict.fromkeys(kinds))  # dedupe, keep Cleaning before M&R


def _readiness_label(pending: list) -> str:
	return "Siap" if not pending else "Belum: " + ", ".join(pending)


def _set_target(container: str, date, plan: str) -> None:
	d = getdate(date)
	frappe.db.set_value(
		"Container", container,
		{"target_lift_on": d, "gate_out_plan": plan},
		update_modified=False,
	)
	_push_to_open_orders(container, d)


def _clear_target(container: str, plan: str) -> None:
	"""Release the stamp only if this container still points at THIS plan (don't clobber a
	stamp another active plan owns)."""
	if frappe.db.get_value("Container", container, "gate_out_plan") == plan:
		frappe.db.set_value(
			"Container", container,
			{"target_lift_on": None, "gate_out_plan": None},
			update_modified=False,
		)
		_push_to_open_orders(container, None)


def _push_to_open_orders(container: str, date) -> None:
	"""Mirror the container's target_lift_on onto its still-open Cleaning / M&R orders so the
	PWA + Desk worklists can sort & badge by it across pagination. New orders inherit it via
	``fetch_from``; this keeps ALREADY-open orders in sync when the plan changes or closes."""
	for ro in frappe.get_all(
		"Repair Order", filters={"container": container, "status": ["not in", _MR_DONE]}, pluck="name"
	):
		frappe.db.set_value("Repair Order", ro, "target_lift_on", date, update_modified=False)
	for co in frappe.get_all(
		"Cleaning Order",
		filters={"container": container, "status": ["not in", _CLEANING_DONE], "docstatus": ["<", 2]},
		pluck="name",
	):
		frappe.db.set_value("Cleaning Order", co, "target_lift_on", date, update_modified=False)


def _containers_pointing_to(plan: str) -> list:
	return frappe.get_all("Container", filters={"gate_out_plan": plan}, pluck="name")


# --- keeping Kesiapan current ------------------------------------------------
def refresh_plans_for_order(doc, method=None) -> None:
	"""Recompute the Kesiapan of every Open plan that lists this order's container.

	Readiness is STORED (``is_ready`` / ``readiness`` / ``readiness_summary``) so the list
	view can sort and filter on it — which means it goes stale the moment a Cleaning / M&R
	order finishes, i.e. exactly when the plan matters most. So every write to such an order
	pushes the recompute here (see hooks.doc_events).

	Only Open plans: a Fulfilled / Cancelled plan is a closed record and its numbers should
	stay as they were when it closed.
	"""
	container = doc.get("container")
	if not container:
		return
	for plan in _open_plans_for(container):
		refresh_plan_readiness(plan)


def _open_plans_for(container: str) -> list:
	parents = frappe.get_all(
		"Gate Out Plan Item",
		filters={"container": container, "parenttype": "Gate Out Plan"},
		pluck="parent",
		distinct=True,
	)
	if not parents:
		return []
	return frappe.get_all(
		"Gate Out Plan",
		filters={"name": ["in", parents], "status": ACTIVE_STATUS},
		pluck="name",
	)


def refresh_plan_readiness(plan: str) -> None:
	"""Rewrite one plan's stored readiness from the live order state.

	Deliberately ``db.set_value`` and not ``doc.save()``: saving would re-run validation (a
	plan whose container was meanwhile claimed elsewhere would start throwing from inside an
	unrelated order's save) and would re-stamp every container's target_lift_on. Nothing here
	touches the plan's own data — only the derived readiness — so the document is left alone,
	``modified`` included.
	"""
	rows = frappe.get_all(
		"Gate Out Plan Item",
		filters={"parent": plan, "parenttype": "Gate Out Plan"},
		fields=["name", "container"],
	)
	listed, ready = 0, 0
	for r in rows:
		if not r.container:
			continue
		listed += 1
		pending = _pending_work(r.container)
		if not pending:
			ready += 1
		frappe.db.set_value(
			"Gate Out Plan Item", r.name,
			{"is_ready": 0 if pending else 1, "readiness": _readiness_label(pending)},
			update_modified=False,
		)
	frappe.db.set_value(
		"Gate Out Plan", plan,
		{"readiness_summary": f"{ready}/{listed} siap" if listed else None},
		update_modified=False,
	)


# --- closing the plan when its tanks actually leave ---------------------------
def refresh_plans_for_container(container: str) -> list:
	"""Recompute ``% Keluar`` on every Open plan listing this tank; returns those it closed.

	Called from ``gate.mark_gate_out`` right after the tank moves to ``Gate_Out`` — the only
	moment a plan's fulfilment can change.
	"""
	if not container:
		return []
	return [p for p in _open_plans_for(container) if refresh_plan_fulfilment(p)]


def refresh_plan_fulfilment(plan: str) -> bool:
	"""Rewrite one plan's ``% Keluar`` from the live Container statuses, closing it at 100%.

	Modelled on Purchase Receipt's ``% Amount Billed``: a stored percentage that says how much
	of the document is done, so a partly-collected plan reads as progress rather than as an
	open/closed flag. Reaching 100% flips the plan to Fulfilled, which is what releases each
	tank's ``target_lift_on`` stamp and frees it for the customer's next lift-on notice.

	Deliberately ``db.set_value`` and never ``doc.save()`` — for the same reason as
	:func:`refresh_plan_readiness`: this runs from inside an unrelated document's save (the
	gate-out), where re-running the plan's validation could throw on a state that has nothing
	to do with the tank leaving. Returns whether this call closed the plan.
	"""
	rows = frappe.get_all(
		"Gate Out Plan Item",
		filters={"parent": plan, "parenttype": "Gate Out Plan"},
		fields=["name", "container", "was_out"],
	)
	listed = [r for r in rows if r.container]
	if not listed:
		frappe.db.set_value("Gate Out Plan", plan, "per_fulfilled", 0, update_modified=False)
		return False

	away = set(
		frappe.get_all(
			"Container",
			filters={"name": ["in", [r.container for r in listed]], "status": GATE_OUT_STATUS},
			pluck="name",
		)
	)
	# Same rule as the save path (:func:`_set_departure`), applied field by field because
	# this runs on rows, not on a loaded document.
	left = 0
	for r in listed:
		updates = {}
		if r.container not in away:
			if cint(r.was_out):
				updates["was_out"] = 0
			r.was_out = 0
		out = r.container in away and not cint(r.was_out)
		updates["gated_out"] = 1 if out else 0
		left += 1 if out else 0
		frappe.db.set_value("Gate Out Plan Item", r.name, updates, update_modified=False)

	per = flt(left * 100.0 / len(listed), 2)
	updates = {"per_fulfilled": per}
	close = per >= 100 and frappe.db.get_value("Gate Out Plan", plan, "status") == ACTIVE_STATUS
	if close:
		updates["status"] = FULFILLED_STATUS
	frappe.db.set_value("Gate Out Plan", plan, updates, update_modified=False)
	if close:
		# What on_update would have done: a closed plan owns no tank any more.
		for cn in _containers_pointing_to(plan):
			_clear_target(cn, plan)
	return close


@frappe.whitelist()
def related_orders(gate_out_plan: str) -> list:
	"""Per listed tank, EVERY document still open against it, plus the finished ones as history.

	Six kinds, in the order an operator thinks about them: the Cleaning / M&R work behind
	Kesiapan, the EIRs recording its condition, and the Booking / Bongkar / Muat paperwork it
	moves under. "Belum: Cleaning, M&R" says a tank is held up but not by WHAT — this names
	the document, so it can be opened instead of hunted for.

	Two different questions are answered side by side and must not be confused:

	* ``open``   — unfinished. Everything here is tracked on that basis.
	* ``blocks`` — unfinished AND standing between the tank and the gate. Only Cleaning and
	  M&R can. A draft EIR is unfinished paperwork; an open Tank Out booking is the very way
	  out. Counting either as a blocker would hold up every tank on the plan forever.

	Read live, never stored: the answer must not be able to age.
	"""
	frappe.has_permission("Gate Out Plan", "read", doc=gate_out_plan, throw=True)
	readable = {
		dt
		for dt in ("Cleaning Order", "Repair Order", "Inspection",
				   "Container Booking", "Order Bongkar", "Order Muat")
		if frappe.has_permission(dt, "read")
	}
	out = []
	for r in frappe.get_all(
		"Gate Out Plan Item",
		filters={"parent": gate_out_plan, "parenttype": "Gate Out Plan"},
		fields=["container", "container_no", "target_lift_on"],
		order_by="idx asc",
	):
		if not r.container:
			continue
		tank_status = frappe.db.get_value("Container", r.container, "status")
		orders = [
			o
			for o in _tank_orders(r.container)
			+ _tank_eirs(r.container)
			+ _tank_jobs(r.container, tank_status)
			if o["doctype"] in readable
		]
		out.append({
			"container": r.container,
			"container_no": r.container_no or r.container,
			# Read here rather than off the stored row: the tab is the live answer, and the
			# grid's copy is only as fresh as the last save.
			"status": tank_status,
			"target_lift_on": str(r.target_lift_on) if r.target_lift_on else None,
			# Counted here, not in the browser: a role that cannot read Cleaning Orders must
			# not be told how many of them are open either.
			"open_count": sum(1 for o in orders if o["open"]),
			"blocking_count": sum(1 for o in orders if o["blocks"]),
			"orders": orders,
		})
	return out


@frappe.whitelist()
def pickable_containers(gate_out_plan: str) -> list:
	"""The plan's tanks that can still be booked, with their status read LIVE.

	The picker used to read the status mirrored on the plan row, which is only as fresh as
	the last save — so a tank whose cleaning finished after the plan was written still
	offered itself as ``In_Depot`` while the Order & EIR tab, which reads live, already
	called it ``Available``. Two panels on the same screen disagreeing about the same tank
	is worse than either being slightly stale, and the pre-ticking was wrong with it: the
	tank ready to go was not offered.

	Same source as :func:`related_orders`, so the two cannot drift again.
	"""
	frappe.has_permission("Gate Out Plan", "read", doc=gate_out_plan, throw=True)
	out = []
	for r in frappe.get_all(
		"Gate Out Plan Item",
		filters={"parent": gate_out_plan, "parenttype": "Gate Out Plan"},
		fields=["container", "container_no", "target_lift_on"],
		order_by="idx asc",
	):
		if not r.container:
			continue
		status = frappe.db.get_value("Container", r.container, "status")
		# Already gone: nothing left to book, and the row is history.
		if status == GATE_OUT_STATUS:
			continue
		out.append({
			"container": r.container,
			"container_no": r.container_no or r.container,
			"status": status,
			"target_lift_on": str(r.target_lift_on) if r.target_lift_on else None,
			# `Available` IS "present with no open work" (container_status.recompute_
			# availability keeps it so), which is the one state a Tank Out booking may be
			# submitted from — so it is the readiness test, not a second opinion on it.
			"ready": status == "Available",
			"readiness": _readiness_label(_pending_work(r.container)),
		})
	return out


# --- container list from Excel -----------------------------------------------
# A lift-on notice routinely names twenty tanks, and they arrive as a spreadsheet attached
# to the customer's mail. Mirrors Container Booking's grid importer (same dialog, same
# refusal rules, same "register what the master is missing" option) — only the columns
# differ, because a plan asks for a target date per tank where a booking asks for a
# condition.
_FILE_HEADERS = {"container", "container no", "kontainer", "no kontainer", "no container"}


@frappe.whitelist(methods=["GET"])
def download_container_template():
	"""Blank import template for the plan's Container grid: Container, Target Lift-On, Catatan."""
	from container_depot.xlsx_utils import finish_sheet, new_sheet

	headers = ["Container", "Target Lift-On (YYYY-MM-DD)", "Catatan"]
	output, wb, ws, fmts = new_sheet("Template", headers, [24, 26, 34])
	ws.write_row(1, 0, ["ABCD1234567", add_days(today(), 7), ""])
	finish_sheet(output, wb, ws, "gate_out_plan_template.xlsx", 1, len(headers) - 1)


def _create_container(container_no: str, principal: str) -> str:
	"""Register a Container master for a number a lift-on notice introduced.

	Same terms as Container Booking's importer (``_create_imported_container``): only the
	owner is stamped, and ``status`` / ``depot`` are left to the doctype's own default —
	*Departed*, "the master exists but the tank is not in my yard". A plan is written days
	ahead of the pickup and no longer asks the tank to be here, so claiming it stands
	Available at this depot would be the import inventing a gate-in that never happened.
	Gate-in is what stamps presence. Type defaults to ISO Tank, the only thing this depot
	stores; the rest of the spec is filled in on the master later.
	"""
	doc = frappe.get_doc({
		"doctype": "Container",
		"container_no": container_no,
		"container_type": "ISO Tank",
		"principal": principal,
	})
	doc.insert()
	return doc.name


def _match_key(container_no: str) -> str:
	"""A container number reduced to what identifies it: no spaces, no dashes, upper case.

	For MATCHING only. A depot's own numbering carries separators the customer's spreadsheet
	will not spell the same way twice, and the tank is the same tank either way. It must
	never be what gets stored — a master registered under the flattened form is a second,
	phantom record of a tank that already exists.
	"""
	return re.sub(r"[\s\-]+", "", container_no or "").upper()


def _container_index() -> dict:
	"""Every Container master keyed by :func:`_match_key`, for one file's worth of lookups.

	Where two masters flatten to the same key (the duplicates a dash-blind import used to
	create), the ACTIVE one wins, and failing that the older — the record with the history
	on it, rather than the empty one minted by mistake.
	"""
	index = {}
	for c in frappe.get_all(
		"Container",
		fields=["name", "container_no", "principal", "is_active", "creation"],
		order_by="creation asc",
	):
		key = _match_key(c.container_no or c.name)
		kept = index.get(key)
		if not kept or (c.is_active and not kept.is_active):
			index[key] = c
	return index


@frappe.whitelist()
def parse_container_xlsx(
	file_url: str,
	principal: str | None = None,
	create_missing: int | str | None = None,
) -> dict:
	"""Parse an uploaded .xlsx into plan rows: Container, Target Lift-On, Catatan.

	Resolves each number to an existing Container master. A number the master does not
	know is handled per ``create_missing``:

	* off — SKIPPED and listed in ``unknown``. A spreadsheet is exactly where a typo'd
	  tank number hides, and a plan stamps its target onto a real Container or it does
	  nothing at all.
	* on — the master is REGISTERED here and now (:func:`_create_container`), owned by the
	  plan's Principal, and the row comes back flagged ``is_new: 1``. Customers routinely
	  announce tanks whose master entry lags behind; refusing the whole notice over that is
	  what the flag exists to avoid. Every one created is named back in ``created`` so a
	  typo that just minted a master is visible immediately rather than discovered months
	  later.

	``principal`` (the plan's own) is applied as the row picker applies it — a tank of
	another owner is refused and named in ``errors`` rather than silently landing on the
	grid. Nothing else narrows the file: status and depot say where a tank is today, and a
	plan is written days before it needs to be anywhere.

	A missing or unreadable date is reported but does NOT drop the row: Target Lift-On is
	mandatory on the row, so the empty cell shows up on the grid itself where the operator
	can fill it, which beats losing the container.

	Returns ``{rows: [{container, container_no, target_lift_on, remark, is_new}], errors,
	unknown, created}``.
	"""
	from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file

	if not file_url:
		frappe.throw(_("Belum ada file yang dipilih."))
	create_missing = cint(create_missing)
	if create_missing:
		# A Container master cannot exist without an owner, and guessing one is not on the
		# table — the header carries it, so say so instead of failing row by row.
		if not principal:
			frappe.throw(_("Isi Principal di header dulu sebelum membuat master Container baru."))
		frappe.has_permission("Container", "create", throw=True)

	# Built once per file, not per row: the master keyed by its number with separators
	# removed, so "CNTH-1", "CNTH 1" and "cnth1" all find the tank that is already there.
	by_key = _container_index()

	rows, unknown, errors, created, seen = [], [], [], [], set()
	for cells in read_xlsx_file_from_attached_file(file_url=file_url) or []:
		if not cells or cells[0] is None:
			continue
		raw = str(cells[0]).strip()
		if not raw or raw.lower() in _FILE_HEADERS:
			continue
		# `cno` is the number AS WRITTEN (tidied only) — that is what a new master is
		# registered under, and what the operator sees reported back. `key` exists solely to
		# match it against the master; the two were once the same value, and collapsing them
		# is what minted a duplicate tank for every dashed number in a file.
		cno = raw.upper()
		key = _match_key(cno)
		if key in seen:
			continue
		seen.add(key)
		container = by_key.get(key)
		# A retired tank is out of the fleet: named and dropped rather than quietly given a
		# lift-on target, and never re-registered under the same number.
		if container and not container.is_active:
			errors.append(_("{0}: container non-aktif — dilewati").format(cno))
			continue
		is_new = 0
		if not container:
			if not create_missing:
				unknown.append(cno)
				continue
			container = frappe._dict(
				name=_create_container(cno, principal), principal=principal
			)
			by_key[key] = container
			created.append(cno)
			is_new = 1
		if principal and container.principal != principal:
			errors.append(_("{0}: bukan tank milik {1}").format(cno, principal))
			continue
		target = None
		raw_date = cells[1] if len(cells) > 1 else None
		if raw_date in (None, ""):
			errors.append(_("{0}: Target Lift-On kosong — isi manual di baris").format(cno))
		else:
			try:
				target = str(getdate(raw_date))
			except Exception:
				errors.append(_("{0}: tanggal tidak terbaca ({1})").format(cno, raw_date))
		remark = str(cells[2]).strip() if len(cells) > 2 and cells[2] is not None else None
		rows.append({
			"container": container.name,
			"container_no": cno,
			"target_lift_on": target,
			"remark": remark,
			"is_new": is_new,
		})
	return {"rows": rows, "errors": errors, "unknown": unknown, "created": created}


# --- the plan's endpoint: a Tank Out booking ----------------------------------
# Container condition on the booking line is read off the tank, never assumed: a tank whose
# cleaning is still running leaves as EMPTY DIRTY (and the booking's own Tank Out gate will
# refuse to submit it) — writing EMPTY CLEAN over it would state the opposite of what the
# depot knows.
def _needs_cleaning(container: str) -> bool:
	"""True while the depot still has an unfinished Cleaning Order on this tank.

	This used to read ``Container.cleaning_status``, a hint nothing ever reset: a tank
	cleaned last cycle read "Completed" after it had gated out and come back dirty, so the
	booking line was stamped EMPTY CLEAN on a dirty tank. The open order is the same
	question asked of the document that actually knows.
	"""
	return bool(
		container
		and frappe.db.exists(
			"Cleaning Order",
			{"container": container, "status": ["not in", DONE_CLEANING], "docstatus": ["<", 2]},
		)
	)


@frappe.whitelist()
def make_container_booking(source_name, target_doc=None, containers=None):
	"""Turn the plan into an unsaved Tank Out (Lift On) Container Booking.

	The plan is only the notice — the booking is the priced, submittable document that
	actually lets a tank out, so this hand-off is the plan's endpoint. Everything the plan
	already knows rides along: owner, the source email / reference, the customer's Release
	DO, and per tank its target lift-on date as the booking line's date. Depot and Branch
	are read off the tanks themselves — the booking derives its own depot for a Tank Out,
	and Branch is filled here when the collected tanks all stand in one depot.

	**Customer (Bill To)** rides along too when the plan recorded one: the tank owner is not
	always the party billed for the lift-on, so it is a field of its own on the plan rather
	than assumed to be the Principal. Left blank on the plan it stays blank here — the
	booking still asks for it before it can be saved.

	The **charges** are deliberately NOT filled. The plan has no pricing and no opinion on
	what the lift-on costs, so the services stay the operator's to pick on the booking form,
	which is where the price list and payment mode live.

	Tanks that have already gated out are dropped: a fulfilled row has nothing left to book.
	``containers`` narrows it further to a chosen few — a lift-on notice is routinely
	collected over several visits, so the form asks which tanks this booking is for rather
	than assuming the whole plan leaves at once. Left out, every tank still on the plan goes.

	Nothing is saved here; the operator lands on a fresh draft.
	"""
	from frappe.model.mapper import get_mapped_doc

	# open_mapped_doc does not forward its `args` as keyword arguments — frappe's
	# make_mapped_doc calls method(source_name) and leaves them in frappe.flags.args — so the
	# Desk picker arrives there. The keyword stays for direct callers and tests.
	picked = containers if containers is not None else (frappe.flags.args or {}).get("containers")
	if isinstance(picked, str):
		picked = frappe.parse_json(picked)
	picked = set(picked) if picked else None

	def set_missing(source, target):
		# set_only_once on the booking, so it is fixed here before the first save — and it
		# is what drives the whole outbound pipeline (naming, gates, Order Muat, EIR).
		target.direction = "Tank Out"
		if not target.get("items"):
			frappe.throw(
				_("Tidak ada container yang bisa dibooking — semuanya sudah keluar.")
				if picked is None
				else _("Container yang dipilih sudah keluar semua.")
			)
		# Branch is mandatory on the booking and the plan has no depot of its own to read it
		# off, so it comes from the tanks actually being collected. Only when they agree: a
		# notice spanning two depots has no single answer, and guessing one would file the
		# booking under the wrong branch. Left blank, the operator picks it on the form.
		if not target.branch:
			depots = {
				d for d in frappe.get_all(
					"Container",
					filters={"name": ["in", [r.container for r in target.items if r.container]]},
					pluck="depot",
				) if d
			}
			if len(depots) == 1:
				target.branch = frappe.db.get_value("Depot", depots.pop(), "branch")

	def set_line(source_row, target_row, source_parent):
		# fetch_from fills this on save; set it here so the operator sees which yard each
		# tank is in while the draft is still being completed.
		target_row.depot = frappe.db.get_value("Container", source_row.container, "depot")
		target_row.condition = "EMPTY DIRTY" if _needs_cleaning(source_row.container) else "EMPTY CLEAN"
		target_row.cargo = frappe.db.get_value("Container", source_row.container, "last_cargo")
		# EMKL / truck / driver / RO carry over as typed (same fieldnames, mapped for free).
		# A row that named no transporter falls back to the party being billed — the same
		# default the booking applies on save (``_default_row_shipper``), just visible on
		# the draft instead of appearing after the first save.
		if not target_row.shipper:
			target_row.shipper = source_parent.customer

	return get_mapped_doc(
		"Gate Out Plan",
		source_name,
		{
			"Gate Out Plan": {
				"doctype": "Container Booking",
				"field_map": {
					"name": "gate_out_plan",
					# The customer's own Release DO is the paperwork behind the lift-on; the
					# booking has a DO slot of its own, so it carries rather than re-asks.
					"customer_do": "do_document",
					"customer_do_no": "do_reference",
					# no_copy on both sides, so map_fields skips it — named explicitly to keep
					# the source email attached to the document the customer actually gets.
					"reff_email": "reff_email",
					"notes": "remarks",
				},
			},
			"Gate Out Plan Item": {
				"doctype": "Container Booking Item",
				"field_map": {"target_lift_on": "tanggal_bongkar", "remark": "remarks"},
				"condition": lambda row: (
					row.container and not row.gated_out and (picked is None or row.container in picked)
				),
				"postprocess": set_line,
			},
		},
		target_doc,
		set_missing,
	)
