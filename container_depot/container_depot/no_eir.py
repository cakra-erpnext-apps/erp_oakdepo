"""LADEN tanks the user chose not to inspect — "Pakai EIR" switched off (user, 2026-10-07).

A booking line whose condition is LADEN carries ``use_eir`` (default on). Switched off, the
tank is handled with no EIR at all, and the bon is the whole visit:

* **Tank In** — no EIR-In and no Leak Check. Submitting the Order Bongkar puts the tank in
  the yard, ``Available`` straight away; its Tanggal Bongkar is the day it came in
  (``visit_dates``). An Order Bongkar whose every tank is like this is Completed at issue.
* **Tank Out** — no EIR-Out and no survey row. Submitting the Order Muat IS the gate-out
  (``gate.mark_gate_out(no_eir=True)``), dated by its Tanggal Muat. Kembalikan ke Draft or a
  void brings the tank back (:func:`reverse_departures`).

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


def depart(bon) -> None:
	"""Order Muat submit: its no-EIR tanks leave now, dated by Tanggal Muat."""
	from container_depot.container_depot.gate import mark_gate_out

	for container in bon_no_eir(bon):
		mark_gate_out(container=container, no_eir=True, order_muat=bon.name)


def reverse_departures(bon) -> list:
	"""An Order Muat back to draft, or voided: its submit sent the no-EIR tanks out, so they come
	back — Gate Entry reopened, tank in the yard again, Tanggal Keluar cleared."""
	from container_depot import storage_charge
	from container_depot.container_depot import lift_on
	from container_depot.container_depot.container_activity import log_container_activity
	from container_depot.container_depot.container_status import AVAILABLE, recompute_availability
	from container_depot.container_depot.gate import reopen_gate_entry

	back = []
	for container in bon_no_eir(bon):
		tank = frappe.db.get_value("Container", container, ["status", "container_no", "last_order_muat"], as_dict=True)
		if not tank or tank.status != "Gate_Out":
			continue
		ge = frappe.db.get_value(
			"Gate Entry",
			{"container_no": tank.container_no, "order_muat": bon.name, "status": "Gate_Out_Completed"},
			["name", "gate_in_timestamp"], as_dict=True,
		)
		if not ge:
			continue  # it left on another bon since; that departure is not this bon's to undo
		reopen_gate_entry(ge)
		frappe.flags.in_status_automation = True
		try:
			doc = frappe.get_doc("Container", container)
			doc.status = AVAILABLE
			doc.out_date = None
			doc.save(ignore_permissions=True)
		finally:
			frappe.flags.in_status_automation = False
		recompute_availability(container)
		log_container_activity(
			container, "Status Change",
			reference_doctype=bon.doctype, reference_name=bon.name,
			from_status="Gate_Out", to_status=frappe.db.get_value("Container", container, "status"),
			summary=_("{0} dibatalkan — tank tanpa EIR kembali ke depo").format(bon.name),
		)
		lift_on.refresh_bookings_for_container(container)
		storage_charge.sync(container, tank.container_no)
		back.append(container)
	return back
