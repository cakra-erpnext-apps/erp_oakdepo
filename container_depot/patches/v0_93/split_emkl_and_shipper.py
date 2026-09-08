"""Satu kolom ``shipper`` dipecah jadi dua: ``emkl`` (angkutan) dan ``shipper`` (pabrik).

Sampai sekarang setiap dokumen cuma punya SATU field bernama ``shipper``, dan isinya
sebenarnya EMKL — perusahaan trucking yang menarik tank. Yang tidak pernah tercatat di mana
pun adalah pabrik yang MEMERINTAH EMKL itu, padahal itulah pihak yang sebetulnya punya
muatan. Sejak sekarang keduanya berdiri sendiri:

* ``emkl``    — Ekspedisi Muatan Kapal Laut / angkutan. Ini yang ikut Customer (Bill To):
                sudah begitu perilakunya sejak dulu, hanya namanya yang salah.
* ``shipper`` — pabrik tempat muat barang. TIDAK punya default: Bill To adalah yang membayar,
                bukan yang mengirim, jadi menurunkannya dari sana cuma akan mencetak nama
                yang keliru tapi masuk akal di setiap baris.

Karena itu isi lama PINDAH ke ``emkl``, bukan disalin: nilainya memang EMKL. Kolom
``shipper`` ditinggalkan kosong supaya yang mengisinya adalah orang yang tahu pabriknya —
kosong yang jujur lebih baik daripada tebakan yang rapi.

``rename_field`` tidak dipakai: begitu ``bench migrate`` menyinkronkan doctype-nya, kolom
``emkl`` sudah lahir (kosong) di samping ``shipper``, jadi rename akan bentrok. Satu UPDATE
per tabel memindahkan isinya sekaligus mengosongkan yang lama.

Idempoten: setelah jalan, baris yang punya data sudah ber-``emkl``, sehingga syarat
``emkl`` kosong tidak lagi terpenuhi dan pengulangan tidak menyentuh apa pun — termasuk
``shipper`` yang sesudah ini diisi orang.

Terakhir: ``List View Settings`` yang pernah disetel orang menyimpan pilihan kolomnya
sendiri dan sejak itu dialah yang menentukan, jadi kolom "Shipper" di daftar bon ditukar ke
"EMKL" di situ juga — kalau tidak, daftar bon memperlihatkan kolom yang selamanya kosong.
"""

from __future__ import annotations

import json

import frappe

# Container Booking Item dipakai dua parent sekaligus (Container Booking.items dan
# Order Bongkar.containers), jadi satu tabel ini menutup keduanya.
TABLES = (
	"Container Booking Item",
	"Order Muat",
	"Order Bongkar",
	"Inspection",
	"Container",
)

# Doctype yang punya kolom daftar — di sinilah pilihan kolom tersimpan per site.
LIST_VIEWS = ("Order Muat", "Order Bongkar")


def execute():
	for doctype in TABLES:
		columns = frappe.db.get_table_columns(doctype)
		if "emkl" not in columns or "shipper" not in columns:
			continue
		frappe.db.sql(
			f"""
			UPDATE `tab{doctype}`
			   SET emkl = shipper, shipper = NULL
			 WHERE (emkl IS NULL OR emkl = '')
			   AND shipper IS NOT NULL AND shipper != ''
			"""
		)
	frappe.db.commit()

	for doctype in LIST_VIEWS:
		_swap_list_column(doctype)


def _swap_list_column(doctype: str):
	"""Tukar kolom ``shipper`` jadi ``emkl`` pada pilihan kolom yang tersimpan."""
	if not frappe.db.exists("List View Settings", doctype):
		return  # belum pernah disetel: `in_list_view` di doctype yang berlaku
	doc = frappe.get_doc("List View Settings", doctype)
	fields = json.loads(doc.fields or "[]")
	if any(f.get("fieldname") == "emkl" for f in fields):
		return
	changed = False
	for f in fields:
		if f.get("fieldname") == "shipper":
			f["fieldname"] = "emkl"
			f["label"] = "EMKL / Angkutan"
			changed = True
	if changed:
		doc.fields = json.dumps(fields)
		doc.save(ignore_permissions=True)
