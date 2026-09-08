"""Cap ``job_type = Repair`` pada Repair Order lama yang belum punya nilainya.

Uji berkala 2,5 / 5 tahun tetap dibukukan sebagai M&R — patch v0_66 menurunkan doctype
``Periodic Test Order`` secara sadar dan itu tidak dibangkitkan lagi. Yang tersisa dari
pemisahannya hanyalah ``Repair Order.job_type``, dipakai filter list view "Jenis Pekerjaan";
baris kosong di filter itulah yang dibereskan di sini.

Patch ini dulu juga menyemai Depot Service Menu "Periodic Test" untuk memisahkan KATALOG
ITEM uji berkala dari katalog sparepart. Seluruh fitur Depot Service Menu dihapus pada
2026-09-07 (picker item kini menampilkan seluruh katalog, lihat
``container_depot.item_catalog`` dan patch v0_92) — jadi bagian itu ikut dilepas dari sini.
Nama modulnya sengaja tidak diubah: mengganti nama patch yang sudah tercatat di Patch Log
membuatnya jalan lagi di setiap site lama.

Idempoten: run kedua tidak menemukan Repair Order tanpa job_type.
"""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.has_column("Repair Order", "job_type"):
		return
	for name in frappe.get_all(
		"Repair Order", filters={"job_type": ["in", ["", None]]}, pluck="name"
	):
		# Koreksi data, bukan perubahan bisnis — jejak audit tidak digeser.
		frappe.db.set_value("Repair Order", name, "job_type", "Repair", update_modified=False)
	frappe.db.commit()
