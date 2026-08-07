"""Container Inventory — the live per-tank monitoring list.

One row per Container with its monitoring stage, in-date and age in the depo.
Defaults to tanks physically in the depo (every
``inventory_stage`` except Pre-Arrival / Departed); flip ``in_depo_only`` off to
include reserved + gated-out tanks. Reuses the derived ``inventory_stage`` kept
in step by ``Container.before_save``.
"""

from __future__ import annotations

import frappe
from frappe.utils import date_diff, getdate, today

from container_depot.state_machine import IN_DEPO_STAGES


def execute(filters=None):
	filters = filters or {}
	return _columns(), _data(filters)


def _columns():
	return [
		{"fieldname": "container_no", "label": "Container", "fieldtype": "Link", "options": "Container", "width": 140},
		{"fieldname": "principal", "label": "Principal", "fieldtype": "Link", "options": "Customer", "width": 160},
		{"fieldname": "container_type", "label": "Type", "fieldtype": "Data", "width": 90},
		{"fieldname": "size", "label": "Size", "fieldtype": "Data", "width": 70},
		{"fieldname": "inventory_stage", "label": "Stage", "fieldtype": "Data", "width": 110},
		{"fieldname": "status", "label": "Raw Status", "fieldtype": "Data", "width": 150},
		{"fieldname": "last_cargo", "label": "Last Cargo", "fieldtype": "Link", "options": "Cargo", "width": 120},
		{"fieldname": "cleaning_status", "label": "Cleaning", "fieldtype": "Data", "width": 100},
		{"fieldname": "repair_status", "label": "Repair", "fieldtype": "Data", "width": 110},
		{"fieldname": "in_date", "label": "In Date", "fieldtype": "Date", "width": 100},
		{"fieldname": "days_in_depo", "label": "Days In Depo", "fieldtype": "Int", "width": 110},
		{"fieldname": "next_pt_due", "label": "Next PT Due", "fieldtype": "Date", "width": 100},
	]


def _data(filters):
	where = []
	params = {}
	# Physically-present tanks by default (excludes Pre-Arrival reservations and
	# tanks that have already gated out).
	if filters.get("in_depo_only", 1):
		where.append("c.inventory_stage IN %(in_depo)s")
		params["in_depo"] = tuple(IN_DEPO_STAGES)
	for field in ("principal", "depot", "inventory_stage"):
		if filters.get(field):
			where.append(f"c.{field} = %({field})s")
			params[field] = filters[field]

	clause = (" WHERE " + " AND ".join(where)) if where else ""
	rows = frappe.db.sql(
		f"""
		SELECT c.container_no, c.principal, c.container_type, c.size, c.inventory_stage,
		       c.status, c.last_cargo, c.cleaning_status, c.repair_status,
		       c.eir_in_date, c.next_pt_due
		FROM `tabContainer` c{clause}
		ORDER BY c.principal, c.container_no
		""",
		params,
		as_dict=True,
	)

	now = getdate(today())
	out = []
	for r in rows:
		in_date = getdate(r.eir_in_date) if r.eir_in_date else None
		# Age only makes sense for a tank still in the depo with a recorded gate-in.
		days = date_diff(now, in_date) if (in_date and r.inventory_stage in IN_DEPO_STAGES) else None
		out.append({
			"container_no": r.container_no,
			"principal": r.principal,
			"container_type": r.container_type,
			"size": r.size,
			"inventory_stage": r.inventory_stage,
			"status": r.status,
			"last_cargo": r.last_cargo,
			"cleaning_status": r.cleaning_status,
			"repair_status": r.repair_status,
			"in_date": in_date,
			"days_in_depo": days,
			"next_pt_due": r.next_pt_due,
		})
	return out
