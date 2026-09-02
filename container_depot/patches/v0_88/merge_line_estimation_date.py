"""Satukan dua tanggal per baris booking jadi satu ``estimation_date``.

Baris container sempat punya dua field tanggal: ``tanggal_bongkar`` (lama) dan
``tanggal_muat`` (ditambahkan supaya booking KELUAR punya tanggalnya sendiri). Yang satu
selalu kosong, karena sebuah booking cuma punya satu arah — dan yang kosong itu muncul
sebagai kolom mati di grid yang harus disembunyikan lewat toggle supaya tidak
membingungkan. Satu field sudah cukup: arah booking-nya yang menentukan artinya (hari tank
dibongkar untuk Tank In, hari tank diambil untuk Tank Out), dan yang berubah cuma LABEL-nya
— itu diatur form.

Perpindahan datanya:

1. baris yang punya ``tanggal_bongkar`` → ``estimation_date`` (semua data lama, kedua arah:
   sebelum ``tanggal_muat`` ada, booking keluar pun memakai kolom ini);
2. baris milik booking Tank Out yang sempat mengisi ``tanggal_muat`` → menimpa, karena
   itulah tanggal yang benar untuk baris tersebut;
3. dua kolom lamanya dibuang beserta Property Setter / Custom Field yang menempel padanya.

Idempoten: kalau kolom lamanya sudah tidak ada, tidak ada yang dikerjakan.
"""

from __future__ import annotations

import frappe

CHILD = "Container Booking Item"
NEW = "estimation_date"
OLD = ("tanggal_bongkar", "tanggal_muat")


def execute():
	if not frappe.db.has_column(CHILD, NEW):
		# Sinkronisasi doctype belum sempat jalan — tidak ada tujuan untuk memindahkan data.
		return

	if frappe.db.has_column(CHILD, "tanggal_bongkar"):
		frappe.db.sql(
			f"""
			UPDATE `tab{CHILD}`
			   SET `{NEW}` = tanggal_bongkar
			 WHERE `{NEW}` IS NULL AND tanggal_bongkar IS NOT NULL
			"""
		)
	if frappe.db.has_column(CHILD, "tanggal_muat"):
		# Hanya baris booking keluar: Order Bongkar memakai child doctype yang sama, dan
		# baris bon masuk tidak pernah punya tanggal muat yang berarti.
		frappe.db.sql(
			f"""
			UPDATE `tab{CHILD}` r
			  JOIN `tabContainer Booking` b
				ON b.name = r.parent AND r.parenttype = 'Container Booking'
			   SET r.`{NEW}` = r.tanggal_muat
			 WHERE b.direction = 'Tank Out' AND r.tanggal_muat IS NOT NULL
			"""
		)

	for fieldname in OLD:
		for dt, filters in (
			("Custom Field", {"dt": CHILD, "fieldname": fieldname}),
			("Property Setter", {"doc_type": CHILD, "field_name": fieldname}),
		):
			for name in frappe.get_all(dt, filters=filters, pluck="name"):
				frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
		if frappe.db.has_column(CHILD, fieldname):
			frappe.db.sql_ddl(f"ALTER TABLE `tab{CHILD}` DROP COLUMN `{fieldname}`")

	frappe.db.commit()
