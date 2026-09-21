"""Siapa yang boleh MELIHAT DAFTAR User.

Frappe memberi role `Desk User` izin `select` pada doctype User supaya picker link
(Assign To, Share, filter Owner, mention) bisa mencari orang. Yang jarang disadari:
`db_query._set_permission_map` menerima `select` SEBAGAI PENGGANTI `read`, dan list view
Desk memakai endpoint yang sama (`frappe.desk.reportview.get`). Jadi setiap akun — termasuk
akun customer — bisa mengetik /app/user/view/list dan mendapat seluruh direktori staf
lengkap dengan emailnya, walaupun DocPerm-nya cuma `select`.

Dua aturan, karena "picker" berarti hal yang berbeda untuk dua jenis akun:

* **Akun internal** (staf OAK) — hanya jalur DAFTAR yang ditutup. Picker dibiarkan utuh:
  tanpa itu dialog Assign To, Share dan filter Owner kosong untuk semua orang yang bukan
  System Manager, dan itu memutus pekerjaan kantor yang sah. Bedanya dibaca dari endpoint
  yang memanggil, karena `permission_query_conditions` sendiri tidak tahu siapa peneleponnya.
* **Akun eksternal** (portal customer — dikenali dari User Permission `Customer`-nya, lihat
  customer_scope) — SEMUA jalur ditutup, picker termasuk. Tidak ada satu pun pekerjaan
  pelanggan yang perlu memilih pegawai OAK, dan direktori staf adalah persis yang tidak
  boleh keluar. Yang tersisa untuknya cuma dirinya sendiri, supaya kolom seperti "Dibuat
  oleh" di dokumennya tetap bisa dibaca.

Mention (`@`) tidak lewat sini sama sekali: `frappe.desk.search.get_names_for_mentions`
membaca daftar yang di-cache lewat `frappe.get_all` (ignore_permissions), jadi ia ditutup
lewat `override_whitelisted_methods` di bawah.

Membuka SATU dokumen User lewat URL tidak lewat sini dan memang sudah tertutup: akun biasa
tidak punya `read`, dan satu-satunya dokumen User yang bisa ia buka adalah miliknya sendiri
lewat DocShare yang dibuat Frappe (lihat public/js/user.js bagian 3).
"""

from __future__ import annotations

import frappe

from container_depot import desk_surface

def _is_external(user: str) -> bool:
	"""Akun portal customer, bukan staf OAK — penandanya User Permission `Customer`-nya."""
	from container_depot import customer_scope

	return bool(customer_scope.get_user_customers(user))


def user_query(user=None, doctype=None) -> str:
	"""Daftar User = dirinya sendiri, untuk akun yang cuma punya `select`.

	Menyaring, bukan melempar `PermissionError`. Melempar sempat dicoba dan memang menutup
	datanya, tapi list view Desk menjawab 403 itu dengan kerangka halaman yang menggantung
	plus dialog "Not permitted" — dua lapis pesan untuk satu penolakan. Halamannya sendiri
	ditutup di klien (``public/js/user_list.js``, lewat flag boot
	``depot_block_user_list``), dan baris yang tersisa di sini adalah jaring pengaman untuk
	pemanggil API yang tidak lewat halaman itu.
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return ""
	# `only_has_select_perm` adalah pembeda yang dipakai db_query sendiri: benar persis untuk
	# akun yang lolos ke sini lewat `select` milik `Desk User`, dan salah untuk System Manager
	# yang memang punya `read`.
	if not frappe.only_has_select_perm("User", user=user):
		return ""
	if not (_is_external(user) or desk_surface.is_list_request()):
		return ""
	return f"`tabUser`.name = {frappe.db.escape(user, percent=False)}"


def get_names_for_mentions(search_term):
	"""`@sebutan` untuk akun portal: kosong. Untuk yang lain: apa adanya.

	Dipasang lewat `override_whitelisted_methods` karena daftar aslinya tidak bisa disaring
	`permission_query_conditions`: `get_users_for_mentions` membacanya dengan
	`frappe.get_all` (ignore_permissions) DAN menyimpannya di cache global, jadi satu daftar
	yang sama dipakai ulang untuk semua akun.
	"""
	if _is_external(frappe.session.user):
		return []
	from frappe.desk.search import get_names_for_mentions as _core

	return _core(search_term)
