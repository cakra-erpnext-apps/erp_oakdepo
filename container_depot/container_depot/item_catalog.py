"""Katalog item untuk semua picker transaksi (M&R, Cleaning, Booking, Kontrak).

Sampai 2026-09-07 setiap picker menyaring dua kali: item harus punya selling Item Price di
price list customer **dan** masuk sebuah "Depot Service Menu" (master pemetaan Item Group
yang ikut dihapus, patch v0_92). Dua saringan itu dilepas — operator boleh memilih item apa
pun dari katalog, termasuk yang belum ada di kontrak si customer. Yang tidak dikontrak datang dengan rate 0 dan diisi manual oleh operator/kasir
(lihat ``pricing_model.currency_for_customer`` untuk mata uangnya).

Pengganti saringan itu adalah **urutan**: item yang paling sering dipakai naik ke halaman
pertama, sisanya menyusul alfabetis, dan pencarian tetap menjangkau seluruh katalog. Jadi
pemakaian harian tidak melambat meski daftarnya jauh lebih panjang.

Pengurutan dikerjakan di Python setelah query: katalog depot berukuran ratusan item (bukan
puluhan ribu), jadi satu query tanpa limit + slice jauh lebih murah dibanding sulap
``ORDER BY FIELD(...)`` — dan pagination-nya tetap jujur.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, cint, nowdate

# Dari mana "sering dipakai" dihitung: tabel anak tempat item benar-benar terpakai, per
# konteks picker. Nama tabel/kolom hanya boleh datang dari peta ini (dipakai mentah di SQL).
USAGE_SOURCES = {
	"mr": ("Repair Used Item", "item"),
	"cleaning": ("Cleaning Order Service", "cleaning_item"),
	"booking": ("Container Booking Charge", "item"),
}

# Jendela pemakaian: cukup panjang untuk menangkap pekerjaan musiman, cukup pendek supaya
# item yang sudah pensiun tidak menempel di atas selamanya.
USAGE_WINDOW_DAYS = 180
USAGE_LIMIT = 40
USAGE_CACHE_TTL = 3600


def _usage_counts(doctype: str, field: str, since: str) -> dict:
	rows = frappe.db.sql(
		f"""
		select `{field}` as item, count(*) as n
		from `tab{doctype}`
		where `{field}` is not null and `{field}` != '' and creation >= %(since)s
		group by `{field}`
		""",
		{"since": since},
		as_dict=True,
	)
	return {r.item: cint(r.n) for r in rows}


def popular_items(context: str | None = None) -> list:
	"""Item code terurut dari yang paling sering dipakai. ``context`` = kunci
	``USAGE_SOURCES``; None menggabungkan semua konteks (dipakai picker kontrak).

	Di-cache satu jam: hitungannya cuma sebuah GROUP BY, tapi picker dipanggil tiap ketikan.
	"""
	key = f"depot_popular_items::{context or 'all'}"
	cached = frappe.cache().get_value(key)
	if cached is not None:
		return cached
	sources = [USAGE_SOURCES[context]] if context in USAGE_SOURCES else list(USAGE_SOURCES.values())
	since = add_days(nowdate(), -USAGE_WINDOW_DAYS)
	counts: dict = {}
	for doctype, field in sources:
		for item, n in _usage_counts(doctype, field, since).items():
			counts[item] = counts.get(item, 0) + n
	ranked = [i for i, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))][:USAGE_LIMIT]
	frappe.cache().set_value(key, ranked, expires_in_sec=USAGE_CACHE_TTL)
	return ranked


def clear_popular_cache() -> None:
	for context in list(USAGE_SOURCES) + ["all"]:
		frappe.cache().delete_value(f"depot_popular_items::{context}")


def rank_by_usage(rows: list, context: str | None = None, key: str = "item_code") -> list:
	"""Urutkan ``rows`` (dict item) sering-dipakai dulu, sisanya tetap seperti diterima.

	Sort-nya stabil, jadi urutan alfabetis dari query bertahan di antara item yang
	sama-sama tidak pernah dipakai.
	"""
	ranked = popular_items(context)
	if not ranked:
		return rows
	order = {code: i for i, code in enumerate(ranked)}
	rows.sort(key=lambda r: order.get(r.get(key), len(order)))
	return rows


def search_items(
	txt=None, filters=None, fields=None, context=None, start=0, page_length=20
) -> list:
	"""Cari di SELURUH katalog item — tidak ada penyaringan kontrak sama sekali.

	``filters`` ditumpuk di atas ``disabled = 0``; ``fields`` default ke
	``item_code``/``item_name``. Hasil diurutkan sering-dipakai dulu lalu nama, dan baru
	dipotong sesuai halaman — supaya satu halaman 20 tidak pernah pulang kurang.
	"""
	query_filters = {"disabled": 0}
	query_filters.update(filters or {})
	or_filters = None
	txt = (txt or "").strip()
	if txt and txt.lower() != "undefined":
		or_filters = {"item_code": ["like", f"%{txt}%"], "item_name": ["like", f"%{txt}%"]}
	rows = frappe.get_all(
		"Item",
		filters=query_filters,
		or_filters=or_filters,
		fields=fields or ["name as item_code", "item_name"],
		order_by="item_name asc",
		limit_page_length=0,
	)
	rank_by_usage(rows, context)
	start = cint(start)
	page_length = cint(page_length)
	return rows[start : start + page_length] if page_length else rows[start:]
