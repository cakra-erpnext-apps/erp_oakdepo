"""LADEN tanks the user chose not to inspect — "Pakai EIR" switched off (user, 2026-10-07).

A booking line whose condition is LADEN carries ``use_eir`` (default on). Switched off, the
tank is handled with no EIR at all, and the bon is the whole visit:

* **Tank In** — no EIR-In and no Leak Check. Submitting the Order Bongkar puts the tank in
  the yard, ``Available`` straight away; its Tanggal Bongkar is the day it came in
  (``visit_dates``). An Order Bongkar whose every tank is like this is Completed at issue.
* **Tank Out** — no EIR-Out, no survey row and no Leak Check. Its Order Muat submit is the
  gate-out like every other tank's (``gate.depart_bon``), dated by its Tanggal Muat.

Every other tank (EMPTY, or LADEN with the switch on) keeps the normal flow. Decided per tank
and per direction, so one bon may mix both. The switch is locked once the line is on a bon:
by then the EIR it decides about has been raised or skipped.
"""

from __future__ import annotations

import frappe
from frappe import _

LADEN = "LADEN"


def is_no_eir(line) -> bool:
	return line.get("condition") == LADEN and not line.get("use_eir")


def no_eir_containers(parent: str | None, parenttype: str = "Container Booking") -> set:
	"""Tanks on a booking — or on a Tank In bon, whose rows ARE booking lines — that take no EIR."""
	if not parent:
		return set()
	return {
		c for c in frappe.get_all(
			"Container Booking Item",
			filters={"parent": parent, "parenttype": parenttype, "condition": LADEN, "use_eir": 0},
			pluck="container",
		) if c
	}


def bon_no_eir(bon) -> set:
	"""The no-EIR tanks on a bon. An Order Muat row carries no condition, so a Tank Out bon reads
	its booking's lines."""
	if bon.doctype == "Order Bongkar":
		return no_eir_containers(bon.name, "Order Bongkar")
	mine = {r.container for r in bon.get("containers") or [] if r.container}
	return no_eir_containers(bon.get("booking")) & mine


def normalise(booking) -> None:
	"""``use_eir`` means something only on a LADEN line; every other line always takes an EIR."""
	for line in booking.get("items") or []:
		if line.get("condition") != LADEN:
			line.use_eir = 1


def assert_switch_locked(booking) -> None:
	"""Refuse flipping "Pakai EIR" on a line that already has a bon."""
	from container_depot.container_depot.order_generation import live_bon_row

	before = booking.get_doc_before_save()
	old = {r.name: r for r in (before.items if before else [])}
	for line in booking.get("items") or []:
		was = old.get(line.name)
		if not was or int(was.get("use_eir") or 0) == int(line.get("use_eir") or 0):
			continue
		bon = live_bon_row(line.get("booking_code"))
		if bon:
			frappe.throw(
				_("Tank {0} sudah ada di bon {1} — pilihan Pakai EIR tidak bisa diubah lagi.").format(
					line.get("container_no") or line.get("container"), bon.bon
				),
				title=_("Pakai EIR terkunci"),
			)


def switch_changed(booking) -> bool:
	before = booking.get_doc_before_save()
	old = {r.name: int(r.get("use_eir") or 0) for r in (before.items if before else [])}
	return any(old.get(r.name, 1) != int(r.get("use_eir") or 0) for r in booking.get("items") or [])
