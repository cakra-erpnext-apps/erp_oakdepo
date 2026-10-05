"""LADEN tanks: no EIR, no Leak Check, no survey. The bon is the visit (user, 2026-10-05).

A tank that travels full cannot be inspected inside, so no order is raised for it:

* **Tank In** — the bon's own date (Tanggal Bongkar) is the day it came in, which is also where
  storage starts. With nothing open on it, the tank is ``Available`` straight away.
* **Tank Out** — submitting the bon IS the departure (``gate.mark_gate_out``), dated by Tgl.
  Muat. Kembalikan ke Draft brings the tank back (:func:`reverse_departures`).

Both dates stay editable after submit; the tank's dates follow (:func:`restamp`).

Read per tank and per direction off the booking line's ``condition``: one bon may carry a laden
tank beside an empty one, and a tank may come in laden and leave empty, or the other way round.
"""

from __future__ import annotations

import datetime

import frappe
from frappe.utils import get_datetime, getdate, now_datetime

LADEN = "LADEN"


def laden_containers(parent: str | None, parenttype: str = "Container Booking") -> set:
	"""Tanks marked LADEN on a booking, or on a Tank In bon (its rows ARE booking lines)."""
	if not parent:
		return set()
	return {
		c for c in frappe.get_all(
			"Container Booking Item",
			filters={"parent": parent, "parenttype": parenttype, "condition": LADEN},
			pluck="container",
		) if c
	}


def bon_laden(bon) -> set:
	"""The LADEN tanks on a bon. An Order Muat row carries no condition, so a Tank Out bon reads
	its booking's lines."""
	if bon.doctype == "Order Bongkar":
		return laden_containers(bon.name, "Order Bongkar")
	mine = {r.container for r in bon.get("containers") or [] if r.container}
	return laden_containers(bon.get("booking")) & mine


def bon_time(day, at=None) -> datetime.datetime:
	"""The bon's own date at the clock time of ``at`` (default now): the date is what the
	operator set, the time keeps same-day moves in order."""
	at = get_datetime(at) if at else now_datetime()
	return datetime.datetime.combine(getdate(day), at.time()) if day else at


def depart(bon) -> None:
	"""Order Muat submit: its LADEN tanks leave now, dated by Tgl. Muat."""
	from container_depot.container_depot.gate import mark_gate_out

	when = bon_time(bon.get("tanggal_muat"))
	for container in bon_laden(bon):
		mark_gate_out(container=container, laden_at=when)


def _departure(container: str, bon: str):
	"""The closed Gate Entry of a LADEN tank that left on ``bon``, or None. Only while the tank is
	still out and this bon is its latest Order Muat — after a return the visit is history."""
	from container_depot.container_depot.gate import _latest_order_muat

	tank = frappe.db.get_value("Container", container, ["status", "container_no"], as_dict=True)
	if not tank or tank.status != "Gate_Out" or _latest_order_muat(container, tank.container_no) != bon:
		return None
	rows = frappe.get_all(
		"Gate Entry",
		filters={"container_no": tank.container_no, "status": "Gate_Out_Completed"},
		fields=["name", "container_no", "gate_in_timestamp", "gate_out_timestamp"],
		order_by="gate_out_timestamp desc", limit=1,
	)
	return rows[0] if rows else None


def reverse_departures(bon) -> list:
	"""Kembalikan ke Draft on an Order Muat: its submit sent the LADEN tanks out, so they come
	back — Gate Entry reopened, tank present again, the booking's % Keluar recounted."""
	from container_depot.container_depot import lift_on
	from container_depot.container_depot.container_activity import log_container_activity
	from container_depot.container_depot.container_status import AVAILABLE, recompute_availability
	from container_depot.container_depot.gate import reopen_gate_entry

	back = []
	for container in bon_laden(bon):
		ge = _departure(container, bon.name)
		if not ge:
			continue
		reopen_gate_entry(ge)
		frappe.flags.in_status_automation = True
		try:
			tank = frappe.get_doc("Container", container)
			tank.status = AVAILABLE
			tank.save(ignore_permissions=True)
		finally:
			frappe.flags.in_status_automation = False
		recompute_availability(container)
		log_container_activity(
			container, "Status Change",
			reference_doctype=bon.doctype, reference_name=bon.name,
			from_status="Gate_Out", to_status=frappe.db.get_value("Container", container, "status"),
			summary=f"{bon.name} dikembalikan ke Draft — gate-out tank laden dibatalkan",
		)
		lift_on.refresh_bookings_for_container(container)
		back.append(container)
	return back


def restamp(bon) -> None:
	"""Tanggal Bongkar / Tgl. Muat corrected after submit: the LADEN tanks' arrival / departure
	follows — Gate Entry, its timeline row, the Container date, the storage ledger."""
	from container_depot import storage_charge

	for container in bon_laden(bon):
		if bon.doctype == "Order Bongkar":
			cno = frappe.db.get_value("Container", container, "container_no")
			ge = frappe.db.get_value(
				"Gate Entry",
				{"order_doctype": "Order Bongkar", "order_ref": bon.name, "container_no": cno, "status": ["!=", "Cancelled"]},
				["name", "gate_in_timestamp"], as_dict=True,
			)
			field, activity, own = "gate_in_timestamp", "Gate In", "eir_in_date"
			# The tank's arrival date is this bon's only while this bon is its latest arrival.
			mine = frappe.db.get_value("Container", container, "last_order_bongkar") == bon.name
			when = bon_time(bon.get("tanggal_bongkar"), bon.get("gate_in_time"))
		else:
			ge = _departure(container, bon.name)
			field, activity, own, mine = "gate_out_timestamp", "Gate Out", "eir_out_date", True
			when = ge and bon_time(bon.get("tanggal_muat"), ge.gate_out_timestamp)
		if not ge or not ge.get(field) or get_datetime(ge.get(field)) == when:
			continue
		frappe.db.set_value("Gate Entry", ge.name, field, when)
		for name in frappe.get_all(
			"Container Activity",
			filters={"reference_doctype": "Gate Entry", "reference_name": ge.name, "activity_type": activity},
			pluck="name",
		):
			frappe.db.set_value("Container Activity", name, "activity_time", when, update_modified=False)
		if mine:
			frappe.db.set_value("Container", container, own, when, update_modified=False)
		storage_charge.sync(container)
