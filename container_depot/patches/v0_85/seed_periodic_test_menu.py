"""Menu item picker "Periodic Test" + ``job_type`` pada Repair Order yang sudah ada.

Uji berkala 2,5 / 5 tahun tetap dibukukan sebagai M&R — patch v0_66 menurunkan doctype
``Periodic Test Order`` secara sadar dan itu tidak dibangkitkan lagi. Yang dipisah di sini
hanya KATALOG ITEM-nya: satu picker yang harus melayani perbaikan sekaligus uji berkala
memaksa teknisi menyaring seluruh katalog sparepart untuk mencari dua baris testing.

Karena ``mr.py`` memilih menu dari ``Repair Order.job_type``, dokumen lama yang belum
punya nilai harus dicap ``Repair`` — kalau tidak, picker-nya jatuh ke fallback dan diam-
diam berubah perilaku untuk order yang sudah berjalan. (Fallback ``MR_MENU_BY_JOB.get(...,
MR_MENU)`` sudah menjaga hal yang sama di sisi kode; ini menuntaskannya di data, sekaligus
membuat filter list view "Jenis Pekerjaan" tidak menampilkan baris kosong.)

Menu-nya sengaja lahir KOSONG, tanpa satu pun Item Group. Menu kosong tidak memfilter apa
pun (``service_menu.is_real_menu``), jadi picker tetap terbuka sampai operator memetakan
group-nya di Desk. Menebak group di dalam patch adalah kegagalan yang sudah terjadi sekali
(v0_34): nama group yang ditebak seeder lama diganti rate card asli si customer, dan setiap
install baru diam-diam mendapat menu yang menunjuk ke ketiadaan.

Idempoten: ``seed_default_menus`` hanya membuat yang belum ada dan tidak pernah menyentuh
menu yang sudah dipetakan operator; run kedua tidak menemukan Repair Order tanpa job_type.
"""

from __future__ import annotations

import frappe

from container_depot.container_depot.service_menu import seed_default_menus


def execute():
	seed_default_menus()

	if not frappe.db.has_column("Repair Order", "job_type"):
		return
	for name in frappe.get_all(
		"Repair Order", filters={"job_type": ["in", ["", None]]}, pluck="name"
	):
		# Koreksi data, bukan perubahan bisnis — jejak audit tidak digeser.
		frappe.db.set_value("Repair Order", name, "job_type", "Repair", update_modified=False)
	frappe.db.commit()
