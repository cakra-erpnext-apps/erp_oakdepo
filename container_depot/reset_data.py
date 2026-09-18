"""Container Depot — reset satu site kembali ke kondisi "baru selesai di-seed".

    bench --site <site> execute container_depot.reset_data.run \
        --kwargs "{'confirm': '<site>'}"

Dipakai untuk menyiapkan / mengulang simulasi: seluruh dokumen transaksional depot
dan akuntansinya dihapus, jejak yatimnya disapu, penomoran dimulai lagi dari 1, lalu
master di-seed ulang. Site, user, role, dan isi ``site_config.json`` (termasuk kunci
VAPID) TIDAK disentuh — itulah bedanya dengan ``docker compose down -v``, yang jauh
lebih cepat tapi juga menghapus semuanya.

Parameter
---------
``confirm``  wajib, harus sama persis dengan nama site. Tanpa ini script menolak jalan —
             satu-satunya pengaman terhadap "kepencet di server yang salah".
``masters``  1 = kosongkan master kurasi SELURUHNYA, bukan cuma yang dibuat seeder:
             Customer, Supplier, Item, Item Group (daunnya), Warehouse
             ber-branch, Depot, Branch, Depot Contract (tarifnya ikut di dalamnya),
             Shipping Line, Surveyor Company, template letak tank, portal user, SST.
             Yang diketik orang ikut hilang —
             lihat :func:`_wipe_masters`. 0 (default) = master dibiarkan, hanya
             transaksi yang dibersihkan.
``seed``     ``""`` (default) tidak menyeed apa pun; ``"prod"`` master saja tanpa tarif;
             ``"dev"`` seed lengkap TERMASUK Depot Contract Bertschi berisi tarif
             karangan. Defaultnya sengaja kosong: menghapus itu yang Anda minta,
             menyeed itu kejutannya — dan tarif satu kontrak Active langsung dibaca
             booking, cleaning dan M&R sebagai rate card, jadi
             ``seed='dev'`` yang nyasar ke produksi memasang harga palsu yang terlihat
             sah. ``scripts/reset-site.sh`` selalu mengisinya sesuai stack.

Catatan
-------
* Penghapusan memakai ``frappe.db.delete`` mentah per tabel: cepat, melewati
  ``on_trash``, dan tidak peduli docstatus. Frappe tidak punya foreign key di level DB,
  jadi urutan antar tabel tidak jadi soal.
* Tabel anak SELALU dihapus ber-scope ``parenttype``. ``Sales Taxes and Charges``
  dipakai bersama oleh Sales Invoice DAN template PPN-nya; menghapusnya per nama tabel
  akan mengosongkan baris template tanpa error apa pun, dan semua invoice berikutnya
  terbit dengan pajak nol.
* Lampiran di disk tidak ikut terhapus — hanya baris ``File``-nya. Sisa file di
  ``sites/<site>/private/files`` aman diabaikan atau dibersihkan manual.
"""

from __future__ import annotations

import frappe

# --- dokumen transaksional depot (anak-anaknya diturunkan dari meta) ---------------
DEPOT_DOCTYPES = [
	"Booking Code",
	"Container Activity",
	"Container Movement",
	"Container Booking",
	"Container Position",
	"Gate Entry",
	"Inspection",
	"Cleaning Order",
	"Repair Order",
	"Order Bongkar",
	"Order Muat",
	"Survey Order",
	"Storage Charge",
	"OAK Monthly Invoice",
	"SST Activity Log",
	"Depot Push Subscription",
	# Terakhir: hampir semua yang di atas menautnya.
	"Container",
]

# --- akuntansi, pembelian, penjualan, stok ---------------------------------------
#
# Semuanya dokumen transaksi (submittable), bukan master: tidak ada satu pun yang
# dibangun ulang oleh seeder, jadi meninggalkannya berarti site "baru" yang masih
# menyimpan PO uji coba dan stok yang tidak pernah benar-benar ada.
#
# Rantai pembelian ada di sini karena justru itu jalur sparepart M&R (Purchase Order →
# Purchase Receipt → Stock Entry, lihat COMPANION_ROLES: peran Warehouse yang memilikinya).
# Sebelum 2026-09-14 hanya Purchase *Invoice* yang terdaftar, jadi PO dan PR-nya selamat
# dan stoknya ikut bertahan lewat Bin/Stock Ledger Entry yang menautnya.
#
# Sisi penjualan (Quotation / Sales Order / Delivery Note) tidak dipakai app ini, tapi
# tetap dihapus: reset yang menyisakannya bukan reset.
ACCOUNTING_DOCTYPES = [
	# Akuntansi
	"Sales Invoice",
	"Purchase Invoice",
	"Payment Entry",
	"Payment Request",
	"Journal Entry",
	# Jejak jalannya langganan berulang. Bukan dipakai depot, tapi barisnya menumpuk
	# sendiri dari scheduler — dan `_report_leftovers` di bawah yang menemukannya.
	"Process Subscription",
	# Pembelian — jalur sparepart M&R
	"Material Request",
	"Request for Quotation",
	"Supplier Quotation",
	"Purchase Order",
	"Purchase Receipt",
	"Subcontracting Order",
	"Subcontracting Receipt",
	"Landed Cost Voucher",
	# Penjualan
	"Quotation",
	"Sales Order",
	"Delivery Note",
	"Pick List",
	"Packing Slip",
	# Stok
	"Stock Entry",
	"Stock Reconciliation",
]

# Tabel datar tanpa dokumen induk — dihapus utuh.
LEDGER_TABLES = [
	"GL Entry",
	"Payment Ledger Entry",
	"Advance Payment Ledger Entry",
	"Stock Ledger Entry",
	"Bin",
	"Serial and Batch Bundle",
	"Repost Item Valuation",
	"Repost Payment Ledger",
	"Repost Accounting Ledger",
	# Identitas stok yang lahir DARI transaksi di atas, bukan master yang diketik orang.
	"Serial No",
	"Batch",
	"Stock Reservation Entry",
]

# (doctype jejak, kolom doctype yang ditunjuk, kolom NAMA dokumen yang ditunjuk)
#
# Kolom nama ada di sini sejak 2026-09-18 karena sapuannya berubah aturan: dulu ia membuang
# jejak milik daftar doctype yang dihapus reset ini, sekarang ia membuang SETIAP jejak yang
# dokumennya tidak ada lagi. Daftar tidak pernah lengkap — Depot Contract ketinggalan dan
# meninggalkan 252 Notification Log yatim — sedangkan "dokumennya sudah tidak ada" berlaku
# untuk doctype apa pun, termasuk yang dipasang app lain besok.
ORPHAN_TRAILS = [
	("Comment", "reference_doctype", "reference_name"),
	("Version", "ref_doctype", "docname"),
	("ToDo", "reference_type", "reference_name"),        # bukan reference_doctype
	("DocShare", "share_doctype", "share_name"),
	("Notification Log", "document_type", "document_name"),
	("File", "attached_to_doctype", "attached_to_name"),
]

# Log murni: baris yang tidak menunjuk dokumen mana pun, jadi ``_sweep_orphans`` tidak akan
# pernah menjaringnya, dan tidak ada yang lain yang membersihkannya. Di site dev ini mereka
# menumpuk jadi 9041 Deleted Document, 5462 Error Log dan 1428 Scheduled Job Log yang
# bertahan menyeberangi setiap reset — "hapus semua data" yang menyisakan 16 ribu baris log
# bukan hapus semua data.
#
# ``Deleted Document`` ikut karena setelah reset ia hanya menyimpan nisan dokumen yang
# memang sudah tidak ada. Yang TIDAK ada di sini: `Email Queue` (antrean kirim, bukan
# riwayat — membuangnya di tengah jalan menelan email yang belum terkirim) dan `File`
# (barisnya menaut berkas di disk, dan yang yatim sudah diurus sapuan).
LOG_TABLES = [
	"Deleted Document",
	"Activity Log",
	"Route History",
	"Access Log",
	"Error Log",
	"Error Snapshot",
	"Scheduled Job Log",
	"Prepared Report",
]

# Awalan penomoran yang ikut di-nol-kan supaya nomor mulai dari 1 lagi.
SERIES_PREFIXES = [
	"EIR-", "CO-", "RO-", "ORD-BKR-", "ORD-MT-", "SVO-", "MV-", "GE-",
	"CPOS-", "OMI-", "SSTL-", "BKG-IN-", "BKG-OUT-", "CPU-",
	"ACC-SINV-", "ACC-PINV-", "ACC-PAY-", "ACC-JV-", "MAT-STE-",
]
MASTER_SERIES_PREFIXES = ["DCNT-"]

# Master kurasi yang ikut hilang saat ``masters=1`` (di luar yang diurus seed_dev.clear).
#
# Hanya doctype berdiri sendiri. ``Contract Document`` dan ``Allowed Branch`` pernah ada
# di sini dan keduanya tabel ANAK: yang pertama milik Depot Contract (jadi sudah ikut
# terhapus lewat ``_child_tables`` saat kontraknya dihapus, ber-scope), yang kedua tidak
# punya induk sama sekali. Menyebut tabel anak di daftar ini berarti ``frappe.db.delete``
# tanpa scope — persis yang diperingatkan docstring modul ini.
MASTER_DOCTYPES = [
	"Container Position Template",
	"Shipping Line",
	"Surveyor Company",
	"Customer Portal User",
	"Self Service Terminal",
	# Katalog kurasi depot. Ditambahkan 2026-09-18: sebelumnya `masters=1` melewatinya,
	# jadi tiap baris yang pernah diketik tangan atau ditinggalkan teardown test bertahan
	# menyeberangi setiap reset — Cargo sempat 211 dari 210 yang ditanam seeder, Damage
	# Code 36 dari 29. Aman dihapus karena KEDUA seeder membangunnya ulang dari patch yang
	# sama (`seed_dev.run` dan `seed_prod.run` sama-sama memanggil `_seed_cargo`,
	# `_seed_eir_codes`, `_seed_eir_checklist`, `_seed_eir_fittings`,
	# `_seed_cleaning_checklist`), jadi hasilnya persis angka seeder, bukan nol.
	"Cargo",
	"Cleaning Checklist Item",
	"Inspection Checklist Item",
	"Inspection Damage Code",
	"Inspection Repair Code",
	"Inspection Fitting Item",
	# Satu-satunya di blok ini yang TIDAK dibangun seeder — routing-nya lahir di
	# `install.setup_notification_rules`, yang biasanya cuma jalan waktu migrate. Karena
	# itu `_reseed` memanggilnya sendiri; tanpa itu reset meninggalkan site tanpa satu pun
	# aturan notifikasi sampai migrate berikutnya.
	"Depot Notification Rule",
]


def run(confirm: str | None = None, masters: int = 0, seed: str = "") -> None:
	site = frappe.local.site
	if confirm != site:
		frappe.throw(
			f"reset_data dibatalkan. Ulangi dengan confirm='{site}' "
			f"kalau memang site inilah yang mau dikosongkan."
		)

	print("=" * 64)
	print(f"Container Depot — RESET DATA · site {site}")
	print(f"  masters={'ya' if int(masters) else 'tidak'}  seed={seed or 'tidak'}")
	print("=" * 64)

	deleted = 0
	deleted += _wipe_documents(DEPOT_DOCTYPES, "depot")
	deleted += _wipe_documents(ACCOUNTING_DOCTYPES, "akuntansi")
	deleted += _wipe_child_rows("Sales Taxes and Charges", "Sales Invoice")
	deleted += _wipe_child_rows("Purchase Taxes and Charges", "Purchase Invoice")
	deleted += _wipe_tables(LEDGER_TABLES, "buku besar")

	if int(masters):
		deleted += _wipe_masters()

	deleted += _sweep_orphans()
	deleted += _wipe_tables(LOG_TABLES, "log")
	_reset_series(SERIES_PREFIXES + (MASTER_SERIES_PREFIXES if int(masters) else []))

	frappe.db.commit()
	print(f"[reset] {deleted} baris dihapus.")

	if seed:
		_reseed(seed)

	_report_leftovers()

	frappe.clear_cache()
	print("=" * 64)
	print("[reset] SELESAI. Jalankan `bench --site <site> clear-cache` kalau Desk masih basi.")
	print("=" * 64)


# ----------------------------------------------------------------------------------
# Penghapusan
# ----------------------------------------------------------------------------------
def _child_tables(doctype: str) -> list[str]:
	return [f.options for f in frappe.get_meta(doctype).get_table_fields() if f.options]


def _wipe_documents(doctypes: list[str], label: str) -> int:
	"""Hapus dokumen + tabel anaknya. Anak selalu ber-scope parenttype."""
	total = 0
	for dt in doctypes:
		if not frappe.db.exists("DocType", dt):
			continue
		n = frappe.db.count(dt)
		for child in _child_tables(dt):
			total += _wipe_child_rows(child, dt, quiet=True)
		frappe.db.delete(dt)
		total += n
		if n:
			print(f"[reset] {label}: {dt} — {n}")
	return total


def _wipe_child_rows(child: str, parenttype: str, quiet: bool = False) -> int:
	"""Hapus baris tabel anak milik SATU induk saja.

	Selalu ber-scope: tabel anak yang sama bisa dipakai doctype lain (lihat docstring
	modul soal Sales Taxes and Charges), dan menghapus per nama tabel diam-diam
	mengosongkan master orang lain.
	"""
	if not frappe.db.table_exists(child):
		return 0
	n = frappe.db.count(child, {"parenttype": parenttype})
	if n:
		frappe.db.delete(child, {"parenttype": parenttype})
		if not quiet:
			print(f"[reset] anak: {child} (parent {parenttype}) — {n}")
	return n


def _wipe_tables(doctypes: list[str], label: str) -> int:
	total = 0
	for dt in doctypes:
		if not frappe.db.table_exists(dt):
			continue
		n = frappe.db.count(dt)
		frappe.db.delete(dt)
		total += n
		if n:
			print(f"[reset] {label}: {dt} — {n}")
	return total


def _wipe_masters() -> int:
	"""Kosongkan master kurasi SELURUHNYA, supaya seeder membangunnya dari awal.

	Bukan cuma nama-nama yang dikenal seeder: satu site yang sudah dipakai uji coba
	punya Customer dan Item yang diketik orang, dan "reset ke kondisi baru selesai
	di-seed" tidak berarti apa-apa kalau sisa itu bertahan (keputusan pemilik repo,
	2026-09-14). Karena itu flag ini bukan default, dan pembungkusnya menuntut nama
	site diketik ulang sebelum jalan.

	Tiga hal yang sengaja TIDAK ikut:

	* **Node grup** pada pohon Item Group dan Warehouse. Akar "All Item Groups" /
	  "All Warehouses - <abbr>" adalah induk yang dipakai seeder saat membangun ulang;
	  menghapusnya berarti seeder tidak punya tempat menggantung apa pun.
	* **Gudang bawaan ERPNext** (Stores / Finished Goods / WIP / Goods In Transit).
	  Stock Settings dan Company menautnya, dan menghapus gudang yang ditaut sebuah
	  Single memunculkan LinkExistsError yang pesannya di-samarkan Frappe jadi "disable
	  saja" — mahal dilacaknya. Yang dibuang hanya gudang ber-`branch`, yaitu milik
	  seeder ini.
	* **Customer Group / Territory / UOM / Company**. Seeder membacanya, tidak
	  membuatnya.
	"""
	total = 0

	# Kontrak dulu, sebelum Customer: tarifnya ikut di dalamnya (child table Tariff Rate),
	# jadi tidak ada rate card terpisah yang perlu dibersihkan sendiri.
	total += _wipe_documents(["Depot Contract"], "master")

	total += _wipe_documents(MASTER_DOCTYPES, "master")
	total += _wipe_documents(["Customer", "Supplier", "Item", "Depot", "Branch"], "master")

	# Jejak Contact/Address ke pihak yang barusan hilang. Dokumennya sendiri dibiarkan —
	# satu Contact bisa menaut pihak lain juga.
	for party in ("Customer", "Supplier"):
		n = frappe.db.count("Dynamic Link", {"link_doctype": party})
		if n:
			frappe.db.delete("Dynamic Link", {"link_doctype": party})
			total += n
			print(f"[reset] master: Dynamic Link → {party} — {n}")

	total += _wipe_tree_leaves("Item Group")
	total += _wipe_tree_leaves("Warehouse", {"branch": ["!=", ""]})

	return total


def _wipe_tree_leaves(doctype: str, extra: dict | None = None) -> int:
	"""Hapus daun sebuah pohon (``is_group = 0``), lalu susun ulang lft/rgt.

	``frappe.db.delete`` melewati ``on_trash``, jadi angka nested-set induknya tidak
	ikut menyusut. Insert berikutnya menghitung posisinya dari angka yang sudah basi
	itu — pohonnya rusak diam-diam, dan yang kelihatan baru nanti waktu seeder menaruh
	Item Group pertama. ``rebuild_tree`` menghitungnya ulang dari awal.
	"""
	from frappe.utils.nestedset import rebuild_tree

	filters = {"is_group": 0, **(extra or {})}
	names = frappe.get_all(doctype, filters=filters, pluck="name")
	if not names:
		return 0
	for child in _child_tables(doctype):
		_wipe_child_rows(child, doctype, quiet=True)
	frappe.db.delete(doctype, {"name": ["in", names]})
	rebuild_tree(doctype)
	print(f"[reset] master: {doctype} — {len(names)}")
	return len(names)


def _sweep_orphans() -> int:
	"""Buang SETIAP jejak yang dokumennya sudah tidak ada.

	Bukan "jejak milik doctype yang barusan dihapus". Itu aturan lamanya, dan aturan itu
	adalah sebuah daftar: daftar transaksi saja sampai 2026-09-18, jadi satu reset
	``masters=1`` meninggalkan 252 Notification Log milik Depot Contract yang sudah hilang.
	Daftar berikutnya akan ketinggalan doctype berikutnya.

	Aturannya sekarang satu kalimat: sebuah riwayat tanpa dokumen adalah sampah. Yang
	diperiksa tiap baris jejak, bukan nama doctype-nya — jadi ia ikut membuang sisa dari
	teardown test, dari penghapusan manual di Desk, dan dari app yang dipasang besok, tanpa
	pernah menyentuh riwayat dokumen yang masih hidup.

	Tidak ada lagi flag ``masters`` di sini: master yang ``_wipe_masters`` hapus ikut
	terjaring dengan sendirinya, karena dokumennya memang sudah tidak ada.
	"""
	total = 0
	for trail, dt_col, name_col in ORPHAN_TRAILS:
		if not frappe.db.table_exists(trail):
			continue
		targets = frappe.db.sql(
			f"select distinct `{dt_col}` from `tab{trail}` where ifnull(`{dt_col}`, '') != ''",
			pluck=True,
		)
		for target in targets:
			if not frappe.db.table_exists(target):
				# Doctype-nya sendiri sudah tidak ada (app dicopot, doctype dibuang patch):
				# setiap barisnya yatim, tidak ada tabel untuk dibandingkan.
				n = frappe.db.count(trail, {dt_col: target})
				if n:
					frappe.db.delete(trail, {dt_col: target})
					total += n
					print(f"[reset] jejak: {trail} → {target} (doctype hilang) — {n}")
				continue
			# LEFT JOIN, bukan `not in (select …)`: daftar nama bisa ratusan ribu baris, dan
			# NOT IN dengan NULL di dalamnya diam-diam tidak mencocokkan apa pun.
			orphans = frappe.db.sql(
				f"""
				select t.name from `tab{trail}` t
				left join `tab{target}` d on d.name = t.`{name_col}`
				where t.`{dt_col}` = %s and ifnull(t.`{name_col}`, '') != '' and d.name is null
				""",
				(target,),
				pluck=True,
			)
			if orphans:
				frappe.db.delete(trail, {"name": ["in", orphans]})
				total += len(orphans)
				print(f"[reset] jejak: {trail} → {target} — {len(orphans)}")

	# Nisan "Deleted" menumpuk ribuan baris dari tiap teardown dan murni derau. Tidak
	# terjaring aturan di atas: baris nisan justru MENUNJUK dokumen yang sudah hilang secara
	# sah, dan sebagiannya menunjuk dokumen yang masih ada.
	n = frappe.db.count("Comment", {"comment_type": "Deleted"})
	if n:
		frappe.db.delete("Comment", {"comment_type": "Deleted"})
		total += n
		print(f"[reset] jejak: Comment(comment_type=Deleted) — {n}")
	return total


def _report_leftovers() -> None:
	"""Sebut dokumen transaksi yang MASIH bersisa, alih-alih diam.

	Daftar di atas ditulis tangan, dan daftar tulis tangan selalu ketinggalan — PO dan
	PR ketinggalan sampai 2026-09-14. Yang mahal bukan ketinggalannya, melainkan bahwa
	tidak ada yang memberi tahu: operator menyangka site-nya bersih. Sapuan ini tidak
	menghapus apa pun, hanya menyalakan lampu.
	"""
	modules = ["Accounts", "Stock", "Buying", "Selling", "Assets", "Container Depot"]
	rows = frappe.get_all(
		"DocType",
		filters={"module": ["in", modules], "istable": 0, "issingle": 0, "is_submittable": 1},
		pluck="name",
	)
	sisa = {dt: frappe.db.count(dt) for dt in rows if frappe.db.table_exists(dt)}
	sisa = {dt: n for dt, n in sisa.items() if n}
	if not sisa:
		return
	print("[reset] MASIH BERSISA (tidak ada di daftar hapus):")
	for dt, n in sorted(sisa.items(), key=lambda kv: -kv[1]):
		print(f"[reset]   {dt} — {n}")


def _reset_series(prefixes: list[str]) -> None:
	"""Nol-kan penomoran. ``tabSeries`` tidak punya DocType, jadi SQL mentah."""
	for prefix in prefixes:
		frappe.db.sql("delete from `tabSeries` where name like %s", f"{prefix}%")
	print(f"[reset] penomoran: {len(prefixes)} awalan di-nol-kan")


def _reseed(seed: str) -> None:
	if seed == "dev":
		from container_depot import seed_dev

		seed_dev.run()
	elif seed == "prod":
		from container_depot import seed_prod

		seed_prod.run()
	else:
		frappe.throw(f"seed='{seed}' tidak dikenal — pakai 'dev', 'prod', atau '' ")

	# Routing notifikasi tidak ada di seeder mana pun — ia lahir di `after_migrate`. Reset
	# yang menghapusnya (MASTER_DOCTYPES) tanpa memanggil ini meninggalkan site yang diam:
	# tidak ada bel untuk gate, EIR, cleaning atau approval sampai migrate berikutnya.
	from container_depot.install import setup_notification_rules

	setup_notification_rules()
	frappe.db.commit()
