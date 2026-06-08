# Billing Mode — Cash vs Termin + Statement Reminder

Operasi depot isotank menagih customer dengan dua mode, dan menarik **statement
penagihan yang TIDAK membuat dokumen akuntansi apapun** (murni reminder/ringkasan
atas invoice yang sudah ada).

Semua dibangun di atas **primitive bawaan ERPNext** — tidak ada doctype baru.

---

## 1. Mode penagihan

| Kebutuhan | Primitive ERPNext | Di-seed oleh |
|---|---|---|
| Bayar langsung (Cash/Bank) | **Mode of Payment** + **Payment Entry** | `install.ensure_modes_of_payment` |
| Termin / due date per invoice | **Payment Terms Template** | `install.ensure_payment_terms_templates` |
| Default mode di customer | `Customer.payment_terms` (bawaan) | patch `v0_13.set_customer_payment_terms` |
| Override per invoice | `Sales Invoice.payment_terms_template` (bawaan) | — (tidak di-hide, langsung jalan) |
| Tarik outstanding & kirim statement | **Process Statement Of Accounts (PSOA)** | manual (lihat §4) |

### Payment Terms Templates yang di-seed (global, idempotent)
- **Immediate** — jatuh tempo = tanggal invoice (0 hari). Untuk bayar langsung.
- **Net 30** — 30 hari setelah tanggal invoice.
- **End of Following Month** — 1 bulan setelah akhir bulan invoice (basis termin default).

> Basis pasti tiap principal masih perlu dikonfirmasi owner — `End of Following
> Month` dipakai sebagai default yang aman. Ubah pemetaan di
> `patches/v0_13/set_customer_payment_terms.py` (`CONTRACT_TYPE_TO_TERMS`).

### Modes of Payment yang di-seed
- **Cash** (type Cash) → akun Kas default tiap company.
- **Bank Transfer** (type Bank) → akun Bank default tiap company.

Mapping dibuat untuk **semua company** yang ada (idempotent; baris yang sudah ada
tidak diduplikasi). Catatan: tidak ada company "MDN / PT. Oasis Anugerah Kasih"
di site ini — yang ada `Oak Depo` (OD) & `Oak Depo (Demo)` (ODD), jadi seeder
menerapkan ke keduanya.

---

## 2. Default mengalir ke invoice (dan bisa di-override)

`Customer.payment_terms` adalah **Default Payment Terms Template**. Saat Sales
Invoice dibuat untuk customer itu, ERPNext mengisi `payment_terms_template`
otomatis (`erpnext.accounts.party.get_payment_terms_template`). User tetap bisa
mengganti field tersebut per invoice — itulah override-nya.

Default per customer di-backfill dari `Depot Contract.payment_type`:
- `TOP`  → **End of Following Month**
- `Cash` → **Immediate**

Backfill **hanya** mengisi customer yang `payment_terms`-nya masih kosong, jadi
edit manual owner tidak pernah ditimpa.

---

## 3. Pembayaran

- **Bayar langsung:** buat **Payment Entry** (Mode of Payment = Cash / Bank
  Transfer), allocate ke invoice → invoice jadi Paid.
- **Bayar kolektif (termin):** **satu Payment Entry** bisa di-allocate ke
  **banyak Sales Invoice** sekaligus (fitur bawaan ERPNext: di Payment Entry,
  tabel *References* menampung banyak baris invoice).

---

## 4. Statement = REMINDER, bukan dokumen akuntansi

Pakai **Process Statement Of Accounts (PSOA)** — doctype bawaan ERPNext yang
**read-only terhadap akuntansi**: ia hanya merender PDF ringkasan + (opsional)
kirim email. **Tidak** membuat invoice, consolidated invoice, atau journal.

Langkah tarik statement (bisa **tanggal apapun**, manual atau terjadwal):

1. Buka **Process Statement Of Accounts** (Accounts workspace), buat baru.
2. **Customers**: tambahkan customer termin yang mau ditagih.
3. **Include Only Outstanding Invoices = ✓** ← kunci: hanya tampilkan invoice
   yang belum lunas.
4. **From Date / To Date**: isi rentang berapapun (tidak terkunci ke satu
   tanggal tetap).
5. **Preview / Download PDF** atau **Send Emails** untuk kirim ke AP customer.

### Auto-email (opsional, belum diaktifkan — tunggu konfirmasi owner)
Di PSOA: `Enable Auto Email = ✓`, `Frequency = Monthly`, isi `Recipients`
(email AP tiap customer). Selama belum dikonfirmasi, jalankan **manual**.

### Kalau tanggal penarikan terlewat
Cukup tarik/kirim statement belakangan (atau pakai notifikasi). **Tidak ada
auto-create dan tidak ada efek akuntansi** dari "terlewat".

---

## 4b. Multi-currency (1 company, invoice USD)

Company tetap base **IDR** (GL & laporan IDR), tapi principal yang di-quote USD
(price list OAK / Bertschi) bisa **diinvoice dalam USD** — fitur native ERPNext.

Di-setup oleh:
- `install.ensure_multi_currency_billing()` — menyalakan Accounts Settings
  **"Allow multi-currency invoices against single party account"** sehingga satu
  akun piutang IDR bisa menampung invoice USD (di-track per-party + exchange
  rate). Base currency company **tidak** diubah.
- patch `v0_13.set_customer_billing_currency` — set `Customer.default_currency` =
  currency Price List customer, **hanya** bila currency itu asing (bukan base
  company) dan `default_currency` masih kosong. Jadi Bertschi → USD; customer
  IDR dibiarkan (default ke base).

> Catatan: patch memakai `db.set_value` (lewati guard "ubah currency saat sudah
> ada transaksi"). Di site yang sudah punya invoice IDR untuk customer yang sama,
> review dulu sebelum mengganti billing currency-nya. Untuk bayar invoice USD via
> akun bank IDR, isi exchange rate di Payment Entry (selisih kurs otomatis).

## 5. Idempotency & lokasi kode

- `container_depot/install.py`
  - `ensure_payment_terms_templates()` — Payment Term + Template (Immediate / Net
    30 / End of Following Month).
  - `ensure_modes_of_payment()` — Cash + Bank Transfer, mapping akun per company.
  - Dipanggil di **`after_install` dan `after_migrate`** → fresh install maupun
    site existing sama-sama ter-cover, dan tetap idempotent.
- `container_depot/patches/v0_13/set_customer_payment_terms.py` — backfill default
  customer dari Depot Contract (terdaftar di `patches.txt`).
- `container_depot/container_depot/tests/test_billing_mode.py` — test acceptance.

Semua `ensure_*` cek-exist sebelum create; aman dijalankan berulang.
