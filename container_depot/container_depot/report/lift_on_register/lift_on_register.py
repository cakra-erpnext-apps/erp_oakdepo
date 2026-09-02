"""Lift On Register — booking keluar (Tank Out) dan seberapa jauh sudah diambil.

Sebuah booking keluar adalah janji: tank ini akan diambil pada tanggal itu. Nilainya justru
ada pada booking yang LEWAT TANGGAL tapi tanknya masih di yard — itu tempat yang terpakai,
dan pekerjaan cleaning / M&R yang seharusnya diprioritaskan supaya tanknya siap. Karena itu
"Lewat Tanggal" jadi angka tersendiri di ringkasan, merah, bukan sesuatu yang harus dicari
dengan menyortir tabel.

``per_fulfilled`` datang dari dokumennya sendiri (dihitung saat tank keluar gate), jadi
laporan ini tidak menghitung ulang apa pun — ia hanya menyusunnya jadi daftar.

Pengganti Gate Out Plan Register: pemberitahuan lift-on tidak lagi jadi dokumen tersendiri,
melainkan booking keluar itu sendiri.
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate

# Booking yang belum selesai keluar. Bukan "Open" seperti dulu — sebuah booking punya alur
# statusnya sendiri, dan yang berarti di sini adalah: sudah dikonfirmasi, tanknya belum
# semua keluar.
LIVE_STATUSES = ("Draft", "Pending Payment", "Pending Confirmation", "Confirmed", "Blocked")


def execute(filters=None):
	filters = filters or {}
	rows = _rows(filters)
	return _columns(), rows, None, None, _summary(rows)


def _rows(filters) -> list:
	where = ["b.direction = 'Tank Out'"]
	params = {}
	for key, clause in (
		("principal", "b.principal = %(principal)s"),
		("customer", "b.customer = %(customer)s"),
		("branch", "b.branch = %(branch)s"),
		("status", "b.booking_status = %(status)s"),
	):
		if filters.get(key):
			where.append(clause)
			params[key] = filters[key]
	if filters.get("from_date"):
		where.append("b.plan_date >= %(from_date)s")
		params["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		where.append("b.plan_date <= %(to_date)s")
		params["to_date"] = filters["to_date"]
	if filters.get("only_open"):
		where.append("b.booking_status in %(live)s")
		params["live"] = LIVE_STATUSES

	return frappe.db.sql(
		f"""
		SELECT
			b.plan_date, b.principal, b.customer, b.branch,
			b.do_reference AS customer_do_no, b.container_summary AS tanks,
			b.per_fulfilled, b.bon_status, b.booking_status AS status, b.name AS booking
		FROM `tabContainer Booking` b
		WHERE {' AND '.join(where)}
		ORDER BY b.plan_date ASC, b.creation ASC
		""",
		params,
		as_dict=True,
	)


def _columns() -> list:
	return [
		{"fieldname": "plan_date", "label": "Tanggal Rencana", "fieldtype": "Date", "width": 120},
		{"fieldname": "principal", "label": "Principle", "fieldtype": "Link",
		 "options": "Customer", "width": 170},
		{"fieldname": "customer", "label": "Customer", "fieldtype": "Link",
		 "options": "Customer", "width": 170},
		{"fieldname": "branch", "label": "Branch", "fieldtype": "Link",
		 "options": "Branch", "width": 120},
		{"fieldname": "customer_do_no", "label": "DO Customer", "fieldtype": "Data", "width": 130},
		{"fieldname": "tanks", "label": "Tank", "fieldtype": "Data", "width": 240},
		# Dua kemajuan yang berbeda dan sering tertukar: bon = kertas sudah terbit,
		# % keluar = tanknya sudah benar-benar lewat gate.
		{"fieldname": "bon_status", "label": "Bon", "fieldtype": "Data", "width": 120},
		{"fieldname": "per_fulfilled", "label": "% Keluar", "fieldtype": "Percent", "width": 100},
		{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 130},
		{"fieldname": "booking", "label": "Booking", "fieldtype": "Link",
		 "options": "Container Booking", "width": 170},
	]


def _summary(rows) -> list:
	live = [r for r in rows if r["status"] in LIVE_STATUSES]
	overdue = sum(1 for r in live if r["plan_date"] and getdate(r["plan_date"]) < getdate())
	return [
		{"label": "Total Booking Keluar", "value": len(rows), "datatype": "Int"},
		{"label": "Belum Selesai", "value": len(live), "datatype": "Int",
		 "indicator": "Orange" if live else "Green"},
		{"label": "Selesai Keluar", "value": sum(1 for r in rows if r["status"] == "Completed"),
		 "datatype": "Int", "indicator": "Green"},
		# Tanggalnya sudah lewat, tanknya masih di yard: tempat yang terpakai, dan
		# pekerjaan yang seharusnya didahulukan supaya tanknya siap.
		{"label": "Lewat Tanggal", "value": overdue, "datatype": "Int",
		 "indicator": "Red" if overdue else "Green"},
	]
