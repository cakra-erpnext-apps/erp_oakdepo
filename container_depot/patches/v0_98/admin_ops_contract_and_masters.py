"""Buka Depot Contract, Item dan Price List untuk Admin Ops.

Yang mengisi kontrak, tarif dan master Item saat go-live adalah Admin Ops, dan sampai
sekarang ia bahkan tidak punya izin BACA atas Depot Contract: doctype itu ada di
``FINANCE_DOCTYPES``, yang membuat ``_office_role_perms`` melewatinya sama sekali. Menunya
bukan sekadar tersembunyi — dokumennya tertutup. (Keputusan pemilik repo 2026-09-14.)

Tiga hal yang harus dilakukan pada site yang sudah jalan, karena tidak satu pun terjadi
sendiri:

1. **Depot Contract.** ``setup_permissions`` bersifat add-only per (doctype, role), jadi
   begitu "Depot Contract" keluar dari ``FINANCE_DOCTYPES`` barisnya memang akan lahir
   pada migrate berikutnya — tidak ada yang perlu ditambal di sini. Ditulis supaya orang
   berikutnya tidak mencarinya.

2. **Item / Price List / Item Price milik ERPNext.** Izinnya TIDAK boleh lewat Custom
   DocPerm: baris Custom DocPerm pertama pada sebuah doctype membuat Frappe mengabaikan
   seluruh izin bawaannya, jadi satu baris untuk Admin Ops akan mematikan Item Manager,
   Stock User dan seterusnya milik ERPNext. Jalurnya role standar lewat COMPANION_ROLES:
   ``Item Manager`` dan ``Sales Master Manager``. Yang kedua satu-satunya tingkat yang
   menyentuh ``Item Price`` sama sekali — doctype itu tidak punya tingkat baca-saja.

3. **``Sales Master Manager`` sedang di-park** (`restrict_to_domain = Unused`) sebagai
   "tingkat manager yang tidak dibagikan". Role yang naik ke COMPANION_ROLES harus keluar
   dari daftar itu DAN keluar dari domainnya di site yang terlanjur ter-seed.
"""

import frappe

from container_depot.install import (
	OFFICE_ROLES,
	push_role_profiles_to_users,
	setup_role_profiles,
	unpark_roles,
)

NEW_ROLES = ["Item Manager", "Sales Master Manager"]


def execute():
	unpark_roles(NEW_ROLES)
	# Menulis role baru ke profil Admin Ops (add-only, lihat setup_role_profiles).
	setup_role_profiles()
	# Dorong ke akun yang sudah memegang profilnya, jangan menunggu job latar.
	push_role_profiles_to_users(OFFICE_ROLES)
	frappe.db.commit()
