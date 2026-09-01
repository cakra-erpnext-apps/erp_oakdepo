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
"""

from __future__ import annotations

import frappe

from container_depot.container_depot.container_status import DONE_CLEANING


def execute(filters, *, wash_type: str, item_code: str, date_label: str):
	filters = filters or {}
	rows = _rows(filters, wash_type, item_code)
	return _columns(date_label), rows, None, None, _summary(rows)


def _rows(filters, wash_type, item_code) -> list:
	where = [
		"co.docstatus < 2",
		"co.status != 'Cancelled'",
		"(co.cleaning_type = %(wash_type)s OR EXISTS ("
		"   SELECT 1 FROM `tabCleaning Order Service` cos"
		"   WHERE cos.parent = co.name AND cos.cleaning_item = %(item_code)s))",
	]
	params = {"wash_type": wash_type, "item_code": item_code}

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
	if filters.get("from_date"):
		where.append("DATE(co.order_created) >= %(from_date)s")
		params["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		where.append("DATE(co.order_created) <= %(to_date)s")
		params["to_date"] = filters["to_date"]
	if filters.get("only_outstanding"):
		where.append("co.status != 'Completed'")

	return frappe.db.sql(
		f"""
		SELECT
			co.container AS tank_no,
			COALESCE(NULLIF(co.container_principal, ''), c.principal) AS principal,
			DATE(co.order_created) AS order_date,
			co.plan_date AS plan_date,
			DATE(co.cleaning_end) AS wash_date,
			co.status AS status,
			co.name AS cleaning_order,
			co.sales_invoice AS sales_invoice
		FROM `tabCleaning Order` co
		LEFT JOIN `tabContainer` c ON co.container = c.name
		WHERE {' AND '.join(where)}
		ORDER BY co.order_created ASC
		""",
		params,
		as_dict=True,
	)


def _columns(date_label) -> list:
	return [
		{"fieldname": "tank_no", "label": "Tank No", "fieldtype": "Link",
		 "options": "Container", "width": 140},
		{"fieldname": "principal", "label": "Principle", "fieldtype": "Link",
		 "options": "Customer", "width": 180},
		{"fieldname": "order_date", "label": "Order Date", "fieldtype": "Date", "width": 110},
		# Rencana, di sebelah realisasinya: baris tanpa tanggal cuci tapi punya rencana
		# adalah pekerjaan yang sudah dijadwalkan; yang tidak punya keduanya belum.
		{"fieldname": "plan_date", "label": "Plan Date", "fieldtype": "Date", "width": 110},
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
