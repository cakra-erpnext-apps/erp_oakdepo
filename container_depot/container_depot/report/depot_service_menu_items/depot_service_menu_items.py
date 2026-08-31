"""Isi tiap Depot Service Menu — satu halaman untuk menjawab "picker ini sebenarnya
menampilkan apa", per menu.

Sebuah menu adalah sekumpulan Item Group (plus item yang dipin satu-satu), dan itulah
yang membatasi item picker Booking / Cleaning / M&R / uji berkala. Sampai sekarang isinya
hanya bisa dibaca dengan membuka record menunya, mencatat groupnya, lalu menyaring daftar
Item satu per satu — dan yang paling penting justru tidak kelihatan sama sekali:

* menu yang BELUM DIPETAKAN tidak memfilter apa pun (``service_menu.is_real_menu``), jadi
  pickernya menampilkan seluruh katalog dan tampak normal. Kegagalannya senyap;
* menu yang dipetakan ke group yang TIDAK BERISI ITEM apa pun menghasilkan picker kosong,
  dan dari layar picker penyebabnya tidak terbaca;
* group induk diam-diam menarik seluruh turunannya (Item Group itu tree), sehingga isi
  sebenarnya bisa jauh lebih luas daripada yang dipilih operator.

Ketiganya terbaca langsung di sini: ringkasan di atas memberi satu angka per menu (merah
kalau nol), dan barisnya menyebut lewat mana tiap item masuk.

Isi menu dibaca lewat ``service_menu`` yang sama dengan yang dipakai picker — bukan query
tersendiri — supaya laporan ini tidak bisa menyatakan sesuatu yang berbeda dari apa yang
benar-benar dilihat operator di form.
"""

from __future__ import annotations

import frappe

from container_depot.container_depot import service_menu

# Semua item, bukan satu halaman: laporan ini justru dipakai untuk melihat seberapa luas
# sebuah menu menjaring (group induk menarik turunannya), jadi memotongnya di 500 akan
# menjawab pertanyaannya dengan angka yang salah.
_NO_LIMIT = 0

_UNMAPPED = "Belum dipetakan"
_INACTIVE = "Non-aktif"
_EMPTY_GROUPS = "Dipetakan, tanpa item"
_OK = "Aktif"


def execute(filters=None):
	filters = filters or {}
	menus = _menus(filters)
	rows = []
	counts = {}
	for menu in menus:
		menu_rows = _rows_for_menu(menu)
		counts[menu.name] = sum(1 for r in menu_rows if r.get("item_code"))
		rows.extend(menu_rows)
	return _columns(), rows, None, _chart(counts), _summary(counts)


def _menus(filters) -> list:
	one = filters.get("menu")
	menu_filters = {"name": one} if one else {}
	menus = frappe.get_all(
		"Depot Service Menu",
		filters=menu_filters,
		fields=["name", "is_active", "sequence"],
		order_by="sequence asc, name asc",
	)
	# Urutan sequence adalah urutan alur kerjanya (Booking -> Cleaning -> Maintenance ->
	# Periodic Test); menu tanpa sequence menyusul di belakang, bukan menyelip di depan.
	return menus


def _rows_for_menu(menu) -> list:
	"""Baris untuk satu menu — SELALU minimal satu baris.

	Menu kosong yang hilang dari laporan adalah persis kegagalan yang mau ditangkap:
	yang tidak muncul tidak akan diperbaiki siapa pun. Karena itu menu tanpa item tetap
	memakai satu baris berisi alasannya.
	"""
	if not menu.is_active:
		return [{"menu": menu.name, "status": _INACTIVE}]
	# Dibaca dari docnya langsung, bukan lewat helper privat service_menu: di titik ini
	# menunya sudah dipastikan aktif, jadi gating yang sama tidak perlu diulang.
	doc = frappe.get_cached_doc("Depot Service Menu", menu.name)
	extras = {r.item for r in (doc.get("extra_items") or []) if r.item}
	if not service_menu.is_real_menu(menu.name):
		return [{"menu": menu.name, "status": _UNMAPPED}]

	items = service_menu.items_in_menu(menu.name, limit=_NO_LIMIT)
	if not items:
		return [{"menu": menu.name, "status": _EMPTY_GROUPS}]

	rows = []
	for it in sorted(items, key=lambda i: ((i.get("item_group") or ""), (i.get("item_name") or ""))):
		rows.append({
			"menu": menu.name,
			"status": _OK,
			# Lewat mana item ini masuk: group (termasuk turunan group yang dipilih) atau
			# dipin satu-satu di extra_items. Yang kedua gampang terlupa saat memangkas
			# group, karena ia tidak ikut hilang bersama groupnya.
			"via": "Item (pinned)" if it["item_code"] in extras else "Item Group",
			"item_group": it.get("item_group"),
			"item_code": it["item_code"],
			"item_name": it.get("item_name"),
		})
	return rows


def _columns() -> list:
	return [
		{"fieldname": "menu", "label": "Menu", "fieldtype": "Link",
		 "options": "Depot Service Menu", "width": 150},
		{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 170},
		{"fieldname": "via", "label": "Masuk lewat", "fieldtype": "Data", "width": 120},
		{"fieldname": "item_group", "label": "Item Group", "fieldtype": "Link",
		 "options": "Item Group", "width": 220},
		{"fieldname": "item_code", "label": "Item Code", "fieldtype": "Link",
		 "options": "Item", "width": 180},
		{"fieldname": "item_name", "label": "Item Name", "fieldtype": "Data", "width": 260},
	]


def _chart(counts) -> dict:
	labels = list(counts.keys())
	return {
		"data": {"labels": labels, "datasets": [{"name": "Item", "values": [counts[m] for m in labels]}]},
		"type": "bar",
	}


def _summary(counts) -> list:
	"""Satu kartu per menu — segmen yang dicari saat membuka laporan ini.

	Nol ditandai merah: sebuah menu yang tidak menjaring apa pun bukan angka netral,
	itu picker yang tidak dibatasi (atau dibatasi sampai kosong)."""
	return [
		{"label": name, "value": count, "datatype": "Int",
		 "indicator": "Red" if not count else "Green"}
		for name, count in counts.items()
	]
