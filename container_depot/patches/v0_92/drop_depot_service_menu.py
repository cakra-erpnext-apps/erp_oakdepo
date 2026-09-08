"""Turunkan seluruh fitur Depot Service Menu — doctype, data, laporan, kartu, dan tautannya.

Menu itu lahir sebagai filter: sebuah picker item hanya menawarkan item yang Item Group-nya
terdaftar di menu, dipotong lagi dengan item yang punya harga di kontrak si customer. Pada
2026-09-07 kedua saringan itu dilepas — item di luar kontrak pun harus bisa dipilih, dan
yang menggantikannya adalah urutan "paling sering dipakai"
(``container_depot.item_catalog``). Setelah itu tidak ada satu pun picker yang membaca menu,
jadi yang tersisa hanyalah master yang masih tampak hidup di sidebar: operator memetakan
Item Group ke sana dan mengira itu mengubah sesuatu. Master yang tidak mengerjakan apa-apa
lebih berbahaya daripada tidak ada.

Yang ikut turun: tiga doctype (menu + dua tabel anaknya), laporan "Depot Service Menu
Items", Number Card "Menu Belum Dipetakan", serta tautannya di Workspace dan Workspace
Sidebar. Custom DocPerm-nya dihapus juga supaya seeder izin di install.py tidak menghidupkan
baris yatim.

Item, Item Group, dan seluruh transaksi TIDAK tersentuh — menu tidak pernah memiliki data
itu, ia hanya menunjuknya.

Idempoten: setiap langkah no-op di site yang sudah melewatinya.
"""

from __future__ import annotations

import frappe

DOCTYPES = [
	# Anak dulu — menghapus induk lebih dulu akan tersandung pemeriksaan link.
	"Depot Service Menu Group",
	"Depot Service Menu Item",
	"Depot Service Menu",
]

REPORTS = ["Depot Service Menu Items"]
NUMBER_CARDS = ["Menu Belum Dipetakan"]
WORKSPACE = "Container Depot"


def execute():
	_drop_reports()
	_drop_number_cards()
	_drop_workspace_links()
	_drop_doctypes()
	frappe.db.commit()


def _drop_reports():
	for report in REPORTS:
		frappe.db.delete("Workspace Link", {"link_to": report, "link_type": "Report"})
		if frappe.db.exists("Report", report):
			frappe.delete_doc("Report", report, force=True, ignore_permissions=True)


def _drop_number_cards():
	for card in NUMBER_CARDS:
		if not frappe.db.exists("Number Card", card):
			continue
		try:
			frappe.db.delete("Workspace Number Card", {"number_card_name": card})
			frappe.delete_doc("Number Card", card, force=True, ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"drop number card {card}")


def _drop_workspace_links():
	"""Baris di Workspace dan Workspace Sidebar yang menunjuk menu.

	JSON-nya sudah tidak memuat baris ini lagi, tapi ``bench migrate`` menimpa Workspace
	dari JSON dan MENYISAKAN baris anak yang sudah tidak ada di sana pada site lama —
	tautan yatim yang mengarah ke doctype terhapus akan mematahkan render sidebar.
	"""
	for dt in DOCTYPES + REPORTS:
		frappe.db.delete("Workspace Link", {"link_to": dt})
		if frappe.db.table_exists("Workspace Sidebar Item"):
			frappe.db.delete("Workspace Sidebar Item", {"link_to": dt})
	if frappe.db.exists("Workspace", WORKSPACE):
		frappe.clear_cache()


def _drop_doctypes():
	for dt in DOCTYPES:
		for name in frappe.get_all("Custom DocPerm", filters={"parent": dt}, pluck="name"):
			frappe.delete_doc("Custom DocPerm", name, force=True, ignore_permissions=True)
		for name in frappe.get_all("Custom Field", filters={"dt": dt}, pluck="name"):
			frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)
		frappe.db.delete("Property Setter", {"doc_type": dt})
		if frappe.db.exists("DocType", dt):
			# force: lewati pemeriksaan link — tidak ada lagi yang merujuk ini.
			frappe.delete_doc("DocType", dt, force=True, ignore_permissions=True, ignore_missing=True)
		# Drop tabelnya by name juga: di site yang sweep orphan-nya sudah menghapus record
		# DocType, penjaga di atas terlewat dan barisnya akan tertinggal.
		frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{dt}`")
