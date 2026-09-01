"""Gate Out Plan Register — pemberitahuan lift-on dari customer, dan seberapa jauh dipenuhi.

Gate Out Plan adalah janji: tank ini akan diambil pada tanggal itu. Nilainya justru ada
pada rencana yang LEWAT TANGGAL tapi tanknya masih di yard — itu tank yang menghabiskan
tempat, dan pekerjaan cleaning / M&R yang seharusnya diprioritaskan agar tank siap.
Karena itu "Lewat Tanggal" jadi angka tersendiri di ringkasan, merah, bukan sesuatu yang
harus dicari dengan menyortir tabel.

``per_fulfilled`` datang dari dokumennya sendiri (dihitung saat tank keluar), jadi
laporan ini tidak menghitung ulang apa pun — ia hanya menyusunnya jadi daftar.
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate


def execute(filters=None):
	filters = filters or {}
	rows = _rows(filters)
	return _columns(), rows, None, None, _summary(rows)


def _rows(filters) -> list:
	where = ["1 = 1"]
	params = {}
	for key, clause in (
		("principal", "p.principal = %(principal)s"),
		("customer", "p.customer = %(customer)s"),
		("status", "p.status = %(status)s"),
	):
		if filters.get(key):
			where.append(clause)
			params[key] = filters[key]
	if filters.get("from_date"):
		where.append("p.plan_date >= %(from_date)s")
		params["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		where.append("p.plan_date <= %(to_date)s")
		params["to_date"] = filters["to_date"]
	if filters.get("only_open"):
		where.append("p.status = 'Open'")

	return frappe.db.sql(
		f"""
		SELECT
			p.plan_date, p.next_lift_on, p.principal, p.customer,
			p.customer_do_no, p.container_summary AS tanks,
			p.per_fulfilled, p.status, p.source, p.name AS plan
		FROM `tabGate Out Plan` p
		WHERE {' AND '.join(where)}
		ORDER BY p.plan_date ASC, p.creation ASC
		""",
		params,
		as_dict=True,
	)


def _columns() -> list:
	return [
		{"fieldname": "plan_date", "label": "Plan Date", "fieldtype": "Date", "width": 105},
		{"fieldname": "next_lift_on", "label": "Next Lift-On", "fieldtype": "Date", "width": 110},
		{"fieldname": "principal", "label": "Principle", "fieldtype": "Link",
		 "options": "Customer", "width": 170},
		{"fieldname": "customer", "label": "Customer", "fieldtype": "Link",
		 "options": "Customer", "width": 170},
		{"fieldname": "customer_do_no", "label": "DO Customer", "fieldtype": "Data", "width": 130},
		{"fieldname": "tanks", "label": "Tank", "fieldtype": "Data", "width": 240},
		{"fieldname": "per_fulfilled", "label": "% Keluar", "fieldtype": "Percent", "width": 100},
		{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 110},
		{"fieldname": "source", "label": "Sumber", "fieldtype": "Data", "width": 120},
		{"fieldname": "plan", "label": "Gate Out Plan", "fieldtype": "Link",
		 "options": "Gate Out Plan", "width": 160},
	]


def _summary(rows) -> list:
	open_rows = [r for r in rows if r["status"] == "Open"]
	overdue = sum(1 for r in open_rows if r["plan_date"] and getdate(r["plan_date"]) < getdate())
	return [
		{"label": "Total Plan", "value": len(rows), "datatype": "Int"},
		{"label": "Open", "value": len(open_rows), "datatype": "Int",
		 "indicator": "Orange" if open_rows else "Green"},
		{"label": "Fulfilled", "value": sum(1 for r in rows if r["status"] == "Fulfilled"),
		 "datatype": "Int", "indicator": "Green"},
		# Tanggalnya sudah lewat, tanknya masih di yard: tempat yang terpakai, dan
		# pekerjaan yang seharusnya didahulukan supaya tanknya siap.
		{"label": "Lewat Tanggal", "value": overdue, "datatype": "Int",
		 "indicator": "Red" if overdue else "Green"},
	]
