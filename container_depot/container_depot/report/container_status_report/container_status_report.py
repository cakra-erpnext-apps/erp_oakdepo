"""Container Status Report — one row per tank, with every order attached to it.

The status columns alone stopped answering the operator's real question. Container
``status`` is presence-based now (Booked / In_Depot / Available / Gate_Out): it says
where the tank is, never what is being done to it. That detail lives on the orders, so
a "status report" that names no orders leaves the reader to open ten list views and
match container numbers by eye.

Every order type that can name a container is therefore a column here:

* raised directly on the tank — EIR-In, EIR-Out, Cleaning, M&R, Survey Posisi;
* raised on a document that LISTS the tank — Container Booking, Order Bongkar, Order
  Muat (each via its container child table). The outbound Container Booking is where a
  planned lift-on now lives; Gate Out Plan was a separate notice document, removed in
  v0_87.

Each cell holds the most recent non-cancelled document of that type, as a Link, so the
row is a jumping-off point rather than a summary to be re-searched.

"Open work" is separate from "related orders" and is answered by ``open_orders`` /
``readiness``, both derived from :func:`container_status.container_open_orders` — the
same function that decides whether the tank is Available. The report cannot claim a
tank is ready while the gate refuses to let it out.

One query per order type, never one per container: the row count is the container
count, and a per-row lookup would make this report unusable at depot scale.
"""

from __future__ import annotations

import frappe

from container_depot.container_depot.container_status import (
	DONE_CLEANING,
	DONE_REPAIR,
	readiness_label,
)


def execute(filters=None):
	filters = filters or {}
	containers = _containers(filters)
	names = [c.name for c in containers]
	related = _related_orders(names)
	open_work = _open_work(names)

	rows = []
	for c in containers:
		work = open_work.get(c.name, [])
		if filters.get("with_open_work") and not work:
			continue
		row = {
			"container_no": c.name,
			"principal": c.principal,
			"container_type": c.container_type,
			"equipment_type": c.equipment_type,
			"size": c.size,
			"status": c.status,
			"readiness": readiness_label(c.status, work),
			"open_orders": len(work),
			"target_lift_on": c.target_lift_on,
		}
		for key, _label, _doctype in _ORDER_COLUMNS:
			row[key] = related.get(key, {}).get(c.name)
		rows.append(row)
	return _columns(), rows


# (column fieldname, column label, linked doctype) — also drives the per-type queries
# below, so a column can never exist without a query filling it, or the reverse.
_ORDER_COLUMNS = (
	("booking", "Booking", "Container Booking"),
	("order_bongkar", "Order Bongkar", "Order Bongkar"),
	("eir_in", "EIR-In", "Inspection"),
	("eir_out", "EIR-Out", "Inspection"),
	("cleaning_order", "Cleaning Order", "Cleaning Order"),
	("repair_order", "M&R", "Repair Order"),
	("position_survey", "Survey Posisi", "Container Position Survey"),
	("order_muat", "Order Muat", "Order Muat"),
)


def _columns():
	cols = [
		{"fieldname": "container_no", "label": "Container", "fieldtype": "Link",
		 "options": "Container", "width": 140},
		{"fieldname": "principal", "label": "Principal", "fieldtype": "Link",
		 "options": "Customer", "width": 150},
		{"fieldname": "container_type", "label": "Type", "fieldtype": "Data", "width": 100},
		{"fieldname": "equipment_type", "label": "Equip", "fieldtype": "Data", "width": 70},
		{"fieldname": "size", "label": "Size", "fieldtype": "Data", "width": 70},
		{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 100},
		{"fieldname": "readiness", "label": "Kesiapan", "fieldtype": "Data", "width": 170},
		{"fieldname": "open_orders", "label": "Order Terbuka", "fieldtype": "Int", "width": 110},
	]
	cols += [
		{"fieldname": key, "label": label, "fieldtype": "Link", "options": doctype, "width": 150}
		for key, label, doctype in _ORDER_COLUMNS
	]
	cols += [
		{"fieldname": "target_lift_on", "label": "Target Lift-On", "fieldtype": "Date", "width": 110},
	]
	return cols


def _containers(filters):
	query = {}
	for field in ("status", "container_type", "principal", "depot"):
		if filters.get(field):
			query[field] = filters[field]
	# A retired tank is master data that is no longer in play; it is off by default but
	# reachable, because "why is this tank not in the report" needs an answer too.
	if not filters.get("include_retired"):
		query["is_active"] = 1
	return frappe.get_all(
		"Container",
		filters=query,
		fields=[
			"name", "principal", "container_type", "equipment_type", "size", "status",
			"target_lift_on",
		],
		order_by="principal asc, name asc",
		limit_page_length=0,
	)


def _open_work(names: list[str]) -> dict[str, list[str]]:
	"""``{container: [label, ...]}`` for work that still holds the tank.

	Mirrors :func:`container_status.container_open_orders` exactly — a draft EIR-In plus
	any unfinished Cleaning / M&R — but resolved for the whole result set
	in four queries instead of four per row.
	"""
	if not names:
		return {}
	out: dict[str, list[str]] = {}

	def add(container, label):
		if container:
			out.setdefault(container, []).append(label)

	for row in frappe.get_all(
		"Inspection",
		filters={"container": ["in", names], "inspection_type": "EIR-In", "docstatus": 0},
		fields=["container"],
		limit_page_length=0,
	):
		add(row.container, "EIR-In")
	for doctype, done, label in (
		("Cleaning Order", DONE_CLEANING, "Cleaning"),
		("Repair Order", DONE_REPAIR, "M&R"),
	):
		for row in frappe.get_all(
			doctype,
			filters={
				"container": ["in", names],
				"status": ["not in", list(done)],
				"docstatus": ["<", 2],
			},
			fields=["container"],
			limit_page_length=0,
		):
			add(row.container, label)
	return out


def _related_orders(names: list[str]) -> dict[str, dict[str, str]]:
	"""``{column: {container: document}}`` — the newest non-cancelled document per type.

	Newest wins because a tank cycles through the depot repeatedly: its third booking is
	the one an operator is asking about, not its first. Cancelled documents are dropped
	(they name work that never happened); everything else is kept, finished or not, since
	the question this column answers is "which paperwork touched this tank", and
	``open_orders`` already answers "what is still outstanding".
	"""
	if not names:
		return {}
	return {
		# Raised directly on the container.
		"eir_in": _direct("Inspection", names, {"inspection_type": "EIR-In"}),
		"eir_out": _direct("Inspection", names, {"inspection_type": "EIR-Out"}),
		"cleaning_order": _direct("Cleaning Order", names),
		"repair_order": _direct("Repair Order", names, {"status": ["!=", "Cancelled"]}),
		"position_survey": _direct("Container Position Survey", names),
		# Raised on a parent document that lists the container.
		"booking": _via_child(
			"Container Booking Item", "Container Booking", names,
			"p.booking_status != 'Cancelled'",
		),
		# Order Bongkar reuses Container Booking Item, Order Muat uses Order Container
		# Item — the child doctype differs per parent, and Container Booking Item is
		# shared with the booking itself. Hence the parenttype pin in _via_child.
		"order_bongkar": _via_child("Container Booking Item", "Order Bongkar", names),
		"order_muat": _via_child("Order Container Item", "Order Muat", names),
	}


def _direct(doctype: str, names: list[str], extra: dict | None = None) -> dict[str, str]:
	"""Newest non-cancelled ``doctype`` per container, for doctypes with a Container link."""
	rows = frappe.get_all(
		doctype,
		filters={"container": ["in", names], "docstatus": ["<", 2], **(extra or {})},
		fields=["container", "name"],
		order_by="creation asc",  # ascending + overwrite = newest wins, in one pass
		limit_page_length=0,
	)
	return {r.container: r.name for r in rows if r.container}


def _via_child(child: str, parent: str, names: list[str], parent_where: str = "") -> dict[str, str]:
	"""Newest non-cancelled ``parent`` per container, for doctypes that list containers.

	Raw SQL because the link is a join: ``frappe.get_all`` cannot filter a child table on
	its parent's own fields. ``parenttype`` is pinned — Order Bongkar and Order Muat share
	one child doctype, so without it each would report the other's documents.
	"""
	clause = f" AND {parent_where}" if parent_where else ""
	rows = frappe.db.sql(
		f"""
		SELECT ci.container AS container, p.name AS name
		FROM `tab{child}` ci
		JOIN `tab{parent}` p ON p.name = ci.parent
		WHERE ci.parenttype = %(parent)s
		  AND ci.container IN %(names)s
		  AND p.docstatus < 2{clause}
		ORDER BY p.creation ASC
		""",
		{"parent": parent, "names": tuple(names)},
		as_dict=True,
	)
	return {r.container: r.name for r in rows if r.container}
