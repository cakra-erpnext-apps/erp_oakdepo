"""Register cuci per jenis — isi bersama untuk report Steam Wash / PP Wash / Methanol Rinse.

Tiga register ini selama ini hidup sebagai tiga sheet terpisah di *Tank Inventory at KIM*,
dengan bentuk yang sama persis: nomor tank, principal, tanggal order, tanggal cuci. Yang
membuatnya berguna justru KOLOM TANGGAL YANG KOSONG — di sheet Steam Wash, 512 dari 537
baris tidak pernah punya tanggal selesai. Itulah backlognya, dan itu satu-satunya tempat
backlog tersebut pernah terlihat.

Karena itu register di sini menampilkan order yang BELUM selesai juga, bukan hanya yang
sudah — sebuah "laporan cuci" yang hanya memuat pekerjaan selesai justru menghapus
pertanyaannya. Ringkasan di atas memecahnya jadi tiga angka, dan yang belum selesai merah.

Satu order dianggap milik sebuah jenis lewat DUA jalur, sama seperti report Inventory KPI
per Principal:

* ``Cleaning Order.cleaning_type`` — jenis di header, disetel Admin Ops di Service Setup;
* item CODE service yang dipilih (``INT-STEAM`` dst.) — untuk order yang headernya masih
  Standard Cleaning (nilai default setiap order baru) tapi jelas memuat service tersebut.

Tidak pernah lewat NAMA item: nama item milik finance dan bisa berubah kapan saja, dan
pencocokan nama persis bug yang membuat kolom PP / Methanol / Steam di report KPI selalu
nol selama berbulan-bulan.

Tanpa ``wash_type`` modul ini jadi Cleaning Register: SEMUA order cleaning, termasuk
Standard Cleaning / Other yang tidak masuk register jenis mana pun.

Semua tanggal di sini tanggal order itu sendiri (``plan_date``, "Tanggal Cleaning"), bukan
jam order dibuat atau jam selesai cuci (user, 2026-10-07). Kolom tanggal cuci = tanggal itu
juga, tapi HANYA setelah order selesai — kosongnya tetap penanda backlog.
"""

from __future__ import annotations

import frappe

from container_depot.container_depot import report_kit
from container_depot.container_depot.container_status import DONE_CLEANING


def execute(filters, *, wash_type: str | None, item_code: str | None, date_label: str):
	filters = filters or {}
	default = "plan_date"
	columns, rows = report_kit.finish(
		_columns(date_label, all_types=not wash_type), _rows(filters, wash_type, item_code, default),
		filters, default=default,
	)
	return columns, rows, None, None, _summary(rows)


def _rows(filters, wash_type, item_code, default) -> list:
	where = ["co.docstatus < 2", "co.status != 'Cancelled'"]
	params = {"wash_type": wash_type, "item_code": item_code, "done": tuple(DONE_CLEANING)}
	if wash_type:
		where.append(
			"(co.cleaning_type = %(wash_type)s OR EXISTS ("
			"   SELECT 1 FROM `tabCleaning Order Service` cos"
			"   WHERE cos.parent = co.name AND cos.cleaning_item = %(item_code)s))"
		)

	# Dipakai dialog riwayat per tank (register_history.tank_history), bukan oleh filter
	# di layar: register itu sendiri selalu dibaca per depo, bukan per tank.
	if filters.get("container"):
		where.append("co.container = %(container)s")
		params["container"] = filters["container"]
	if filters.get("principal"):
		where.append("COALESCE(NULLIF(co.container_principal, ''), c.principal) = %(principal)s")
		params["principal"] = filters["principal"]
	if filters.get("depot"):
		where.append("COALESCE(NULLIF(co.depot, ''), c.depot) = %(depot)s")
		params["depot"] = filters["depot"]
	# Only while the range is on Tanggal Cleaning; on another date column report_kit.finish
	# filters the rows instead.
	frm, to = report_kit.native_range(filters, "plan_date", default)
	if frm:
		where.append("co.plan_date >= %(from_date)s")
		params["from_date"] = frm
	if to:
		where.append("co.plan_date <= %(to_date)s")
		params["to_date"] = to
	if filters.get("only_outstanding"):
		where.append("co.status != 'Completed'")

	return frappe.db.sql(
		f"""
		SELECT
			co.container AS tank_no,
			COALESCE(NULLIF(co.container_principal, ''), c.principal) AS principal,
			co.cleaning_type AS cleaning_type,
			co.plan_date AS plan_date,
			IF(co.status IN %(done)s, co.plan_date, NULL) AS wash_date,
			co.status AS status,
			co.name AS cleaning_order,
			co.sales_invoice AS sales_invoice
		FROM `tabCleaning Order` co
		LEFT JOIN `tabContainer` c ON co.container = c.name
		WHERE {' AND '.join(where)}
		ORDER BY co.plan_date ASC, co.creation ASC
		""",
		params,
		as_dict=True,
	)


def _columns(date_label, all_types=False) -> list:
	# Register semua jenis butuh kolom jenisnya; register per jenis tidak — isinya satu jenis.
	kind = [{"fieldname": "cleaning_type", "label": "Jenis Cleaning", "fieldtype": "Data",
		 "width": 140}] if all_types else []
	return [
		{"fieldname": "tank_no", "label": "Tank No", "fieldtype": "Link",
		 "options": "Container", "width": 140},
		{"fieldname": "principal", "label": "Principle", "fieldtype": "Link",
		 "options": "Customer", "width": 180},
		*kind,
		{"fieldname": "plan_date", "label": "Tanggal Cleaning", "fieldtype": "Date", "width": 110},
		# Label kolom mengikuti jenisnya ("Steam Wash Date" dst.) supaya halamannya terbaca
		# sama seperti sheet yang digantikannya.
		{"fieldname": "wash_date", "label": date_label, "fieldtype": "Date", "width": 130},
		{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 120},
		{"fieldname": "cleaning_order", "label": "Cleaning Order", "fieldtype": "Link",
		 "options": "Cleaning Order", "width": 150},
		{"fieldname": "sales_invoice", "label": "Invoice", "fieldtype": "Link",
		 "options": "Sales Invoice", "width": 150},
	]


def _summary(rows) -> list:
	"""Tiga angka yang menjadikan halaman ini watcher, bukan arsip.

	"Belum selesai" merah walaupun nol: nol di sana adalah kabar baik yang pantas dibaca,
	dan warna yang berubah membuat angkanya diperhatikan."""
	done = sum(1 for r in rows if r["status"] in DONE_CLEANING)
	return [
		{"label": "Total Order", "value": len(rows), "datatype": "Int"},
		{"label": "Selesai", "value": done, "datatype": "Int", "indicator": "Green"},
		{"label": "Belum Selesai", "value": len(rows) - done, "datatype": "Int",
		 "indicator": "Red" if len(rows) - done else "Green"},
	]
