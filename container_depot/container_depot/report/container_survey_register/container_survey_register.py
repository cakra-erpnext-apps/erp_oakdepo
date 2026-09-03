"""Container Survey Register — survei posisi tank, dari dijadwalkan sampai survey ditutup.

Survei posisi lahir dari sebuah booking keluar: sebelum tank bisa diambil ia harus
diturunkan ke ground level dan diperiksa. Selama survei belum ditutup, tanknya belum
benar-benar bisa dijanjikan — jadi yang dicari di halaman ini adalah survei yang MASIH
menggantung, dan seberapa lama ia menggantung.

Setiap tahap punya kolomnya sendiri (dijadwalkan, diturunkan, disurvei) supaya antrean yang
tersangkut kelihatan tersangkut DI MANA, bukan cuma "belum selesai" — dan sejak alurnya
dibalik 2026-09-03 itu jauh lebih sering tersangkut di lowering daripada di surveynya.

Letak tank ikut dibaca dari master Container (bukan dari baris survey), lengkap dengan tanggal
terakhir dicatat: satu tank yang macet di lowering dan letaknya terakhir didata bulan lalu
adalah kasus yang berbeda dari yang letaknya didata pagi ini — yang pertama hilang, yang kedua
cuma menunggu reachstacker. Lihat ``container_position``.
"""

from __future__ import annotations

import frappe

# Survei yang masih menuntut pekerjaan seseorang: tank yang belum turun, dan tank yang sudah
# turun tapi surveynya belum ditutup. Keduanya sama-sama menahan janji ke customer.
OPEN_SURVEY = ("Waiting Lowering", "Lowered")


def execute(filters=None):
	filters = filters or {}
	rows = _rows(filters)
	return _columns(), rows, None, None, _summary(rows)


def _rows(filters) -> list:
	where = ["s.parenttype = 'Survey Order'", "o.status != 'Cancelled'", "s.status != 'Cancelled'"]
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
		where.append("o.survey_date >= %(from_date)s")
		params["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		where.append("o.survey_date <= %(to_date)s")
		params["to_date"] = filters["to_date"]
	if filters.get("only_outstanding"):
		where.append("s.status IN %(open)s")
		params["open"] = OPEN_SURVEY

	return frappe.db.sql(
		f"""
		SELECT
			s.container AS tank_no,
			c.principal AS principal,
			DATE(o.creation) AS requested_on,
			s.target_lift_on,
			o.survey_date,
			DATE(s.lowered_on) AS lowered_on,
			DATE(s.surveyed_on) AS surveyed_on,
			s.status, s.depot, o.booking, s.parent AS survey_order,
			c.current_location AS location_note,
			DATE(c.location_updated_on) AS location_updated_on
		FROM `tabSurvey Order Tank` s
		JOIN `tabSurvey Order` o ON o.name = s.parent
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
		{"fieldname": "survey_date", "label": "Jadwal Survei", "fieldtype": "Date", "width": 110},
		{"fieldname": "lowered_on", "label": "Turun (Lowered)", "fieldtype": "Date", "width": 120},
		{"fieldname": "surveyed_on", "label": "Survei Selesai", "fieldtype": "Date", "width": 115},
		{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 120},
		{"fieldname": "depot", "label": "Depot", "fieldtype": "Link", "options": "Depot", "width": 100},
		{"fieldname": "booking", "label": "Booking", "fieldtype": "Link",
		 "options": "Container Booking", "width": 150},
		{"fieldname": "survey_order", "label": "Jadwal", "fieldtype": "Link",
		 "options": "Survey Order", "width": 150},
		{"fieldname": "location_note", "label": "Letak Terakhir", "fieldtype": "Data", "width": 180},
		{"fieldname": "location_updated_on", "label": "Letak Diperbarui", "fieldtype": "Date", "width": 120},

	]


def _summary(rows) -> list:
	outstanding = sum(1 for r in rows if r["status"] in OPEN_SURVEY)
	untouched = sum(1 for r in rows if r["status"] == "Waiting Lowering")
	return [
		{"label": "Total Survei", "value": len(rows), "datatype": "Int"},
		{"label": "Belum Turun", "value": untouched, "datatype": "Int",
		 "indicator": "Red" if untouched else "Green"},
		{"label": "Masih Berjalan", "value": outstanding, "datatype": "Int",
		 "indicator": "Orange" if outstanding else "Green"},
		{"label": "Survey Selesai", "value": sum(1 for r in rows if r["status"] == "Survey Done"),
		 "datatype": "Int", "indicator": "Green"},
	]
