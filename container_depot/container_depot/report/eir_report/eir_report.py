"""EIR Report — satu baris per EIR (In / Out), menurut tanggal EIR-nya sendiri.

Lewat ``frappe.get_list``, bukan SQL mentah: izin baris (User Permission, scope customer)
ikut berlaku tanpa disalin ke sini.
"""

from __future__ import annotations

import frappe

from container_depot.container_depot import report_kit

_OPEN = ("Draft", "Pending Review")


def execute(filters=None):
	filters = filters or {}
	columns, rows = report_kit.finish(_columns(), _rows(filters), filters, default="eir_date")
	return columns, rows, None, None, _summary(rows)


def _rows(filters) -> list:
	where = {"docstatus": ["<", 2]}
	for key, field in (("inspection_type", "inspection_type"), ("principal", "container_principal"),
			   ("depot", "depot"), ("container", "container")):
		if filters.get(key):
			where[field] = filters[key]
	if filters.get("only_damage"):
		where["has_damage"] = 1
	frm, to = report_kit.native_range(filters, "eir_date")
	if frm and to:
		where["eir_date"] = ["between", [frm, to]]
	elif frm or to:
		where["eir_date"] = [">=", frm] if frm else ["<=", to]

	return frappe.get_list(
		"Inspection",
		filters=where,
		fields=[
			"eir_date", "inspection_type", "container as tank_no",
			"container_principal as principal", "tank_status", "cargo", "has_damage",
			"out_outcome", "status", "container_booking", "depot", "name as eir",
		],
		order_by="eir_date asc, creation asc",
		limit_page_length=0,
	)


def _columns() -> list:
	return [
		{"fieldname": "eir_date", "label": "EIR Date", "fieldtype": "Date", "width": 110},
		{"fieldname": "inspection_type", "label": "Tipe", "fieldtype": "Data", "width": 80},
		{"fieldname": "tank_no", "label": "Tank No", "fieldtype": "Link", "options": "Container",
		 "width": 140},
		{"fieldname": "principal", "label": "Principle", "fieldtype": "Link",
		 "options": "Customer", "width": 160},
		{"fieldname": "tank_status", "label": "Tank Status", "fieldtype": "Data", "width": 110},
		{"fieldname": "cargo", "label": "Cargo", "fieldtype": "Link", "options": "Cargo", "width": 150},
		{"fieldname": "has_damage", "label": "Damage", "fieldtype": "Check", "width": 80},
		{"fieldname": "out_outcome", "label": "EIR-Out Outcome", "fieldtype": "Data", "width": 150},
		{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 120},
		{"fieldname": "container_booking", "label": "Booking", "fieldtype": "Link",
		 "options": "Container Booking", "width": 160},
		{"fieldname": "depot", "label": "Depot", "fieldtype": "Link", "options": "Depot", "width": 100},
		{"fieldname": "eir", "label": "EIR", "fieldtype": "Link", "options": "Inspection",
		 "width": 150},
	]


def _summary(rows) -> list:
	damaged = sum(1 for r in rows if r["has_damage"])
	open_ = sum(1 for r in rows if r["status"] in _OPEN)
	return [
		{"label": "Total EIR", "value": len(rows), "datatype": "Int"},
		{"label": "EIR-In", "value": sum(1 for r in rows if r["inspection_type"] == "EIR-In"),
		 "datatype": "Int", "indicator": "Green"},
		{"label": "EIR-Out", "value": sum(1 for r in rows if r["inspection_type"] == "EIR-Out"),
		 "datatype": "Int", "indicator": "Blue"},
		{"label": "Ada Damage", "value": damaged, "datatype": "Int",
		 "indicator": "Orange" if damaged else "Green"},
		{"label": "Belum Submit", "value": open_, "datatype": "Int",
		 "indicator": "Red" if open_ else "Green"},
	]
