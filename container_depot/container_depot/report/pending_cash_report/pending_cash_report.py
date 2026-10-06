"""Pending Cash Report — satu baris per Pending Cash, dengan jumlah keluar / masuk.

Lewat ``frappe.get_list``, bukan SQL mentah: Pending Cash ber-centang Confidential hanya
terbaca pembuatnya + Finance (pending_cash.get_permission_query_conditions), dan report ini
tidak boleh jadi jalan pintas di sekitarnya.
"""

from __future__ import annotations

import frappe

from container_depot.container_depot import report_kit

_UNPAID = ("Draft", "Validated")


def execute(filters=None):
	filters = filters or {}
	columns, rows = report_kit.finish(_columns(), _rows(filters), filters, default="date")
	return columns, rows, None, None, _summary(rows)


def _rows(filters) -> list:
	where = {}
	for key in ("direction", "status", "branch", "pending_cash_type"):
		if filters.get(key):
			where[key] = filters[key]
	frm, to = report_kit.native_range(filters, "date")
	if frm and to:
		where["date"] = ["between", [frm, to]]
	elif frm or to:
		where["date"] = [">=", frm] if frm else ["<=", to]
	return frappe.get_list(
		"Pending Cash",
		filters=where,
		fields=[
			"date", "pending_cash_type", "direction", "connection_party", "modul", "number",
			"total", "net_amount_paid", "refunded_amount", "status", "paid_date", "branch",
			"journal_entry", "name as pending_cash",
		],
		order_by="date asc, creation asc",
		limit_page_length=0,
	)


def _columns() -> list:
	return [
		{"fieldname": "date", "label": "Date", "fieldtype": "Date", "width": 105},
		{"fieldname": "pending_cash_type", "label": "Type", "fieldtype": "Link",
		 "options": "Pending Cash Type", "width": 140},
		{"fieldname": "direction", "label": "Arah", "fieldtype": "Data", "width": 110},
		{"fieldname": "connection_party", "label": "Customer / Vendor", "fieldtype": "Data",
		 "width": 170},
		{"fieldname": "modul", "label": "Modul", "fieldtype": "Data", "hidden": 1},
		{"fieldname": "number", "label": "Source No", "fieldtype": "Dynamic Link",
		 "options": "modul", "width": 160},
		{"fieldname": "total", "label": "Amount", "fieldtype": "Currency", "width": 130},
		{"fieldname": "net_amount_paid", "label": "Net Paid", "fieldtype": "Currency", "width": 130},
		{"fieldname": "refunded_amount", "label": "Refund", "fieldtype": "Currency", "width": 120},
		{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 110},
		{"fieldname": "paid_date", "label": "Paid Date", "fieldtype": "Date", "width": 105},
		{"fieldname": "branch", "label": "Branch", "fieldtype": "Link", "options": "Branch",
		 "width": 110},
		{"fieldname": "journal_entry", "label": "Journal Entry", "fieldtype": "Link",
		 "options": "Journal Entry", "width": 150},
		{"fieldname": "pending_cash", "label": "Pending Cash", "fieldtype": "Link",
		 "options": "Pending Cash", "width": 150},
	]


def _summary(rows) -> list:
	live = [r for r in rows if r["status"] != "Void"]
	unpaid = sum(1 for r in live if r["status"] in _UNPAID)
	return [
		{"label": "Total Dokumen", "value": len(rows), "datatype": "Int"},
		{"label": "Cash Outflow", "datatype": "Currency",
		 "value": sum(r["total"] or 0 for r in live if r["direction"] == "Cash Outflow")},
		{"label": "Cash Inflow", "datatype": "Currency",
		 "value": sum(r["total"] or 0 for r in live if r["direction"] == "Cash Inflow")},
		{"label": "Belum Dibayar", "value": unpaid, "datatype": "Int",
		 "indicator": "Red" if unpaid else "Green"},
	]
