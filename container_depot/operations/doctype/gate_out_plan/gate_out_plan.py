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
from frappe.model.document import Document
from frappe.utils import getdate

# Only an Open plan drives priority; closing it releases the container stamps.
ACTIVE_STATUS = "Open"

# A Cleaning / Repair order in one of these no longer blocks gate-out (work is finished).
_CLEANING_DONE = ("Completed", "Cancelled")
_MR_DONE = ("Completed", "Cancelled", "Rejected")


class GateOutPlan(Document):
	def validate(self):
		self._fill_rows()
		self._roll_up()

	def _fill_rows(self):
		"""Per row: mirror the container number and compute gate-out readiness."""
		for row in self.containers or []:
			if not row.container:
				row.container_no = row.readiness = None
				row.is_ready = 0
				continue
			row.container_no = frappe.db.get_value("Container", row.container, "container_no")
			pending = _pending_work(row.container)
			row.is_ready = 0 if pending else 1
			row.readiness = "Siap" if not pending else "Belum: " + ", ".join(pending)

	def _roll_up(self):
		"""Header summaries for the list view: containers, X/Y ready, nearest lift-on date."""
		rows = [r for r in (self.containers or []) if r.container]
		self.container_summary = ", ".join(r.container_no or r.container for r in rows) or None
		if rows:
			ready = sum(1 for r in rows if r.is_ready)
			self.readiness_summary = f"{ready}/{len(rows)} siap"
		else:
			self.readiness_summary = None
		dates = [getdate(r.target_lift_on) for r in rows if r.target_lift_on]
		self.next_lift_on = min(dates) if dates else None

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


def _pending_work(container: str) -> list:
	"""Open work that must finish before this tank can gate out (readiness = its blockers)."""
	pending = []
	if frappe.db.exists(
		"Cleaning Order",
		{"container": container, "status": ["not in", _CLEANING_DONE], "docstatus": ["<", 2]},
	):
		pending.append("Cleaning")
	if frappe.db.exists(
		"Repair Order", {"container": container, "status": ["not in", _MR_DONE]}
	):
		pending.append("M&R")
	return pending


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
