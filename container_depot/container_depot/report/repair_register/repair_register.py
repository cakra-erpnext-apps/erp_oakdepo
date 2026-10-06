"""Repair Register — semua M&R (Repair Order ber-``job_type = Repair``) dalam satu daftar.

Kembaran Periodic Test Register untuk M&R biasa: satu doctype, dua menu (lihat mr_scope).
Order yang belum selesai tetap tampil dengan Completion Date kosong — itu antrean M&R —
dan yang masih menunggu keputusan owner jadi angka tersendiri di ringkasan.

Tanggal bawaannya ``plan_date`` ("Tanggal M&R"): tanggal order itu sendiri, yang juga
dibaca penagihan — bukan jam order dibuat atau disubmit.
"""

from __future__ import annotations

import frappe

from container_depot.container_depot import report_kit
from container_depot.container_depot.container_status import DONE_REPAIR

_BILLED_TO = {"Client Billed": "Client", "Principal Billed": "Principal"}


def execute(filters=None):
	filters = filters or {}
	rows = _rows(filters)
	for r in rows:
		r["billed_to"] = _BILLED_TO.get(r.pop("billing_status"), "")
	columns, rows = report_kit.finish(_columns(), rows, filters, default="plan_date")
	return columns, rows, None, None, _summary(rows)


def _rows(filters) -> list:
	where = ["ro.job_type = 'Repair'", "ro.status != 'Cancelled'"]
	params = {}
	if filters.get("container"):
		where.append("ro.container = %(container)s")
		params["container"] = filters["container"]
	if filters.get("principal"):
		where.append("COALESCE(NULLIF(ro.principal, ''), c.principal) = %(principal)s")
		params["principal"] = filters["principal"]
	if filters.get("depot"):
		where.append("COALESCE(NULLIF(ro.depot, ''), c.depot) = %(depot)s")
		params["depot"] = filters["depot"]
	# Only while the range is on its own column; on another date column
	# report_kit.finish filters the rows instead.
	frm, to = report_kit.native_range(filters, "plan_date")
	if frm:
		where.append("ro.plan_date >= %(from_date)s")
		params["from_date"] = frm
	if to:
		where.append("ro.plan_date <= %(to_date)s")
		params["to_date"] = to
	if filters.get("only_outstanding"):
		where.append("ro.status NOT IN %(done)s")
		params["done"] = tuple(DONE_REPAIR)

	return frappe.db.sql(
		f"""
		SELECT
			ro.container AS tank_no,
			COALESCE(NULLIF(ro.principal, ''), c.principal) AS principal,
			ro.plan_date AS plan_date,
			DATE(ro.order_created) AS order_date,
			DATE(ro.completion_date) AS completion_date,
			ro.status AS status,
			ro.billing_status AS billing_status,
			ro.sales_invoice AS sales_invoice,
			ro.inspection AS inspection,
			ro.name AS repair_order
		FROM `tabRepair Order` ro
		LEFT JOIN `tabContainer` c ON ro.container = c.name
		WHERE {' AND '.join(where)}
		ORDER BY ro.plan_date ASC, ro.order_created ASC
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
		{"fieldname": "plan_date", "label": "Tanggal M&R", "fieldtype": "Date", "width": 110},
		{"fieldname": "order_date", "label": "Order Date", "fieldtype": "Date", "width": 105},
		{"fieldname": "completion_date", "label": "Completion Date", "fieldtype": "Date",
		 "width": 130},
		{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 140},
		{"fieldname": "billed_to", "label": "Billed To", "fieldtype": "Data", "width": 100},
		{"fieldname": "sales_invoice", "label": "Invoice", "fieldtype": "Link",
		 "options": "Sales Invoice", "width": 150},
		{"fieldname": "inspection", "label": "EIR", "fieldtype": "Link",
		 "options": "Inspection", "width": 150},
		{"fieldname": "repair_order", "label": "M&R", "fieldtype": "Link",
		 "options": "Repair Order", "width": 150},
	]


def _summary(rows) -> list:
	done = sum(1 for r in rows if r["status"] == "Completed")
	waiting = sum(1 for r in rows if r["status"] == "Pending Approval")
	open_ = sum(1 for r in rows if r["status"] not in DONE_REPAIR)
	return [
		{"label": "Total Order", "value": len(rows), "datatype": "Int"},
		{"label": "Selesai", "value": done, "datatype": "Int", "indicator": "Green"},
		# Bola di tangan owner tank: M&R-nya belum boleh dikerjakan.
		{"label": "Menunggu Approval", "value": waiting, "datatype": "Int",
		 "indicator": "Orange" if waiting else "Green"},
		{"label": "Belum Selesai", "value": open_, "datatype": "Int",
		 "indicator": "Red" if open_ else "Green"},
	]
