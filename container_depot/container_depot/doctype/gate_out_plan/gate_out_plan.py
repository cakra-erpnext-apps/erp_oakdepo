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

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

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
		self._assert_containers_unique()
		self._roll_up()

	def _fill_rows(self):
		"""Per row: mirror the container number, compute gate-out readiness, and flag the
		tanks that have already left."""
		for row in self.containers or []:
			if not row.container:
				row.container_no = row.readiness = None
				row.is_ready = row.gated_out = 0
				continue
			cn, status = frappe.db.get_value(
				"Container", row.container, ["container_no", "status"]
			) or (None, None)
			row.container_no = cn
			row.gated_out = 1 if status == GATE_OUT_STATUS else 0
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
				"blocks": blocks,
				"done": not blocks,
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
		out.append({
			"kind": r.inspection_type or "EIR",
			"doctype": "Inspection",
			"name": r.name,
			"status": _("Cancelled") if cancelled else r.status,
			"blocks": False,
			# Only a submitted EIR is a finished record; a draft one is still being written.
			"done": not cancelled and r.status == "Submitted",
		})
	return out


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
		fields=["name", "container"],
	)
	listed = [r for r in rows if r.container]
	if not listed:
		frappe.db.set_value("Gate Out Plan", plan, "per_fulfilled", 0, update_modified=False)
		return False

	gone = set(
		frappe.get_all(
			"Container",
			filters={"name": ["in", [r.container for r in listed]], "status": GATE_OUT_STATUS},
			pluck="name",
		)
	)
	for r in listed:
		frappe.db.set_value(
			"Gate Out Plan Item", r.name,
			"gated_out", 1 if r.container in gone else 0,
			update_modified=False,
		)

	per = flt(len(gone) * 100.0 / len(listed), 2)
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
	"""Per listed tank, the Cleaning / M&R orders behind its Kesiapan, plus its EIRs.

	The "Belum: Cleaning, M&R" column says a tank is held up but not by WHAT — this names the
	orders so an operator can open the one that is blocking a lift-on instead of hunting for
	it. The EIRs ride along as context (see :func:`_tank_eirs`) — they never change Kesiapan.
	Read live, never stored: the answer must not be able to age.
	"""
	frappe.has_permission("Gate Out Plan", "read", doc=gate_out_plan, throw=True)
	readable = {
		dt
		for dt in ("Cleaning Order", "Repair Order", "Inspection")
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
		out.append({
			"container": r.container,
			"container_no": r.container_no or r.container,
			"target_lift_on": str(r.target_lift_on) if r.target_lift_on else None,
			"orders": [
				o
				for o in _tank_orders(r.container) + _tank_eirs(r.container)
				if o["doctype"] in readable
			],
		})
	return out
