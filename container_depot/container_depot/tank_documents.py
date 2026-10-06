"""What a Tank Out booking still needs done on each of its tanks — the dossier behind a lift-on.

"Belum: Cleaning, M&R" says a tank is held up but not by WHAT. This names the document, so
it can be opened instead of hunted for, and it answers the question a Tank Out booking is
opened to ask once the truck is on its way: what still has to happen to these tanks?

ONLY what this booking's gate-out asks for (user, 2026-10-06): this visit's Cleaning, M&R and
Leak Check, and this booking's own EIR-Out, Survey and Bon Muat. Not the tank's whole history —
its Tank In booking, its EIR-In and the other Tank Out bookings it sat on are other stories, and
mixed in they buried the few lines the operator came for.

Two different questions are answered side by side and must not be confused:

* ``open``   — unfinished. Everything here is tracked on that basis, statuses as they are.
* ``blocks`` — unfinished AND standing between the tank and the gate: Cleaning, M&R, survey and
  Leak Check, only while "Wajibkan Semua Order" is ON (:mod:`order_policy`) and only until the
  tank has left on this booking. A draft EIR-Out is unfinished paperwork, never a blocker.

Read live, never stored: the answer must not be able to age.
"""

from __future__ import annotations

import frappe
from frappe import _

from container_depot.container_depot.order_policy import enforce_all

# The stay's work, and the statuses at which each is finished with.
_VISIT_WORK = (
	("Cleaning", "Cleaning Order", ("Completed", "Cancelled")),
	("M&R", "Repair Order", ("Completed", "Cancelled", "Rejected")),
	("Leak Check", "Leak Check", ("Completed",)),
)


def _visit(booking: str, container: str):
	"""``(since, until, eir_outs)`` — the stay this booking takes the tank out of.

	The same line as the gate's own check (``container_status.last_departure``): work created
	after the tank last left belongs to this stay. ``until`` is the gate-out stamped with this
	booking's EIR-Out (``gate.mark_gate_out`` sets ``eir_reference``), so a booking whose tank has
	already gone keeps showing that stay instead of the next one's work — and ``since`` is then
	the departure before it.
	"""
	eir_outs = frappe.get_all(
		"Inspection",
		filters={"container": container, "inspection_type": "EIR-Out", "container_booking": booking},
		fields=["name", "status", "docstatus"],
		order_by="creation desc",
	)
	left = {
		"container_no": frappe.db.get_value("Container", container, "container_no") or container,
		"docstatus": ["<", 2],
		"status": ["!=", "Cancelled"],
		"gate_out_timestamp": ["is", "set"],
	}
	until = None
	if eir_outs:
		until = frappe.db.get_value(
			"Gate Entry",
			{**left, "eir_reference": ["in", [e.name for e in eir_outs]]},
			"gate_out_timestamp",
			order_by="gate_out_timestamp desc",
		)
	since = frappe.db.get_value(
		"Gate Entry",
		{**left, "gate_out_timestamp": ["<", until]} if until else left,
		"gate_out_timestamp",
		order_by="gate_out_timestamp desc",
	)
	return since, until, eir_outs


def _line(kind, doctype, name, status, *, done, cancelled, blocks=False):
	is_open = not cancelled and not done
	return {
		"kind": kind,
		"doctype": doctype,
		"name": name,
		"status": _("Cancelled") if cancelled else status,
		"blocks": blocks and is_open,
		"open": is_open,
		"done": done and not cancelled,
		"cancelled": cancelled,
	}


def documents_for(booking: str, container: str) -> list:
	"""This booking's dossier for one tank, newest first per kind, filtered to what the caller
	may read — counted on the SERVER: a role that cannot read Cleaning Orders must not be told
	how many of them are open either."""
	since, until, eir_outs = _visit(booking, container)
	holds = enforce_all() and not until
	window = [["container", "=", container]]
	if since:
		window.append(["creation", ">", since])
	if until:
		window.append(["creation", "<=", until])

	out = []
	for kind, doctype, done in _VISIT_WORK:
		if not frappe.has_permission(doctype, "read"):
			continue
		for r in frappe.get_all(
			doctype, filters=window, fields=["name", "status", "docstatus"], order_by="creation desc"
		):
			cancelled = r.docstatus == 2
			out.append(_line(
				kind, doctype, r.name, r.status,
				done=r.status in done, cancelled=cancelled, blocks=holds,
			))

	if frappe.has_permission("Inspection", "read"):
		# A record of the tank leaving, not work in front of it: never blocks.
		for r in eir_outs:
			out.append(_line(
				"EIR-Out", "Inspection", r.name, r.status,
				done=r.status == "Submitted", cancelled=r.docstatus == 2,
			))

	if frappe.has_permission("Survey Order", "read"):
		# A Survey Order covers the whole pickup, so the tank's line reads ITS row
		# (Waiting Lowering → Lowered → Survey Done). ON, the EIR-Out waits for it
		# (``Inspection.before_submit``), hence ``blocks``.
		for r in frappe.db.sql(
			"""
			select p.name, p.docstatus, r.status
			  from `tabSurvey Order Tank` r
			  join `tabSurvey Order` p on p.name = r.parent
			 where p.booking = %s and r.container = %s
			   and r.parenttype = 'Survey Order' and r.parentfield = 'tanks'
			 order by p.creation desc
			""",
			(booking, container),
			as_dict=True,
		):
			out.append(_line(
				"Survey", "Survey Order", r.name, r.status,
				done=r.status == "Survey Done",
				cancelled=r.docstatus == 2 or r.status == "Cancelled",
				blocks=holds,
			))
	return out


# A booking's bons, one table per direction: make_order picks the bon from the code's
# direction, so a booking's bons always run its own way — Bongkar in, Muat out.
_BONS = (
	("Bon Bongkar", "Order Bongkar", "Container Booking Item"),
	("Bon Muat", "Order Muat", "Order Container Item"),
)


def booking_bons(booking: str | None, container: str) -> list:
	"""The bons ``booking`` raised for this tank, newest first — same line shape as an order.

	Never ``blocks``: the bon is the way through the gate, not something in front of it.
	Done at ``Completed`` — the Bongkar once every tank has its EIR-In, the Muat at gate-out."""
	out = []
	if not booking or not container:
		return out
	for kind, doctype, child in _BONS:
		if not frappe.has_permission(doctype, "read"):
			continue
		for r in frappe.db.sql(
			f"""
			select p.name, p.docstatus, p.order_status as status, p.creation
			  from `tab{child}` r
			  join `tab{doctype}` p on p.name = r.parent
			 where p.booking = %s and r.container = %s and r.parenttype = %s and r.parentfield = 'containers'
			 order by p.creation desc
			""",
			(booking, container, doctype),
			as_dict=True,
		):
			cancelled = r.docstatus == 2
			done = not cancelled and r.status == "Completed"
			out.append({
				"kind": kind,
				"doctype": doctype,
				"name": r.name,
				# A bon brought back by Kembalikan ke Draft keeps order_status Issued.
				"status": _("Cancelled") if cancelled else "Draft" if r.docstatus == 0 else r.status,
				"date": r.creation,
				"blocks": False,
				"open": not cancelled and not done,
				"done": done,
				"cancelled": cancelled,
			})
	return out


def dossier(rows) -> list:
	"""One entry per listed tank: its live status, its documents, and the two counts.

	``rows``: iterable of dicts carrying ``container`` and the ``booking`` (+ optionally
	``container_no`` and a target date), in the order they should be shown.
	"""
	out = []
	for r in rows:
		container = r.get("container")
		if not container:
			continue
		orders = documents_for(r["booking"], container) + booking_bons(r["booking"], container)
		out.append({
			"container": container,
			"container_no": r.get("container_no") or container,
			# Read here rather than off the stored row: this panel is the live answer, and a
			# document's own copy is only as fresh as its last save.
			"status": frappe.db.get_value("Container", container, "status"),
			"target_lift_on": str(r["target_lift_on"]) if r.get("target_lift_on") else None,
			"open_count": sum(1 for o in orders if o["open"]),
			"blocking_count": sum(1 for o in orders if o["blocks"]),
			"orders": orders,
		})
	return out
