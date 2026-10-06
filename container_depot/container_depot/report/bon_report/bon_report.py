"""Bon Report — Bon Bongkar dan Bon Muat dalam satu daftar, menurut tanggal bon-nya.

Lewat ``frappe.get_list``, bukan SQL mentah: izin baris tetap berlaku. Jenis yang tidak
boleh dibaca user dilewati, bukan menggagalkan seluruh report.
"""

from __future__ import annotations

import frappe

from container_depot.container_depot import report_kit

# jenis -> (doctype, field tanggal bon, field tambahan)
_KINDS = {
	"Bongkar": ("Order Bongkar", "tanggal_bongkar", ["principal"]),
	"Muat": ("Order Muat", "tanggal_muat", ["truck_plate", "driver_name", "destination"]),
}


def execute(filters=None):
	filters = filters or {}
	columns, rows = report_kit.finish(_columns(), _rows(filters), filters, default="bon_date")
	return columns, rows, None, None, _summary(rows)


def _rows(filters) -> list:
	rows = []
	for kind, (doctype, date_field, extra) in _KINDS.items():
		if filters.get("kind") and filters["kind"] != kind:
			continue
		if not frappe.has_permission(doctype, "read"):
			continue
		where = {"docstatus": ["<", 2]}
		if filters.get("branch"):
			where["branch"] = filters["branch"]
		if filters.get("only_open"):
			where["order_status"] = ["!=", "Completed"]
		frm, to = report_kit.native_range(filters, "bon_date")
		if frm and to:
			where[date_field] = ["between", [frm, to]]
		elif frm or to:
			where[date_field] = [">=", frm] if frm else ["<=", to]
		for r in frappe.get_list(
			doctype,
			filters=where,
			fields=[f"{date_field} as bon_date", "booking", "emkl", "shipper",
				"container_summary as tanks", "order_status as status", "branch",
				"name as bon", *extra],
			limit_page_length=0,
		):
			r["kind"] = kind
			r["bon_doctype"] = doctype
			rows.append(r)

	# Bon Muat tidak menyimpan principal; ambil dari booking-nya.
	missing = {r["booking"] for r in rows if not r.get("principal") and r.get("booking")}
	if missing:
		owner = dict(frappe.get_all("Container Booking", filters={"name": ["in", list(missing)]},
					    fields=["name", "principal"], as_list=True))
		for r in rows:
			r.setdefault("principal", None)
			r["principal"] = r["principal"] or owner.get(r.get("booking"))
	if filters.get("principal"):
		rows = [r for r in rows if r.get("principal") == filters["principal"]]

	rows.sort(key=lambda r: (str(r["bon_date"] or ""), r["bon"]))
	return rows


def _columns() -> list:
	return [
		{"fieldname": "bon_date", "label": "Tanggal Bon", "fieldtype": "Date", "width": 110},
		{"fieldname": "kind", "label": "Jenis", "fieldtype": "Data", "width": 80},
		{"fieldname": "tanks", "label": "Tank", "fieldtype": "Data", "width": 220},
		{"fieldname": "principal", "label": "Principle", "fieldtype": "Link",
		 "options": "Customer", "width": 160},
		{"fieldname": "emkl", "label": "EMKL", "fieldtype": "Link", "options": "Customer",
		 "width": 160},
		{"fieldname": "shipper", "label": "Shipper", "fieldtype": "Link", "options": "Customer",
		 "width": 160},
		{"fieldname": "truck_plate", "label": "No. Pol", "fieldtype": "Data", "width": 110},
		{"fieldname": "driver_name", "label": "Supir", "fieldtype": "Data", "width": 130},
		{"fieldname": "destination", "label": "Tujuan", "fieldtype": "Data", "width": 130},
		{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 130},
		{"fieldname": "branch", "label": "Branch", "fieldtype": "Link", "options": "Branch",
		 "width": 110},
		{"fieldname": "booking", "label": "Booking", "fieldtype": "Link",
		 "options": "Container Booking", "width": 160},
		{"fieldname": "bon_doctype", "label": "Doctype", "fieldtype": "Data", "hidden": 1},
		{"fieldname": "bon", "label": "Bon", "fieldtype": "Dynamic Link",
		 "options": "bon_doctype", "width": 160},
	]


def _summary(rows) -> list:
	open_ = sum(1 for r in rows if r["status"] != "Completed")
	hold = sum(1 for r in rows if r["status"] == "Hold")
	return [
		{"label": "Total Bon", "value": len(rows), "datatype": "Int"},
		{"label": "Bongkar", "value": sum(1 for r in rows if r["kind"] == "Bongkar"),
		 "datatype": "Int", "indicator": "Green"},
		{"label": "Muat", "value": sum(1 for r in rows if r["kind"] == "Muat"),
		 "datatype": "Int", "indicator": "Blue"},
		{"label": "Belum Selesai", "value": open_, "datatype": "Int",
		 "indicator": "Orange" if open_ else "Green"},
		{"label": "Hold", "value": hold, "datatype": "Int", "indicator": "Red" if hold else "Green"},
	]
