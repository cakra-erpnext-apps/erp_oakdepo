"""Isi ``Cleaning Order.cleaning_type`` untuk seluruh order yang sudah ada.

Field ini BUKAN field baru: ia sudah ada sejak v0.2, lalu dipensiunkan (``hidden``,
label "Cleaning Type (lama)") ketika metode cleaning pindah ke tabel anak
``Cleaning Order Service``. Sekarang ia dihidupkan lagi — bukan sebagai pengganti tabel
service, melainkan sebagai satu penanda JENIS di header: Standard Cleaning (order yang
lahir otomatis dari EIR-In tank kotor) versus tiga wash khusus yang diminta principal
lewat email atas tank yang sudah bersih (PP Wash / Methanol Rinse / Steam Wash). Ketiga
register manual itu — sheet ``Methanol Rinse`` / ``PP Wash`` / ``Steam Wash`` di
*Tank Inventory at KIM* — selama ini hidup di luar sistem justru karena header order
tidak bisa menjawab "ini cuci jenis apa" tanpa membuka tabel servicenya.

Karena field-nya lama, kolomnya sudah berisi data lama, dan patch ini yang merapikannya:

1. Empat opsi yang dibuang dari daftar Select (``Hot Water``, ``Chemical``,
   ``Detergent``, ``Nitrogen Purge``) → ``Other``. Keempatnya tidak dipakai di register
   manual mana pun dan tidak punya Item padanan di rate card, tapi nilainya TIDAK dihapus
   diam-diam: sebuah nilai yang tidak ada di ``options`` membuat form Desk menolak simpan
   dengan "not a valid value", jadi meninggalkannya berarti memblokir order lama.
2. Order yang jenisnya kosong → disimpulkan dari item service yang dipilih, dikunci ke
   item CODE (``INT-PP-WASH`` / ``INT-METHANOL`` / ``INT-STEAM``), bukan ``item_name``.
   Nama item bisa diedit finance kapan saja; matching lewat nama persis bug yang membuat
   kolom PP / Methanol / Steam di report Inventory KPI per Principal selalu nol.
3. Sisa yang masih kosong → ``Standard Cleaning``.

Semua tulisan pakai ``update_modified=False``: ini koreksi data, bukan perubahan bisnis,
dan menggeser ``modified`` akan membuat setiap order lama tampak baru saja disentuh
seseorang di jejak audit. Idempoten — run kedua tidak menemukan baris untuk dikerjakan.
"""

from __future__ import annotations

import frappe

from container_depot.container_depot.doctype.cleaning_order.cleaning_order import (
	_WASH_TYPE_BY_ITEM,
)

# Opsi lama yang tidak punya padanan di daftar baru (lihat v0_6, yang justru
# mengkanonkan sebagian nilai ini dari Select yang lebih tua lagi).
_RETIRED = ("Hot Water", "Chemical", "Detergent", "Nitrogen Purge")


def execute():
	if not frappe.db.has_column("Cleaning Order", "cleaning_type"):
		return

	for name in frappe.get_all(
		"Cleaning Order", filters={"cleaning_type": ["in", _RETIRED]}, pluck="name"
	):
		frappe.db.set_value("Cleaning Order", name, "cleaning_type", "Other", update_modified=False)

	blank = frappe.get_all(
		"Cleaning Order", filters={"cleaning_type": ["in", ["", None]]}, pluck="name"
	)
	if not blank:
		frappe.db.commit()
		return

	# Satu query untuk semua servicenya; urutan baris (idx) menentukan siapa yang menang
	# kalau satu order memilih lebih dari satu wash khusus — sama dengan yang dilakukan
	# CleaningOrder._derive_cleaning_type() saat order disimpan.
	derived: dict[str, str] = {}
	rows = frappe.get_all(
		"Cleaning Order Service",
		filters={"parent": ["in", blank], "cleaning_item": ["in", list(_WASH_TYPE_BY_ITEM)]},
		fields=["parent", "cleaning_item", "idx"],
		order_by="parent asc, idx asc",
	)
	for row in rows:
		derived.setdefault(row.parent, _WASH_TYPE_BY_ITEM[row.cleaning_item])

	for name in blank:
		frappe.db.set_value(
			"Cleaning Order",
			name,
			"cleaning_type",
			derived.get(name, "Standard Cleaning"),
			update_modified=False,
		)

	frappe.db.commit()
