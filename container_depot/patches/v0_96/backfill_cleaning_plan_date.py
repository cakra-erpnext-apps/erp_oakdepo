"""Isi Cleaning Plan Date order lama yang masih kosong.

Sejak field-nya wajib (`reqd`), order yang lahir sebelum aturan ini — termasuk yang dibuat
otomatis dari EIR tank kotor, yang memang tidak pernah mengisinya — tidak bisa disimpan
ulang sampai seseorang mengetik tanggalnya. Padahal yang menghalangi bukan keputusan yang
belum diambil, melainkan kolom yang dulu boleh kosong.

Diisi dari tanggal order itu dibuat, bukan hari ini: order Februari yang dibaca hari ini
direncanakan bulan Februari, dan menstempelnya hari ini akan membuatnya muncul di jadwal
hari ini seolah pekerjaan baru. `order_created` adalah stempelnya sendiri; `creation`
dipakai kalau bahkan itu pun kosong.

SQL langsung: ini pengisian kolom, bukan perubahan keadaan order — tidak ada hook yang
perlu jalan, dan menyentuh `modified` hanya akan membuat seluruh tabel terlihat baru
diubah.
"""

import frappe


def execute():
	frappe.reload_doc("container_depot", "doctype", "cleaning_order")
	frappe.db.sql(
		"""
		update `tabCleaning Order`
		set plan_date = date(coalesce(order_created, creation))
		where plan_date is null
		"""
	)
	frappe.db.commit()
