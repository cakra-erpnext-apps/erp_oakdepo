"""Isi Reff Doc Cleaning / M&R terakhir di master tank dari order yang sudah ada.

Reff Doc adalah nomor dokumen milik CUSTOMER untuk satu pekerjaan — instruksi cuci dari
principal, persetujuan repair dari pemilik tank. Sejak Cleaning Order & M&R tidak lagi
mewarisi nomor dari EIR/booking (masing-masing punya kertasnya sendiri), nomor itu hanya
ada di order-nya; padahal yang bertanya biasanya menyebut TANK, bukan nomor order.

Dua field baru di Container menyimpannya per jenis order — sengaja tidak digabung jadi satu
"reff doc terakhir", karena keduanya datang dari kertas dan orang yang berbeda.

Cache-nya dihitung ulang dari sumber seperti pointer lain di ``last_orders`` — termasuk
KOSONG kalau order terakhir memang tidak mencantumkan Reff Doc — jadi backfill ini cukup
memanggil recompute yang sama dengan yang dijalankan doc_events, dan aman diulang.
"""

import frappe

from container_depot.container_depot.last_orders import refresh_container


def execute():
	frappe.reload_doc("container_depot", "doctype", "container")
	for i, name in enumerate(frappe.get_all("Container", pluck="name"), start=1):
		for source in ("Cleaning Order", "Repair Order"):
			refresh_container(name, only=source)
		# Armada satu depo bisa puluhan ribu tank — commit per batch supaya patch tidak
		# menahan satu transaksi sepanjang seluruh tabel.
		if i % 500 == 0:
			frappe.db.commit()
	frappe.db.commit()
