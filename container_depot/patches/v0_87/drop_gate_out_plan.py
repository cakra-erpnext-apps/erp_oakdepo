"""Hapus total Gate Out Plan — fungsinya pindah ke Container Booking (Tank Out).

Gate Out Plan adalah dokumen pemberitahuan: customer mengabari tank mana yang akan diambil
dan kira-kira kapan, supaya depo bisa mendahulukan cleaning / M&R-nya. Ia tidak
mengotorisasi apa pun — yang mengeluarkan tank tetap Container Booking (Tank Out) yang harus
dibuat menyusul dari plan itu. Jadi satu pekerjaan dicatat dua kali, di dua dokumen yang
mengatakan hal yang sama tentang tank yang sama, dan satu-satunya efek nyata si plan —
menstempel ``target_lift_on`` ke Container — sekarang dilakukan booking-nya sendiri sejak
draft (``container_depot.container_depot.lift_on``).

Yang ikut pindah lebih dulu (lihat commit yang mendahului patch ini):

* stempel prioritas lift-on + dorongannya ke order yang masih terbuka;
* tab "Order & EIR Terkait" per container (``tank_documents``);
* "% Keluar" dan penutupan otomatis saat semua tank keluar gate;
* jalur email → order: pilihan **Gate Out** kini membuat Container Booking Tank Out;
* Gate Out Plan Register → **Lift On Register** atas booking keluar.

Yang dihapus di sini adalah sisanya: dua doctype (induk + baris), report lamanya, number
card-nya, dan dua field Link yang menunjuk ke sana. Datanya ikut hilang — itu keputusan
yang diambil sadar: plan tidak pernah menjadi bukti apa pun, jejak yang berarti (booking,
bon, EIR, Container Activity) hidup di dokumen lain, dan menyisakan doctype kosong hanya
untuk arsip berarti menyisakan menu yang membingungkan operator.

Idempoten: setiap langkah memeriksa dulu apakah sasarannya masih ada.
"""

from __future__ import annotations

import frappe

DOCTYPES = ("Gate Out Plan Item", "Gate Out Plan")  # child first
REPORT = "Gate Out Plan Register"
NUMBER_CARD = "Gate Out Plan Open"

# Field Link yang menunjuk ke doctype yang mau dihapus. Ditinggalkan, ia jadi kolom yang
# menunjuk ke tabel yang tidak ada lagi — dan penyimpanan berikutnya atas dokumen itu mati
# di validasi link.
DEAD_LINKS = (
	# Container.gate_out_plan digantikan Container.lift_on_booking (diisi lift_on.py).
	("Container", "gate_out_plan"),
	# Container Booking.gate_out_plan menandai booking yang lahir dari sebuah plan.
	("Container Booking", "gate_out_plan"),
)


def execute():
	_drop_dead_links()
	_drop_report()
	_drop_number_card()
	_drop_doctypes()
	frappe.db.commit()


def _drop_dead_links():
	"""Buang field Link yang menunjuk ke doctype yang akan dihapus.

	Frappe tidak membuang kolomnya sendiri ketika sebuah field hilang dari JSON — kolom itu
	tinggal sebagai yatim. Di sini kolomnya dibuang sekalian: ini penghapusan total, dan
	sebuah kolom bernama ``gate_out_plan`` yang berisi NULL cuma akan membuat orang berikutnya
	yang membaca skema bertanya-tanya doctype apa itu.
	"""
	for doctype, fieldname in DEAD_LINKS:
		# Custom Field / Property Setter yang mungkin dibuat orang di atasnya harus pergi
		# lebih dulu — keduanya akan menghidupkan kembali field-nya di sinkronisasi berikutnya.
		for dt, filters in (
			("Custom Field", {"dt": doctype, "fieldname": fieldname}),
			("Property Setter", {"doc_type": doctype, "field_name": fieldname}),
		):
			for name in frappe.get_all(dt, filters=filters, pluck="name"):
				frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
		if frappe.db.has_column(doctype, fieldname):
			frappe.db.sql_ddl(f"ALTER TABLE `tab{doctype}` DROP COLUMN `{fieldname}`")


def _drop_report():
	if frappe.db.exists("Report", REPORT):
		frappe.delete_doc("Report", REPORT, force=True, ignore_permissions=True)


def _drop_number_card():
	if frappe.db.exists("Number Card", NUMBER_CARD):
		# Kartu ini juga dipasang di workspace Container Inventory; barisnya ikut dibuang
		# supaya workspace tidak merender kartu yang sudah tidak ada.
		frappe.db.delete("Workspace Number Card", {"number_card_name": NUMBER_CARD})
		frappe.delete_doc("Number Card", NUMBER_CARD, force=True, ignore_permissions=True)


def _drop_doctypes():
	for doctype in DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		# Baris-barisnya dulu: delete_doc atas DocType tidak menghapus dokumennya, dan sebuah
		# tabel yang tertinggal akan muncul lagi sebagai "orphan doctype" di migrate berikutnya.
		if frappe.db.table_exists(doctype):
			frappe.db.sql(f"DELETE FROM `tab{doctype}`")
		frappe.db.delete("Custom DocPerm", {"parent": doctype})
		frappe.db.delete("DocPerm", {"parent": doctype})
		frappe.delete_doc("DocType", doctype, force=True, ignore_permissions=True)
		if frappe.db.table_exists(doctype):
			frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{doctype}`")
