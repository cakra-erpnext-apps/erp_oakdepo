"""Leak Check Register — satu baris per Leak Check, terbaru di atas.

Akses mengikuti read di ``Leak Check`` (Report tanpa tabel roles jatuh ke ref_doctype).
"""

from __future__ import annotations

import frappe


def execute(filters=None):
	filters = filters or {}
	rows = _rows(filters)
	return _columns(), rows, None, None, _summary(rows)


def _rows(filters) -> list:
	where = ["1=1"]
	params = {}
	for key, clause in (
		("depot", "l.depot = %(depot)s"),
		("container", "l.container = %(container)s"),
		("principal", "c.principal = %(principal)s"),
		("from_date", "DATE(l.recorded_on) >= %(from_date)s"),
		("to_date", "DATE(l.recorded_on) <= %(to_date)s"),
	):
		if filters.get(key):
			where.append(clause)
			params[key] = filters[key]
	if filters.get("only_leak"):
		where.append("l.has_leak = 1")

	return frappe.db.sql(
		f"""
		SELECT
			l.container AS tank_no,
			c.principal AS principal,
			l.depot,
			l.recorded_on,
			l.recorded_by,
			COUNT(p.name) AS photos,
			SUM(p.is_leak) AS leak_photos,
			l.has_leak,
			l.remarks,
			l.name AS leak_check
		FROM `tabLeak Check` l
		LEFT JOIN `tabContainer` c ON c.name = l.container
		LEFT JOIN `tabLeak Check Photo` p ON p.parent = l.name AND p.parenttype = 'Leak Check'
		WHERE {' AND '.join(where)}
		GROUP BY l.name
		ORDER BY l.recorded_on DESC
		""",
		params,
		as_dict=True,
	)


def _columns() -> list:
	return [
		{"fieldname": "tank_no", "label": "Tank No", "fieldtype": "Link", "options": "Container", "width": 140},
		{"fieldname": "principal", "label": "Principle", "fieldtype": "Link", "options": "Customer", "width": 160},
		{"fieldname": "depot", "label": "Depot", "fieldtype": "Link", "options": "Depot", "width": 100},
		{"fieldname": "recorded_on", "label": "Dicek", "fieldtype": "Datetime", "width": 150},
		{"fieldname": "recorded_by", "label": "Dicek Oleh", "fieldtype": "Link", "options": "User", "width": 160},
		{"fieldname": "photos", "label": "Foto", "fieldtype": "Int", "width": 70},
		{"fieldname": "leak_photos", "label": "Foto Bocor", "fieldtype": "Int", "width": 90},
		{"fieldname": "has_leak", "label": "Hasil", "fieldtype": "Data", "width": 90},
		{"fieldname": "remarks", "label": "Remark", "fieldtype": "Data", "width": 220},
		{"fieldname": "leak_check", "label": "Leak Check", "fieldtype": "Link", "options": "Leak Check", "width": 150},
	]


def _summary(rows) -> list:
	leaking = sum(1 for r in rows if r["has_leak"])
	return [
		{"label": "Total Leak Check", "value": len(rows), "datatype": "Int"},
		{"label": "Ada Kebocoran", "value": leaking, "datatype": "Int",
		 "indicator": "Red" if leaking else "Green"},
	]
