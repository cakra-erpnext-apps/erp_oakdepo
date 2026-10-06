"""Gate Report — satu baris per kunjungan tank (Gate Entry): masuk, keluar, berapa lama.

Lewat ``frappe.get_list``, bukan SQL mentah: scope customer di Gate Entry
(customer_scope.gate_entry_query) dan User Permission tetap berlaku.
"""

from __future__ import annotations

import frappe
from frappe.utils import get_datetime, now_datetime

from container_depot.container_depot import report_kit


def execute(filters=None):
	filters = filters or {}
	columns, rows = report_kit.finish(_columns(), _rows(filters), filters, default="gate_in")
	return columns, rows, None, None, _summary(rows)


def _rows(filters) -> list:
	where = {"status": ["!=", "Cancelled"]}
	if filters.get("depot"):
		where["depot"] = filters["depot"]
	if filters.get("only_inside"):
		where["gate_out_timestamp"] = ["is", "not set"]
	rows = frappe.get_list(
		"Gate Entry",
		filters=where,
		fields=[
			"gate_in_timestamp as gate_in", "gate_out_timestamp as gate_out",
			"container_no as tank_no", "truck_plate", "driver_name", "order_doctype",
			"order_ref", "eir_reference", "status", "depot", "name as gate_entry",
		],
		order_by="gate_in_timestamp asc, creation asc",
		limit_page_length=0,
	)
	now = now_datetime()
	for r in rows:
		r["days"] = (
			((get_datetime(r["gate_out"]) if r["gate_out"] else now) - get_datetime(r["gate_in"])).days
			if r["gate_in"] else None
		)
	return rows


def _columns() -> list:
	return [
		{"fieldname": "gate_in", "label": "Gate In", "fieldtype": "Datetime", "width": 155},
		{"fieldname": "gate_out", "label": "Gate Out", "fieldtype": "Datetime", "width": 155},
		{"fieldname": "days", "label": "Hari di Depo", "fieldtype": "Int", "width": 110},
		{"fieldname": "tank_no", "label": "Tank No", "fieldtype": "Link", "options": "Container",
		 "width": 140},
		{"fieldname": "truck_plate", "label": "No. Pol", "fieldtype": "Data", "width": 110},
		{"fieldname": "driver_name", "label": "Supir", "fieldtype": "Data", "width": 130},
		{"fieldname": "order_doctype", "label": "Doctype", "fieldtype": "Data", "hidden": 1},
		{"fieldname": "order_ref", "label": "Bon", "fieldtype": "Dynamic Link",
		 "options": "order_doctype", "width": 160},
		{"fieldname": "eir_reference", "label": "EIR", "fieldtype": "Link", "options": "Inspection",
		 "width": 150},
		{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 150},
		{"fieldname": "depot", "label": "Depot", "fieldtype": "Link", "options": "Depot", "width": 100},
		{"fieldname": "gate_entry", "label": "Gate Entry", "fieldtype": "Link",
		 "options": "Gate Entry", "width": 150},
	]


def _summary(rows) -> list:
	inside = sum(1 for r in rows if not r["gate_out"])
	return [
		{"label": "Total Kunjungan", "value": len(rows), "datatype": "Int"},
		{"label": "Masih di Depo", "value": inside, "datatype": "Int", "indicator": "Orange"},
		{"label": "Sudah Keluar", "value": len(rows) - inside, "datatype": "Int",
		 "indicator": "Green"},
	]
