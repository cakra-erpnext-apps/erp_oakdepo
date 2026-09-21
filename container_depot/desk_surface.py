"""Berapa besar Desk yang boleh dibuka satu akun.

Frappe memberi role otomatis `All` dan `Desk User` izin baca pada puluhan doctype yang tidak
pernah diberikan siapa pun: begitu sebuah app dipasang, doctype-nya ikut terbaca oleh SETIAP
System User di site ini. Di site ini isinya antara lain tiket support app lain (`HD Ticket`),
jatah cuti (`Leave Ledger Entry`), enam doctype `Quality *`, `Token Cache`, `Connected App`.
Menu-nya memang tidak menampilkan semua itu — tapi rutenya ada, dan mengetik
`/desk/hd-ticket` atau `/desk/report` cukup untuk membukanya.

Dua tuas dipakai bersama, karena satu saja tidak menutup apa-apa:

1. **Rutenya dihapus.** `frappe.router.setup()` membangun daftar rute doctype dari
   `frappe.boot.user.can_read` — jadi doctype yang dibuang dari daftar itu tidak punya rute
   untuk diketik, dan Desk menjawabnya sebagai halaman tidak dikenal. Ini yang mematikan
   `/desk/report`, `/desk/workspace`, `/desk/hd-ticket` dan sisanya sekaligus.
2. **Pembacaan DAFTAR-nya dikosongkan** lewat hook `*` `permission_query_conditions`, supaya
   yang memanggil endpoint list langsung (tanpa lewat rute Desk) juga tidak dapat apa-apa.

Yang TIDAK ikut ditutup, dan sengaja:

* **Picker** (`search_link`), pemuatan form, dan `frappe.get_all` internal app. Doctype master
  seperti `UOM`, `Territory` atau `Item Group` harus tetap bisa DIPILIH di form yang memang
  boleh dibuka — menutupnya berarti mengosongkan picker dan mematahkan pekerjaan yang sah,
  bukan menutup kebocoran. Bedanya dibaca dari endpoint pemanggil (`_is_list_request`).
* **Akun customer**, yang aturannya lebih ketat dan sudah punya rumahnya sendiri
  (`customer_scope.foreign_doctype_query` / `_is_foreign`). Modul ini mendelegasikan ke sana.
* **System Manager dan Administrator**, yang memang mengurus site-nya.

Yang dianggap "boleh": doctype yang salah satu role TERTUGAS milik akun itu memberi izin baca
(role otomatis `All`/`Desk User`/`Guest` tidak dihitung — justru merekalah sumber kebocoran
ini), ditambah modul rakitan Desk di `_PLUMBING_MODULES`, yang isinya dipakai Desk sendiri:
File, Communication, ToDo, Note, Tag, dashboard, workspace, print format, template email,
Contact/Address untuk form ERPNext. Sebuah allowlist, bukan daftar pelanggar: app yang
dipasang besok ikut tertutup tanpa kode baru.
"""

from __future__ import annotations

import frappe

# Role yang dipasang Frappe sendiri ke setiap akun. Izin yang datang HANYA dari sini bukan
# izin yang diberikan siapa pun, dan itulah yang modul ini tutup.
_AUTOMATIC_ROLES = {"All", "Desk User", "Guest", "Administrator"}

# Modul yang isinya dipakai Desk untuk bekerja, bukan data bisnis app lain.
_PLUMBING_MODULES = {
	"Core",
	"Custom",
	"Desk",
	"Printing",
	"Email",
	# Contact & Address dipakai form ERPNext (Customer, Supplier) lewat quick entry-nya;
	# Geo menyimpan Country yang jadi pilihan di Address itu.
	"Contacts",
	"Geo",
	# Reminder — fitur "ingatkan saya" milik Desk sendiri.
	"Automation",
}

# Endpoint yang berarti "gambarkan daftarnya", bukan "carikan saya satu nama".
# `search_widget` ikut di sini, bukan di picker: itu yang dipakai awesomebar untuk
# "cari <kata> di <doctype>", dan hasilnya daftar, bukan satu isian field.
_LIST_ENDPOINTS = (
	"frappe.desk.reportview.get",
	"frappe.desk.reportview.get_count",
	"frappe.desk.reportview.get_sidebar_stats",
	"frappe.desk.search.search_widget",
	"frappe.client.get_list",
)


def is_list_request() -> bool:
	"""Permintaan ini menggambar daftar, bukan mengisi satu field."""
	cmd = (frappe.local.form_dict or {}).get("cmd") or ""
	if cmd:
		return cmd in _LIST_ENDPOINTS
	request = getattr(frappe.local, "request", None)
	path = request.path if request else ""
	return any(endpoint in path for endpoint in _LIST_ENDPOINTS)


def _is_privileged(user: str) -> bool:
	return user in ("Administrator",) or "System Manager" in frappe.get_roles(user)


def _outside_assigned_roles(doctype: str, user: str) -> bool:
	"""Izin bacanya datang HANYA dari role otomatis, bukan dari role yang diberikan ke akun."""
	roles = set(frappe.get_roles(user)) - _AUTOMATIC_ROLES
	if not roles:
		return True
	# `meta.permissions` sudah berisi baris Custom DocPerm kalau doctype-nya punya
	# (`Meta.set_custom_permissions`), jadi ini membaca izin yang benar-benar berlaku.
	return not any(p.read and p.role in roles for p in frappe.get_meta(doctype).permissions)


def is_blocked(doctype: str | None, user: str | None = None) -> bool:
	"""Doctype ini di luar permukaan Desk milik `user`?"""
	user = user or frappe.session.user
	if not doctype or _is_privileged(user):
		return False

	module = frappe.get_cached_value("DocType", doctype, "module")
	if module in _PLUMBING_MODULES:
		return False

	return _outside_assigned_roles(doctype, user)


def foreign_doctype_query(user=None, doctype=None) -> str:
	"""Hook `*` `permission_query_conditions` untuk SELURUH site.

	Akun customer dijawab aturannya sendiri; sisanya kena aturan modul ini, dan hanya pada
	endpoint daftar.
	"""
	from container_depot import customer_scope

	if customer_scope.get_user_customers(user):
		return customer_scope.foreign_doctype_query(user=user, doctype=doctype)
	if not is_list_request():
		return ""
	return "1=0" if is_blocked(doctype, user) else ""


def foreign_doctype_permission(doc, ptype=None, user=None, **kwargs) -> bool:
	"""Hook `*` `has_permission`: satu dokumen yang dibuka lewat URL.

	Untuk akun non-customer ini SENGAJA tidak menutup apa-apa: dokumen yang dibuka dari
	form lain (lampiran, kontak, template email) lewat sini juga, dan rutenya sendiri sudah
	hilang dari Desk. Yang ketat tetap sisi customer.
	"""
	from container_depot import customer_scope

	return customer_scope.foreign_doctype_permission(doc, ptype=ptype, user=user, **kwargs)


# Rute yang dipertahankan di luar doctype yang memang diberikan role akun itu. Daftar RUTE
# lebih ketat daripada daftar baca: `_PLUMBING_MODULES` membiarkan Desk membaca isinya (judul
# link, lampiran, template) tanpa harus punya halaman daftar untuk dibuka. Yang di sini adalah
# doctype yang halamannya memang dipakai orang biasa — dan itu sebabnya `Report`, `Workspace`,
# `Module Def`, `Desktop Icon` dan sebangsanya TIDAK ada di sini: itu layar admin.
# Daftar ini juga dibaca klien sebagai "boleh baca" untuk fitur, bukan cuma rute — sebuah
# doctype yang hilang dari sini membuat tombol/blok yang menyebutnya ikut menghilang. Karena
# itu isinya rute yang memang dipakai orang biasa PLUS perkakas list view yang menggantung
# pada flag yang sama.
_ROUTE_EXTRAS = {
	"User",  # /desk/user/<dirinya sendiri> — "Edit Profile" di menu avatar
	"File",  # lampiran, dibuka dari sidebar dokumen
	"Communication",  # satu email yang dibuka dari timeline
	"ToDo",  # penugasan ("Assigned to me")
	"Note",
	"Event",  # kalender
	"Notification Log",
	"Notification Settings",
	# Dibuka dari link di form ERPNext (Customer, Supplier).
	"Contact",
	"Address",
	# Perkakas list view: tag, filter tersimpan, papan kanban, template email di dialog Email.
	"Tag",
	"Tag Link",
	"List Filter",
	"Kanban Board",
	"Email Template",
	"Letter Head",
}


def prune_boot_can_read(bootinfo) -> None:
	"""Buang doctype di luar permukaan akun ini dari `boot.user.can_read` (extend_bootinfo).

	Itu daftar yang dipakai `frappe.router.setup()` membangun rute doctype, jadi membuangnya
	di sini menghapus rutenya: `/desk/hd-ticket`, `/desk/report` dan `/desk/workspace` tidak
	lagi dikenal Desk. Daftar yang sama juga dipakai klien untuk memutuskan boleh-tidaknya
	menggambar link ke sebuah doctype, jadi menunya ikut mengecil — bukan cuma menolak saat
	diklik.

	Ini MENGECILKAN daftarnya, tidak pernah menambah: doctype yang tidak boleh dibaca akun ini
	memang tidak pernah ada di sana sejak awal.
	"""
	user = frappe.session.user
	if _is_privileged(user):
		return
	can_read = (bootinfo.user or {}).get("can_read") or []
	bootinfo.user["can_read"] = [
		dt for dt in can_read if dt in _ROUTE_EXTRAS or not _outside_assigned_roles(dt, user)
	]


# --- layar /desk ------------------------------------------------------------
# Ikon di halaman utama /desk adalah doctype `Desktop Icon`, dan penjaganya sendiri lemah:
# ikon ber-`icon_type = "App"` hanya ditanya hook `add_to_apps_screen.has_permission` milik
# app-nya (frappe tidak punya, Raven meluluskan semua orang), sedangkan ikon `Link` tanpa
# `link_to` melewati pemeriksaan modul sama sekali. Hasilnya akun office melihat Framework,
# Frappe HR, Helpdesk, ERPNext dan belasan folder ERPNext lain di layar pertamanya.
#
# Yang benar-benar dibaca halaman itu satu: `frappe.boot.desktop_icons`
# (`desk/page/desktop/desktop.js`, `sync_layout`). Daftar yang sama juga mengisi pemilih app
# di kepala sidebar, jadi memangkasnya di sini merapikan keduanya sekaligus.
_HOME_ICONS = {"Container Depot", "Depot OAK (Mobile)"}


def prune_desktop_icons(bootinfo) -> None:
	"""Sisakan ikon depot saja di /desk untuk akun non-admin (extend_bootinfo).

	Catatan satu kasus yang tidak lewat sini: kalau user pernah menggeser ikonnya sendiri,
	`Desktop Layout` miliknya yang dipakai, bukan daftar ini. Isinya lahir dari daftar ini
	juga, jadi tata letak yang dibuat SESUDAH pemangkasan tidak akan memuat ikon lain.
	"""
	if _is_privileged(frappe.session.user):
		return
	icons = bootinfo.get("desktop_icons") or []
	bootinfo.desktop_icons = [icon for icon in icons if icon.get("label") in _HOME_ICONS]

