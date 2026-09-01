"""Container Survey Register — survei posisi tank, dari diminta sampai disetujui.

Survei posisi lahir dari sebuah booking keluar: sebelum tank bisa diambil, posisinya di
yard harus dipastikan. Selama survei belum selesai, tanknya belum benar-benar bisa
dijanjikan — jadi yang dicari di halaman ini adalah survei yang MASIH menggantung, dan
seberapa lama ia menggantung.

Setiap tahap dokumen punya kolomnya sendiri (diminta, dikerjakan, disetujui) supaya
antrean yang tersangkut kelihatan tersangkut di mana, bukan cuma "belum selesai".
"""

from __future__ import annotations

import frappe

# Survei yang masih menuntut pekerjaan seseorang. "In Fix" ikut: posisinya salah dan
# sedang dibetulkan, jadi tanknya belum bisa dijanjikan.
OPEN_SURVEY = ("Pending Survey", "In Survey", "Surveyed", "In Fix")


def execute(filters=None):
	filters = filters or {}
	rows = _rows(filters)
	return _columns(), rows, None, None, _summary(rows)


def _rows(filters) -> list:
	where = ["s.docstatus < 2", "s.status != 'Cancelled'"]
	params = {}
	for key, clause in (
		("depot", "s.depot = %(depot)s"),
		("status", "s.status = %(status)s"),
		("container", "s.container = %(container)s"),
	):
		if filters.get(key):
			where.append(clause)
			params[key] = filters[key]
	if filters.get("principal"):
		where.append("c.principal = %(principal)s")
		params["principal"] = filters["principal"]
	if filters.get("from_date"):
		where.append("DATE(s.creation) >= %(from_date)s")
		params["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		where.append("DATE(s.creation) <= %(to_date)s")
		params["to_date"] = filters["to_date"]
	if filters.get("only_outstanding"):
		where.append("s.status IN %(open)s")
		params["open"] = OPEN_SURVEY

	return frappe.db.sql(
		f"""
		SELECT
			s.container AS tank_no,
			c.principal AS principal,
			DATE(s.creation) AS requested_on,
			s.target_lift_on,
			DATE(s.survey_started_on) AS started_on,
			DATE(s.surveyed_on) AS surveyed_on,
			DATE(s.approved_on) AS approved_on,
			s.status, s.depot, s.booking, s.name AS survey
		FROM `tabContainer Position Survey` s
		LEFT JOIN `tabContainer` c ON s.container = c.name
		WHERE {' AND '.join(where)}
		ORDER BY s.creation ASC
		""",
		params,
		as_dict=True,
	)


def _columns() -> list:
	return [
		{"fieldname": "tank_no", "label": "Tank No", "fieldtype": "Link",
		 "options": "Container", "width": 140},
		{"fieldname": "principal", "label": "Principle", "fieldtype": "Link",
		 "options": "Customer", "width": 160},
		{"fieldname": "requested_on", "label": "Diminta", "fieldtype": "Date", "width": 100},
		{"fieldname": "target_lift_on", "label": "Target Lift-On", "fieldtype": "Date", "width": 115},
		{"fieldname": "started_on", "label": "Mulai Survei", "fieldtype": "Date", "width": 110},
		{"fieldname": "surveyed_on", "label": "Selesai Survei", "fieldtype": "Date", "width": 115},
		{"fieldname": "approved_on", "label": "Disetujui", "fieldtype": "Date", "width": 105},
		{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 120},
		{"fieldname": "depot", "label": "Depot", "fieldtype": "Link", "options": "Depot", "width": 100},
		{"fieldname": "booking", "label": "Booking", "fieldtype": "Link",
		 "options": "Container Booking", "width": 150},
		{"fieldname": "survey", "label": "Survey", "fieldtype": "Link",
		 "options": "Container Position Survey", "width": 160},
	]


def _summary(rows) -> list:
	outstanding = sum(1 for r in rows if r["status"] in OPEN_SURVEY)
	untouched = sum(1 for r in rows if r["status"] == "Pending Survey")
	return [
		{"label": "Total Survei", "value": len(rows), "datatype": "Int"},
		{"label": "Belum Disentuh", "value": untouched, "datatype": "Int",
		 "indicator": "Red" if untouched else "Green"},
		{"label": "Masih Berjalan", "value": outstanding, "datatype": "Int",
		 "indicator": "Orange" if outstanding else "Green"},
		{"label": "Confirmed", "value": sum(1 for r in rows if r["status"] == "Confirmed"),
		 "datatype": "Int", "indicator": "Green"},
	]
