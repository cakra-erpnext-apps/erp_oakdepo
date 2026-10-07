"""Container Inventory — one row per tank: where it is, and every order attached to it.

Merged report (2026-09-18). It used to be two menus over the same table: "Container
Inventory" (stage / in-date / age) and "Container Status Report" (the order columns).
One row per Container, one source, one set of filters — two menus meant two answers to
"which tanks are in the depo", and they did not agree: the old inventory report never
filtered ``is_active``, so retired tanks counted as stock.

Container ``status`` is presence-based (Booked / In_Depot / Available / Gate_Out): it says
where the tank is, never what is being done to it. That detail lives on the orders, so
every order type that can name a container is a column here:

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

Defaults to tanks physically in the depo (``in_depo_only``, i.e. ``inventory_stage`` in
:data:`IN_DEPO_STAGES`); switch it off to include reserved (Pre-Arrival) and gated-out
tanks. ``inventory_stage`` itself is the derived bucket kept in step by
``Container.before_save``.

One query per order type, never one per container: the row count is the container
count, and a per-row lookup would make this report unusable at depot scale.

STOCK REPORT LAYOUT (user, 2026-10-02)
--------------------------------------
The columns follow the principals' "Tank Stock Report" sheet the yard already keeps, in its
order and under its headings — Tank Number, Test / Next Test, Ex-Cargo, Equip Type, Remarks,
In Depot, Depot, Cleaning Start / End, Start Repair, Available Date, Survey Date, Depot Out,
Export Ref, Shipper, Seal — so the report reads like the sheet it replaces. Every date is
from the tank's CURRENT visit (on or after its In Depot date): a cleaning from last year's
visit is not this visit's cleaning. The shared "Cari" box and the date range on any of those
date columns come from :mod:`container_depot.container_depot.report_kit`.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_months, date_diff, getdate, today

from container_depot.container_depot import report_kit
from container_depot.container_depot.container_status import (
	DONE_CLEANING,
	DONE_REPAIR,
	PRESENT,
	readiness_label,
)
from container_depot.container_depot.order_policy import enforce_all
from container_depot.customer_scope import get_user_customers
from container_depot.state_machine import IN_DEPO_STAGES


# A tank is retested every 2.5 years, alternating the intermediate (2,5Y) and full (5Y)
# test — either way the next one is due 30 months after the last.
TEST_INTERVAL_MONTHS = 30


def execute(filters=None):
	filters = filters or {}
	containers = _containers(filters)
	names = [c.name for c in containers]
	related = _related_orders(names)
	open_work = _open_work(names)
	visit = _visit_facts(names)

	rows = []
	now = getdate(today())
	for c in containers:
		work = open_work.get(c.name, [])
		if filters.get("with_open_work") and not work:
			continue
		since = getdate(c.in_date) if c.in_date else None
		v = visit.get(c.name, {})

		def this_visit(key):
			"""The fact only if it happened on/after this visit's In Depot date."""
			when = getdate(v[key]) if v.get(key) else None
			return when if when and (not since or when >= since) else None

		eir = v.get("eir_in") or {}
		# The outbound job: the booking the tank is pointed at right now, else the newest Tank
		# Out booking of this visit. Not merely the newest — that may be a past visit's.
		jobs = v.get("out_jobs") or {}
		newest = jobs.get(v.get("out_newest")) or {}
		out_job = jobs.get(c.lift_on_booking) or (
			newest if newest and (not since or getdate(newest["creation"]) >= since) else {}
		)
		out_date = getdate(c.out_date) if c.out_date else None
		row = {
			"principal": c.principal,
			"container_no": c.name,
			"last_test_date": c.last_test_date,
			"next_test_date": add_months(c.last_test_date, TEST_INTERVAL_MONTHS) if c.last_test_date else None,
			# The sheet's Ex-Cargo: the cargo, or how the tank came in when it carried none.
			"last_cargo": c.last_cargo or (eir.get("tank_status") or "").upper() or None,
			"equipment_type": c.equipment_type,
			"remarks": eir.get("remarks"),
			"in_date": since,
			"depot": c.depot,
			"cleaning_start": this_visit("cleaning_start"),
			"cleaning_end": this_visit("cleaning_end"),
			"repair_start": this_visit("repair_start"),
			"available_date": this_visit("available_date"),
			"survey_date": this_visit("survey_date"),
			"out_date": out_date if out_date and (not since or out_date >= since) else None,
			"export_ref": out_job.get("reff_doc"),
			"shipper": out_job.get("shipper"),
			"seal_no": v.get("seal_no") if this_visit("eir_out_on") else None,
			# Switch OFF: only the mandatory draft EIR-In holds a tank (order_policy).
			"readiness": readiness_label(c.status, work if enforce_all() else [w for w in work if w == "EIR-In"]),
			"inventory_stage": c.inventory_stage,
			"status": c.status,
			"open_orders": len(work),
			# Age only makes sense for a tank still in the depo with a recorded gate-in.
			"days_in_depo": _age(now, c),
			"target_lift_on": c.target_lift_on,
			"container_type": c.container_type,
			"size": c.size,
		}
		for key, _label, _doctype in _ORDER_COLUMNS:
			row[key] = related.get(key, {}).get(c.name)
		rows.append(row)
	return report_kit.finish(_columns(), rows, filters, default="in_date")


# (column fieldname, column label, linked doctype) — also drives the per-type queries
# below, so a column can never exist without a query filling it, or the reverse.
_ORDER_COLUMNS = (
	("booking", "Booking", "Container Booking"),
	("order_bongkar", "Order Bongkar", "Order Bongkar"),
	("eir_in", "EIR-In", "Inspection"),
	("eir_out", "EIR-Out", "Inspection"),
	("cleaning_order", "Cleaning Order", "Cleaning Order"),
	("repair_order", "M&R", "Repair Order"),
	("survey_order", "Jadwal Survey", "Survey Order"),
	("order_muat", "Order Muat", "Order Muat"),
)


def _columns():
	"""In the order and under the headings of the yard's Tank Stock Report sheet."""
	def col(fieldname, label, fieldtype="Data", width=110, options=None):
		c = {"fieldname": fieldname, "label": label, "fieldtype": fieldtype, "width": width}
		if options:
			c["options"] = options
		return c

	cols = [
		col("principal", "Principal", "Link", 140, "Customer"),
		col("container_no", "Tank Number", "Link", 130, "Container"),
		col("last_test_date", "Test", "Date", 95),
		col("next_test_date", "Next Test", "Date", 95),
		col("last_cargo", "Ex-Cargo", width=130),
		col("equipment_type", "Equip Type", width=80),
		col("remarks", "Remarks", width=220),
		col("in_date", "In Depot", "Date", 95),
		col("depot", "Depot", "Link", 75, "Depot"),
		col("cleaning_start", "Cleaning Start", "Date", 100),
		col("cleaning_end", "Cleaning End", "Date", 100),
		col("repair_start", "Start Repair", "Date", 100),
		col("available_date", "Available Date", "Date", 105),
		col("survey_date", "Survey Date", "Date", 100),
		col("out_date", "Depot Out", "Date", 95),
		col("export_ref", "Export Ref", width=120),
		col("shipper", "Shipper", "Link", 130, "Customer"),
		col("seal_no", "Seal", width=120),
		col("readiness", "Kesiapan", width=150),
		col("inventory_stage", "Stage", width=90),
		col("status", "Status", width=90),
		col("open_orders", "Order Terbuka", "Int", 95),
		col("days_in_depo", "Days In Depo", "Int", 95),
		col("target_lift_on", "Plan Pickup Date", "Date", 110),
		col("container_type", "Type", width=90),
		col("size", "Size", width=60),
	]
	cols += [col(key, label, "Link", 140, doctype) for key, label, doctype in _ORDER_COLUMNS]
	return cols


def _age(now, c):
	"""Days since gate-in, for a tank that is still in the depo. ``None`` otherwise — a
	tank that has left carries a stale in-date, and counting from it reads as storage that
	is still running."""
	if not c.in_date or c.inventory_stage not in IN_DEPO_STAGES:
		return None
	return date_diff(now, getdate(c.in_date))


def _containers(filters):
	query = {}
	for field in ("status", "container_type", "principal", "depot", "inventory_stage"):
		if filters.get(field):
			query[field] = filters[field]
	# Physically-present tanks by default: reservations that have not arrived and tanks that
	# already left are not inventory. Stated positively (IN_DEPO_STAGES) so a container with
	# a blank stage is not silently counted as stock.
	# ...except when the date range is on Depot Out: a tank that left can never be in the
	# depo, so the pair would always come back empty.
	leaving = report_kit.basis(filters, "in_date") == "out_date" and (
		filters.get("from_date") or filters.get("to_date")
	)
	if filters.get("in_depo_only", 1) and not filters.get("inventory_stage") and not leaving:
		query["inventory_stage"] = ["in", IN_DEPO_STAGES]
	# A retired tank is master data that is no longer in play; it is off by default but
	# reachable, because "why is this tank not in the report" needs an answer too.
	if not filters.get("include_retired"):
		query["is_active"] = 1
	# `frappe.get_all` runs with ignore_permissions=True, so NEITHER the DocPerm matrix nor
	# the Customer User Permission reaches these rows: an external customer account is
	# filtered here by hand or not at all, and every query below is bounded by the names
	# this one returns. None for internal staff, who see everything.
	customers = get_user_customers()
	if customers:
		asked = query.get("principal")
		if asked and asked not in customers:
			return []
		query["principal"] = asked or ["in", customers]
	return frappe.get_all(
		"Container",
		filters=query,
		fields=[
			"name", "principal", "container_type", "equipment_type", "size", "status",
			"inventory_stage", "last_cargo", "in_date", "target_lift_on",
			"depot", "last_test_date", "out_date", "lift_on_booking",
		],
		order_by="principal asc, name asc",
		limit_page_length=0,
	)


def _newest(rows, key="container"):
	"""Rows sorted oldest -> newest, folded so the newest per container wins."""
	out = {}
	for r in rows:
		if r.get(key):
			out[r[key]] = r
	return out


def _visit_facts(names: list[str]) -> dict[str, dict]:
	"""``{container: {...}}`` — the Stock Report's per-stage dates and outbound details,
	each from the newest document of its kind. :func:`execute` keeps only the ones dated on
	or after the tank's In Depot date. One query per source, for the whole result set."""
	if not names:
		return {}
	out: dict[str, dict] = {n: {} for n in names}

	eir_in = _newest(frappe.get_all(
		"Inspection",
		filters={"container": ["in", names], "inspection_type": "EIR-In", "docstatus": ["<", 2]},
		fields=["name", "container", "remarks", "tank_status"],
		order_by="creation asc", limit_page_length=0,
	))
	# No remarks typed on the EIR: its damage lines say what was found instead.
	bare = [r.name for r in eir_in.values() if not r.remarks]
	damages: dict[str, list] = {}
	for d in frappe.get_all(
		"Inspection Damage Entry",
		filters={"parent": ["in", bare or [""]], "parenttype": "Inspection"},
		fields=["parent", "damage_description", "component"], order_by="idx asc", limit_page_length=0,
	):
		text = d.damage_description or d.component
		if text:
			damages.setdefault(d.parent, []).append(text)
	for c, r in eir_in.items():
		out[c]["eir_in"] = {
			"tank_status": r.tank_status,
			"remarks": r.remarks or ", ".join(damages.get(r.name, [])[:4]) or None,
		}

	for c, r in _newest(frappe.get_all(
		"Cleaning Order",
		filters={"container": ["in", names], "docstatus": ["<", 2], "status": ["!=", "Cancelled"]},
		fields=["container", "cleaning_start", "cleaning_end"],
		order_by="creation asc", limit_page_length=0,
	)).items():
		out[c]["cleaning_start"] = r.cleaning_start
		out[c]["cleaning_end"] = r.cleaning_end

	for c, r in _newest(frappe.get_all(
		"Repair Order",
		filters={"container": ["in", names], "status": ["not in", ["Cancelled", "Rejected"]]},
		fields=["container", "start_date"],
		order_by="creation asc", limit_page_length=0,
	)).items():
		out[c]["repair_start"] = r.start_date

	# The day the tank last turned Available — the status ledger records every change.
	for c, r in _newest(frappe.get_all(
		"Container Movement",
		filters={"container": ["in", names], "to_status": "Available"},
		fields=["container", "movement_timestamp"],
		order_by="movement_timestamp asc", limit_page_length=0,
	)).items():
		out[c]["available_date"] = r.movement_timestamp

	# The Survey Order's own date (Tanggal Survey), for tanks it has surveyed — not the moment
	# the surveyor pressed Selesai (user, 2026-10-02).
	for c, r in _newest(frappe.db.sql(
		"""
		SELECT t.container, o.survey_date
		FROM `tabSurvey Order Tank` t
		JOIN `tabSurvey Order` o ON o.name = t.parent AND t.parenttype = 'Survey Order'
		WHERE t.container IN %(names)s AND t.surveyed_on IS NOT NULL AND o.survey_date IS NOT NULL
		ORDER BY t.surveyed_on ASC
		""",
		{"names": names or [""]}, as_dict=True,
	)).items():
		out[c]["survey_date"] = r.survey_date

	# Outbound: the export reference + shipper off the newest live Tank Out booking, the seals
	# off the newest EIR-Out.
	for r in frappe.db.sql(
		"""
		SELECT ci.container, ci.shipper, b.reff_doc, b.name AS booking, b.creation
		FROM `tabContainer Booking Item` ci
		JOIN `tabContainer Booking` b ON b.name = ci.parent
		WHERE ci.parenttype = 'Container Booking' AND ci.container IN %(names)s
		  AND b.direction = 'Tank Out' AND b.docstatus < 2 AND b.booking_status != 'Cancelled'
		ORDER BY b.creation ASC
		""",
		{"names": tuple(names)}, as_dict=True,
	):
		out[r.container].setdefault("out_jobs", {})[r.booking] = r
		out[r.container]["out_newest"] = r.booking
	eir_out = _newest(frappe.get_all(
		"Inspection",
		filters={"container": ["in", names], "inspection_type": "EIR-Out", "docstatus": ["<", 2]},
		fields=["name", "container", "creation"], order_by="creation asc", limit_page_length=0,
	))
	seals: dict[str, list] = {}
	for s in frappe.get_all(
		"Inspection Seal",
		filters={"parent": ["in", [r.name for r in eir_out.values()] or [""]], "parenttype": "Inspection"},
		fields=["parent", "seal_no"], order_by="idx asc", limit_page_length=0,
	):
		if s.seal_no:
			seals.setdefault(s.parent, []).append(s.seal_no)
	for c, r in eir_out.items():
		out[c]["seal_no"] = ", ".join(seals.get(r.name, [])) or None
		out[c]["eir_out_on"] = r.creation
	return out


def _open_work(names: list[str]) -> dict[str, list[str]]:
	"""``{container: [label, ...]}`` for work that still holds the tank.

	Mirrors :func:`container_status.container_open_orders` exactly — a draft EIR-In plus
	any unfinished Cleaning / M&R of THIS visit (created after ``last_departure``) — but
	resolved for the whole result set in five queries instead of five per row.
	"""
	if not names:
		return {}
	out: dict[str, list[str]] = {}
	since = _last_departures(names)

	def add(row, label):
		if row.container and (row.container not in since or row.creation > since[row.container]):
			out.setdefault(row.container, []).append(label)

	for row in frappe.get_all(
		"Inspection",
		filters={"container": ["in", names], "inspection_type": "EIR-In", "docstatus": 0},
		fields=["container", "creation"],
		limit_page_length=0,
	):
		add(row, "EIR-In")
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
			fields=["container", "creation"],
			limit_page_length=0,
		):
			add(row, label)
	return out


def _last_departures(names: list[str]) -> dict:
	"""``{container: last gate-out}`` for the tanks back in the yard —
	:func:`container_status.last_departure` for the whole result set at once."""
	present = {
		r.container_no or r.name: r.name
		for r in frappe.get_all(
			"Container",
			filters={"name": ["in", names], "status": ["in", PRESENT]},
			fields=["name", "container_no"],
			limit_page_length=0,
		)
	}
	out = {}
	if not present:
		return out
	for g in frappe.get_all(
		"Gate Entry",
		filters={
			"container_no": ["in", list(present)],
			"docstatus": ["<", 2],
			"status": ["!=", "Cancelled"],
			"gate_out_timestamp": ["is", "set"],
		},
		fields=["container_no", "gate_out_timestamp"],
		limit_page_length=0,
	):
		c = present[g.container_no]
		if c not in out or g.gate_out_timestamp > out[c]:
			out[c] = g.gate_out_timestamp
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
		# The field survey reaches the tank through a child row too, since the schedule is per
		# BOOKING and lists its tanks — see Survey Order Tank.
		"survey_order": _via_child(
			"Survey Order Tank", "Survey Order", names, "p.status != 'Cancelled'",
		),
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
