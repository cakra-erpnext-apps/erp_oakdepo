"""Container Booking Register — semua booking tank masuk / keluar dalam satu daftar.

Dibaca berdampingan dengan register cuci dan uji berkala: yang itu pekerjaan atas tank
yang sudah di dalam, yang ini janji tank masuk dan keluar. Yang dicari orang di sini
hampir selalu satu dari tiga hal — booking mana yang belum dibayar, booking mana yang
belum dikonfirmasi, dan tank siapa yang datang minggu ini — jadi ketiganya jadi angka
ringkasan di atas, bukan sesuatu yang harus dihitung sendiri dari tabel.

Booking yang dibatalkan tetap ikut kecuali disaring: pembatalan adalah bagian dari
riwayat pelanggan, dan register yang menyembunyikannya membuat orang mengira booking itu
tidak pernah ada.
"""

from __future__ import annotations

import frappe


def execute(filters=None):
	filters = filters or {}
	rows = _rows(filters)
	return _columns(), rows, None, None, _summary(rows)


def _rows(filters) -> list:
	where = ["b.docstatus < 2"]
	params = {}
	for key, clause in (
		("customer", "b.customer = %(customer)s"),
		("principal", "b.principal = %(principal)s"),
		("depot", "b.depot = %(depot)s"),
		("direction", "b.direction = %(direction)s"),
		("booking_status", "b.booking_status = %(booking_status)s"),
	):
		if filters.get(key):
			where.append(clause)
			params[key] = filters[key]
	if filters.get("from_date"):
		where.append("DATE(b.creation) >= %(from_date)s")
		params["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		where.append("DATE(b.creation) <= %(to_date)s")
		params["to_date"] = filters["to_date"]
	if filters.get("only_unpaid"):
		where.append("b.payment_status = 'Unpaid'")

	return frappe.db.sql(
		f"""
		SELECT
			DATE(b.creation) AS order_date,
			b.direction, b.customer, b.principal,
			b.container_summary AS tanks,
			b.payment_type, b.charges_total, b.currency,
			b.payment_status, b.booking_status,
			b.sales_invoice, b.depot,
			b.name AS booking
		FROM `tabContainer Booking` b
		WHERE {' AND '.join(where)}
		ORDER BY b.creation ASC
		""",
		params,
		as_dict=True,
	)


def _columns() -> list:
	return [
		{"fieldname": "order_date", "label": "Order Date", "fieldtype": "Date", "width": 105},
		{"fieldname": "direction", "label": "Arah", "fieldtype": "Data", "width": 90},
		{"fieldname": "customer", "label": "Customer", "fieldtype": "Link",
		 "options": "Customer", "width": 170},
		{"fieldname": "principal", "label": "Principle", "fieldtype": "Link",
		 "options": "Customer", "width": 160},
		{"fieldname": "tanks", "label": "Tank", "fieldtype": "Data", "width": 220},
		{"fieldname": "payment_type", "label": "Bayar", "fieldtype": "Data", "width": 80},
		# Di sini angkanya memang uang — beda dari kartu dashboard, yang mencacah dokumen.
		# ``options: currency`` menunjuk kolom currency di baris yang sama, jadi booking
		# USD dan IDR tidak pernah ditampilkan dengan simbol yang sama.
		{"fieldname": "charges_total", "label": "Total", "fieldtype": "Currency",
		 "options": "currency", "width": 130},
		{"fieldname": "payment_status", "label": "Pembayaran", "fieldtype": "Data", "width": 110},
		{"fieldname": "booking_status", "label": "Status", "fieldtype": "Data", "width": 130},
		{"fieldname": "sales_invoice", "label": "Invoice", "fieldtype": "Link",
		 "options": "Sales Invoice", "width": 150},
		{"fieldname": "depot", "label": "Depot", "fieldtype": "Link", "options": "Depot", "width": 100},
		{"fieldname": "booking", "label": "Booking", "fieldtype": "Link",
		 "options": "Container Booking", "width": 150},
	]


def _summary(rows) -> list:
	unpaid = sum(1 for r in rows if r["payment_status"] == "Unpaid")
	waiting = sum(
		1 for r in rows if r["booking_status"] in ("Draft", "Pending Payment", "Pending Confirmation")
	)
	return [
		{"label": "Total Booking", "value": len(rows), "datatype": "Int"},
		{"label": "Tank In", "value": sum(1 for r in rows if r["direction"] == "Tank In"),
		 "datatype": "Int", "indicator": "Green"},
		{"label": "Tank Out", "value": sum(1 for r in rows if r["direction"] == "Tank Out"),
		 "datatype": "Int", "indicator": "Blue"},
		{"label": "Belum Dikonfirmasi", "value": waiting, "datatype": "Int",
		 "indicator": "Orange" if waiting else "Green"},
		{"label": "Belum Dibayar", "value": unpaid, "datatype": "Int",
		 "indicator": "Red" if unpaid else "Green"},
	]
