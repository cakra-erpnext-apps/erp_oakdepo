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
``masters``  1 = ikut hapus master kurasi (Customer, Item, Depot, Branch, Depot Contract
             + Price List terbitannya, Shipping Line, Surveyor Company, letak tank, dst).
             0 (default) = master dibiarkan, hanya transaksi yang dibersihkan.
``seed``     ``"dev"`` (default) seed lengkap termasuk Depot Contract Bertschi yang
             langsung bisa dipakai; ``"prod"`` master saja tanpa tarif; ``""`` tidak
             menyeed apa pun.

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

# --- akuntansi + stok ------------------------------------------------------------
ACCOUNTING_DOCTYPES = [
	"Sales Invoice",
	"Purchase Invoice",
	"Payment Entry",
	"Journal Entry",
	"Stock Entry",
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
]

# (doctype jejak, kolom yang menyimpan nama doctype yang ditunjuk)
ORPHAN_TRAILS = [
	("Comment", "reference_doctype"),
	("Version", "ref_doctype"),
	("ToDo", "reference_type"),        # bukan reference_doctype
	("DocShare", "share_doctype"),
	("Notification Log", "document_type"),
	("File", "attached_to_doctype"),
]

# Awalan penomoran yang ikut di-nol-kan supaya nomor mulai dari 1 lagi.
SERIES_PREFIXES = [
	"EIR-", "CO-", "RO-", "ORD-BKR-", "ORD-MT-", "SVO-", "MV-", "GE-",
	"CPOS-", "OMI-", "SSTL-", "BKG-IN-", "BKG-OUT-", "CPU-",
	"ACC-SINV-", "ACC-PINV-", "ACC-PAY-", "ACC-JV-", "MAT-STE-",
]
MASTER_SERIES_PREFIXES = ["DCNT-"]

# Master kurasi yang ikut hilang saat ``masters=1`` (di luar yang diurus seed_dev.clear).
MASTER_DOCTYPES = [
	"Container Position Template",
	"Shipping Line",
	"Surveyor Company",
	"Customer Portal User",
	"Contract Document",
	"Allowed Branch",
	"Self Service Terminal",
]


def run(confirm: str | None = None, masters: int = 0, seed: str = "dev") -> None:
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
	_reset_series(SERIES_PREFIXES + (MASTER_SERIES_PREFIXES if int(masters) else []))

	frappe.db.commit()
	print(f"[reset] {deleted} baris dihapus.")

	if seed:
		_reseed(seed)

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
	"""Kembalikan master kurasi ke nol supaya seeder membangunnya dari awal."""
	from container_depot import seed_dev

	total = 0

	# Kontrak dulu, sebelum Customer: Price List terbitannya menautkan keduanya.
	price_lists = frappe.get_all(
		"Price List", filters={"name": ["like", "% - DCNT-%"]}, pluck="name"
	)
	if price_lists:
		total += frappe.db.count("Item Price", {"price_list": ["in", price_lists]})
		frappe.db.delete("Item Price", {"price_list": ["in", price_lists]})
	total += _wipe_documents(["Depot Contract"], "master")
	for pl in price_lists:
		frappe.db.delete("Price List", {"name": pl})
	total += len(price_lists)
	frappe.db.sql("update `tabCustomer` set default_price_list = null where default_price_list like %s",
		"% - DCNT-%")
	if price_lists:
		print(f"[reset] master: Price List terbitan kontrak — {len(price_lists)}")

	total += _wipe_documents(MASTER_DOCTYPES, "master")

	# Item / Item Group / Depot / Branch / Customer: pakai pembersih milik seeder sendiri.
	frappe.db.commit()
	seed_dev.clear()
	return total


def _sweep_orphans() -> int:
	"""Buang jejak yang menunjuk ke dokumen yang barusan hilang."""
	gone = set(DEPOT_DOCTYPES + ACCOUNTING_DOCTYPES + LEDGER_TABLES)
	total = 0
	for dt, field in ORPHAN_TRAILS:
		if not frappe.db.table_exists(dt):
			continue
		n = frappe.db.count(dt, {field: ["in", list(gone)]})
		if n:
			frappe.db.delete(dt, {field: ["in", list(gone)]})
			total += n
			print(f"[reset] jejak: {dt}.{field} — {n}")

	# Nisan "Deleted" menumpuk ribuan baris dari tiap teardown dan murni derau.
	n = frappe.db.count("Comment", {"comment_type": "Deleted"})
	if n:
		frappe.db.delete("Comment", {"comment_type": "Deleted"})
		total += n
		print(f"[reset] jejak: Comment(comment_type=Deleted) — {n}")
	return total


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
	frappe.db.commit()
