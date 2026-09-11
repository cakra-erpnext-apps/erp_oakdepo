# Analisis: Catatan Web vs Sistem Berjalan (erp_oakdepo)

Investigasi berbasis kode, bukan rencana implementasi.
Head repo: `7621fd2` (2026-09-10) `fix(billing): a zero-total order never becomes an invoice`.
Root aplikasi: `erp_oakdepo/container_depot/`. Modul operasional ada di
`container_depot/container_depot/` (TIDAK ADA folder bernama `operations/` — file
`cleaning.py`, `eir.py`, `mr.py`, `tank_survey.py`, `notify.py`, dst. berada langsung
di folder modul itu). Layer PWA ada di `container_depot/ess/`.

---

## Step 0 — Orientasi

### 0.1 DocType operasional (job-type) yang ADA

| Konsep di catatan web | DocType di kode | Bukti |
|---|---|---|
| EIR / Inspection | `Inspection` (`inspection_type` = EIR-In / EIR-Out) | `container_depot/container_depot/doctype/inspection/inspection.json` |
| Cleaning | `Cleaning Order` (+ `Cleaning Order Service`, `Cleaning QC Photo`, `Cleaning Checklist Item`) | `doctype/cleaning_order/cleaning_order.json` |
| Repair / M&R | `Repair Order` (+ `Repair Damage Entry`, `Repair Estimate Item`, `Repair Used Item`, `Repair Work Photo`, `Repair Cost Total`) | `doctype/repair_order/repair_order.json` |
| Periodic Test | **TIDAK ADA DocType sendiri** — hanya `Repair Order.job_type = "Periodic Test"` + `pt_type` (`2,5Y` / `5Y`) | `repair_order.json` (field `job_type`, `pt_type`); `report/periodic_test_register/periodic_test_register.py:3-4` |
| Survey | `Survey Order` (+ `Survey Order Tank`) — dibangkitkan per booking Tank Out | `tank_survey.py:1-13`, `tank_survey.py:198` |
| Booking / order | `Container Booking` (`direction` = Tank In / Tank Out), `Order Bongkar`, `Order Muat`, `Booking Code` | `doctype/container_booking/container_booking.json` |
| Gate | `Gate Entry` | `doctype/gate_entry/` |
| Posisi tank | `Container Position` (+ `Container Position Photo`, `Container Position Template`) | `doctype/container_position/` |
| Log jejak | `Container Activity`, `Container Movement` | `doctype/container_activity/container_activity.json` |
| Master lain | `Container`, `Depot`, `Depot Contract`, `Tariff Rate`, `Cargo`, `Shipping Line`, `Surveyor Company` | `doctype/` |

**TIDAK ADA sama sekali:**
- `Leak Check` / `Leak Test` sebagai job atau field. Grep `leak` di seluruh kode aplikasi
  hanya menemukan Item/tarif: `seed_dev.py:81,137` (`TEST-LEAK-1BAR`, "1 Bar Leak Test"),
  `pricing.py:21` (`"Leak Test": "Leak Test 1 Bar"`), `patches/v0_11/seed_service_items.py:33,59`,
  `patches/v0_11/seed_product_bundles.py:34-37` (masuk paket). Satu-satunya kemunculan lain
  adalah kode kerusakan EIR `('59', 'Leakage')` di `eir_checklist_data.py:17`.
- `Interior Photo` — TIDAK ADA (grep nihil).
- `Photo Out` sebagai job terpisah — TIDAK ADA; yang ada hanya `Inspection` bertipe `EIR-Out`.
- `Touch-up` / klasifikasi perbaikan — TIDAK ADA (grep `touch.?up` nihil di *.py/*.json/*.vue).
- `Periodic Test Order` — pernah ada, **dihapus total** oleh
  `patches/v0_66/drop_periodic_test_and_survey_order.py` (doctype, data, number card, chart,
  Container Activity bertipe "Periodic Test", ToDo pengingat).
- Zone/yard/Depot Storage — sudah dihapus sebelumnya (status tank kini presence-based).

### 0.2 Status Container & transisi

`Container.status` (Select, `container.json`): `Booked`, `In_Depot`, `Available`, `Gate_Out` — hanya 4.
Ada juga `inventory_stage` (Select turunan): `Pre-Arrival` / `In Depot` / `Ready` / `Departed`.

`state_machine.py` **tidak lagi menegakkan urutan apa pun**:
- `state_machine.py:38-40` — `is_allowed(old, new)` → `return True` ("No sequence any more").
- `state_machine.py:43-45` — `assert_transition(old, new)` → `return` (no-op).
- Docstring `state_machine.py:1-11`: "the tank's process detail (cleaning / repair / survey /
  EIR) lives on the related orders, not the status."

**Konsekuensi penting untuk Isu 7:** TIDAK ADA state machine yang bisa dipakai untuk
menegakkan urutan job (Cleaning → Leak Check → Survey → AVL). Urutan itu, kalau ada,
harus hidup di tempat lain.

### 0.3 Bagaimana job dibuat

Tiga jalur, semuanya bertumpu pada EIR atau booking — bukan pada transisi status:

1. **Otomatis dari submit EIR-In** — `container_depot/container_depot/eir_followups.py`:
   - `create_cleaning_order_from_eir()` (`:97`) — dipicu kalau `eir_needs_cleaning()` (`:31`,
     tank_status = Empty Dirty) atau checkbox `create_cleaning_order` dicentang. Order lahir
     dengan `co.status = "Service Setup"` (`:145`).
   - `create_repair_order_from_eir()` (`:221`) — dipicu kalau ada damage row nyata
     (`eir_real_damage_rows()` `:36`) atau checkbox `create_repair_order`. RO lahir `Draft`,
     damage row di-seed lewat `seed_damages_from_eir()` (`:169`).
   - Kebalikannya: `release_followups_for_eir()` (`:284`) membatalkan order yang belum
     tersentuh saat EIR di-void.
2. **Otomatis dari booking Tank Out** — `tank_survey.py:198 provision_survey_order_for_booking()`
   membuat/menyelaraskan satu `Survey Order` + satu `Survey Order Tank` per container.
3. **Manual / dari email** — `mail_to_order.py` (parsing email → order), `order_generation.py`
   (`make_order()` `:176` untuk Order Bongkar/Muat dari booking), dan pembuatan manual di Desk.

**"Delegasi" yang disebut di Isu 2 sudah ketemu namanya di kode:** Cleaning Order lahir di
status `Service Setup` (antrean Admin Ops), dan baru pindah ke `Pending` lewat aksi
**"Teruskan ke Team"** (`install.py:2061`, event `cleaning_order_forwarded`;
`notify.py:437`). Worklist PWA hanya membaca `Pending` / `In_Progress`
(`cleaning.py:95`), jadi order `Service Setup` memang tidak terlihat tim cleaning.

### 0.4 Scheduler yang berjalan (`hooks.py:212-233`)

`daily`: `notify_customers`, `expire_lapsed_contracts`, `sweep_stale_notifications`,
`sync_storage_charges`.
`cron`: `*/5` `mark_stale_sst_heartbeats`; `0 2 1 * *` `generate_monthly_invoices`.

**TIDAK ADA** job harian yang menyapu `Container` untuk urusan tanggal test/inspeksi.

### 0.5 Temuan yang bertentangan dengan asumsi dokumen

- Dokumen menyebut folder `container_depot/operations/` dan `container_depot/doctype/`.
  Yang benar: `container_depot/container_depot/` (modul) dan `container_depot/ess/` (PWA API).
- Dokumen mengasumsikan ada `assert_transition` yang menegakkan transisi. Faktanya **no-op**.
- Dokumen mengasumsikan Periodic Test bukan job. Faktanya ia **sudah** job — sebagai varian
  `Repair Order` (`job_type = "Periodic Test"`), lengkap dengan start/finish/foto/status.
  Ini mengubah bentuk Isu 1 dan Isu 7 secara signifikan.
- `Container.last_test_date` (Date) **sudah ada** di master, dan di-copy ke
  `Inspection.last_test_date`. Jadi Isu 1 bukan "field belum ada", melainkan "belum ada
  perhitungan umur + badge".

---

## Isu 1 — Periodic test date & badge status

### AS-IS

**L1.1 — dari mana sistem tahu sebuah tank kena periodic test.**
Tidak ada deteksi. Yang ada hanya dua jejak terpisah:
1. `Container.last_test_date` (Date) — tanggal plat tank. Sejak 2026-09-09 ia bisa diisi
   **surveyor saat EIR** (`eir.py:1395-1409`, masuk `TANK_MASTER_FIELDS` di `eir.py:1412+`);
   di PWA ia satu field di step "Data tank" (`frontend/src/pages/EirInForm.vue:453,467`),
   opsional, tidak pernah `reqd`.
2. `Repair Order` ber-`job_type = "Periodic Test"` — uji yang benar-benar dikerjakan depo.
Keputusan "tank ini perlu diuji" **selalu keputusan manusia**: seseorang membuat Repair
Order bertipe Periodic Test. Tidak ada yang menghitung umur uji dan memberi tanda.

**L1.2 — tank standby lama yang jatuh tempo di depo.** TIDAK ADA mekanisme.
`hooks.py:212-233` tidak punya satu pun scheduler yang menyentuh `Container`. Satu-satunya
tempat jatuh tempo dihitung adalah report `Periodic Test Register`
(`report/periodic_test_register/periodic_test_register.py:194-198`, `_due()`), dan report itu
**digerakkan Repair Order, bukan Container**: `_orders()` (`:92`) memfilter
`ro.job_type = 'Periodic Test'`. Tank yang belum pernah punya order uji **tidak muncul sama
sekali** di register. Jadi jatuh tempo hanya terlihat kalau seseorang sudah lebih dulu
membuat order-nya — persis kebalikan dari yang dibutuhkan.

**L1.3 — Periodic Test job operasional atau item billing.** **Job operasional.** Ia varian
`Repair Order`, jadi ia mewarisi seluruh perkakas M&R: `start_date`/`started_by`,
`completion_date`, child table `work_photos` (`Repair Work Photo`, foto `reqd=1` per baris),
status 10 langkah, approval owner, dan billing. Sekaligus juga item billing — ada Item
`TEST-2-5YR` / `TEST-5-0YR` (`seed_dev.py:139-140`) yang dipakai `_types_by_order()`
(`periodic_test_register.py:145-158`) untuk menyimpulkan tipe uji dari baris `Repair Used Item`.

**T1.1 — field tanggal di Container** (`doctype/container/container.json`):
| fieldname | fieldtype | catatan |
|---|---|---|
| `manufacture_date` | Date | tanggal pembuatan tank |
| `last_test_date` | Date | **satu-satunya** field uji berkala |
| `eir_in_date` / `eir_out_date` | Datetime | jejak gate, bukan uji |
| `storage_billed_until` | Date | watermark storage |
| `target_lift_on` / `target_survey_on` / `target_urgent_on` | Date | target dari booking |

TIDAK ADA: `next_pt_due` (dihapus v0_66, lihat `periodic_test_register.py:16-18`),
`last_pt_type`, `csc_expiry`, atau field status/badge apa pun.

**T1.2 — scheduler harian atas Container.** TIDAK ADA (`hooks.py:212-233`, lihat §0.4).
Badge saat ini hanya bisa dihitung on-read (di endpoint) atau on-save.

**T1.3 — DocType Settings (Single).** Hanya dua, dan keduanya tidak cocok:
- `Depot Notification Settings` (`doctype/depot_notification_settings/`)
- `Depot Finance Settings` (`doctype/depot_finance_settings/`)
TIDAK ADA `Depot Settings` generik. Ambang 26/29/30 belum punya rumah.

**T1.4 — komponen PWA tank card / detail.**
- Detail: `frontend/src/pages/MonitorDetail.vue` — badge tunggal di `:208` (`badge` computed,
  `BADGE_TONE` di `:200`), spesifikasi tank dirangkai jadi satu baris di `specLine` (`:214-223`)
  yang berisi principal/tipe/kapasitas/tare. **`last_test_date` tidak dirender di sini sama
  sekali**, meski payload-nya sudah dikirim (`ess/inventory.py:582`).
- List: `frontend/src/pages/MonitorContainer.vue`, chip via `components/StatusChip.vue`.
- `last_test_date` dirender di: `CleaningOrder.vue:623`, `EirOutForm.vue:557`,
  `MrHistory.vue:361`, dan diisi di `EirInForm.vue:467` — semuanya sebagai baris teks polos.

### REQUIRED
`last test date` MM/YYYY di data tank + badge otomatis: ≤26 bulan SAFE, 27–29 WARNING,
≥30 NEED TEST (siklus 30 bulan).

### GAP
1. **Anchor tanggalnya tidak tepercaya.** Di DB dev: 19 tank, **0** punya `last_test_date`
   (query dijalankan, lihat §Isu 2 T2.3). Field-nya baru dapat penulis (surveyor EIR)
   pada 2026-09-09 dan opsional. Badge di atas data kosong akan menandai semua tank NEED TEST.
2. **Anchor-nya ganda dan tidak disatukan.** Sumber sebenarnya adalah `completion_date` dari
   Repair Order Periodic Test terakhir, dengan `Container.last_test_date` sebagai fallback.
   Logika itu **sudah ditulis** di `periodic_test_register.py:161-192` (`_history()`) tapi
   terkurung di dalam report dan hanya untuk tank yang punya order. Tidak ada fungsi yang
   bisa dipanggil PWA/Container untuk menjawab "kapan tank X terakhir diuji".
3. **Siklus tidak cocok.** Kode memakai `_MONTHS = {"2,5Y": 30, "5Y": 60}`
   (`periodic_test_register.py:42`) — dua siklus. Catatan web mengasumsikan satu siklus 30
   bulan. Ambang 26/29 tidak ada padanannya di mana pun.
4. TIDAK ADA tempat menyimpan ambang (tidak ada Depot Settings).
5. TIDAK ADA scheduler; TIDAK ADA slot badge tambahan di `MonitorDetail.vue` (hanya satu
   badge status presence).

### Effort kasar: **M**
Perhitungannya sudah ada di report dan tinggal diangkat jadi helper, tapi butuh field
anchor yang terisi, satu Single Settings baru, dan slot badge baru di 2 komponen PWA.

### Pertanyaan balik
- Siklus 30 bulan itu untuk **semua** tank, atau tetap dua siklus (2,5Y=30 / 5Y=60) dan
  ambang 26/29 hanya berlaku pada yang 2,5Y?
- Anchor badge = `completion_date` order uji terakhir, atau tetap `last_test_date` plat?
  (Kalau plat, siapa yang meng-update-nya setelah depo sendiri yang mengerjakan uji itu —
  sekarang tidak ada yang menulis balik.)
- 19 tank di dev tidak punya `last_test_date`. Di produksi apakah datanya ada, atau harus
  ada import massal dulu?

`[SARAN]` Angkat `_history()` + `_due()` dari report jadi satu helper level-Container dulu,
karena tanpa itu badge dan Isu 7 akan menghitung jatuh tempo dua kali dengan cara berbeda.

---

## Isu 2 — Empty Dirty belum tampil di PWA sebelum delegasi

### AS-IS

**L2.1 — alur lengkap.**
1. Surveyor submit EIR-In dengan `tank_status = "Empty Dirty"` → checkbox
   `create_cleaning_order` sudah ter-centang default (`inspection.py:126-131`).
2. `Inspection.on_submit` (`inspection.py:381-382`) memanggil `_ensure_cleaning_order()` →
   `eir_followups.create_cleaning_order_from_eir()` (`eir_followups.py:97`).
3. Cleaning Order lahir **status `Service Setup`** (`eir_followups.py:145`) — antrean Admin Ops.
   Bel berbunyi ke Admin Ops saja, bukan ke tim cuci (`install.py:2090-2092`,
   event `cleaning_order_created`; `notify.py:417-419`).
4. Admin Ops memilih metode cleaning, lalu menekan **"Teruskan ke Team"**
   (`doctype/cleaning_order/cleaning_order.js:121-129`) — tombol ini **hanya mengeset
   `status` ke `Pending`**, tidak ada endpoint sendiri.
5. Controller menangkap transisinya (`cleaning_order.py:251-265`,
   `_notify_if_forwarded_to_team`) dan membunyikan bel tim cuci
   (`notify.py:436-455`, event `cleaning_order_forwarded`).
6. Baru di titik ini order muncul di worklist PWA, karena `list_open_cleaning_orders`
   memfilter `{"status": ["in", ["Pending", "In_Progress"]]}` (`cleaning.py:95`).

Yang bisa klik: siapa pun dengan `write` pada Cleaning Order (`cleaning_order.js:249`) —
praktiknya Admin Ops.

**L2.2 — bisakah tim cuci mulai tanpa delegasi.** **Secara teknis BISA.**
- `cleaning.start_cleaning` (`cleaning.py:175-200`) hanya menolak kalau order sudah
  `docstatus == 1` / `Completed` / `Pending Review`. **Status `Service Setup` tidak diblokir.**
- PWA-nya bahkan mengizinkan: `frontend/src/pages/CleaningOrder.vue:593` —
  `canStart = ["Pending", "Service Setup"].includes(order.status)`.
- Yang menghalangi murni **penemuan**: order `Service Setup` tidak ada di worklist
  (`cleaning.py:95`) dan tidak ada notifikasi ke tim. Kalau operator sampai ke halaman
  detailnya (mis. lewat tautan langsung), tombol "Mulai" hidup dan endpoint-nya menerima.

**L2.3 — delegasi = buat job atau assign job.** **Keduanya bukan.** Job (`Cleaning Order`)
sudah dibuat otomatis saat EIR submit. Delegasi = **perpindahan status** `Service Setup →
Pending`, yaitu pernyataan "metode cuci sudah dipilih, silakan dikerjakan". Assignment ke
orang terjadi **belakangan dan sendiri**: `assigned_to` diisi oleh siapa pun yang menekan
"Mulai" (`cleaning.py:203`, model claim di `work_claim.py`), bukan oleh Admin Ops.

**T2.1 — endpoint & filternya.**
`/api/v1/ess/...` → `container_depot.ess.cleaning.cleaning_orders` (`ess/cleaning.py:24-28`)
→ `cleaning.list_open_cleaning_orders` (`cleaning.py:91`). Filter:
```python
filters = {"status": ["in", ["Pending", "In_Progress"]], "docstatus": 0}   # cleaning.py:95
depots  = get_user_depots()                                                # branch scoping
items   = filter_claimed(items, "assigned_to")                             # cleaning.py:122
```
Baris `:95` itulah yang menyembunyikan tank belum-delegasi. `filter_claimed` (`:122`) adalah
lapis kedua — menyembunyikan order yang sudah dipegang operator lain.

**T2.2 — fungsi yang dipanggil tombol delegasi.**
TIDAK ADA fungsi/endpoint. Tombol `Teruskan ke Team` di `cleaning_order.js:124-129`
menjalankan `frm.set_value('status', 'Pending')` lalu save. Efeknya:
`status: Service Setup → Pending`, dan sebagai efek samping controller
(`cleaning_order.py:251`) memicu `notify_cleaning_forwarded_to_team`. **`_assign` tidak
disentuh, tidak ada field custom.** (Bandingkan M&R yang punya endpoint sendiri:
`/api/v1/ess/mr-forward-to-team` → `mr.forward_to_team` `mr.py:935-953`.)

**T2.3 — query jeda Tank IN vs Cleaning start.**
```sql
SET SQL_BIG_SELECTS=1;
SELECT g.bulan, COUNT(*) AS tank_in,
       SUM(CASE WHEN c.d = g.d THEN 1 ELSE 0 END) AS cleaning_hari_sama
FROM (SELECT container, DATE(MIN(activity_time)) d,
             DATE_FORMAT(MIN(activity_time),'%Y-%m') bulan
      FROM `tabContainer Activity` WHERE activity_type='Gate In' GROUP BY container) g
LEFT JOIN (SELECT container, DATE(MIN(activity_time)) d
      FROM `tabContainer Activity` WHERE activity_type='Cleaning' GROUP BY container) c
  ON c.container = g.container
GROUP BY g.bulan ORDER BY g.bulan;
```
**DIJALANKAN** di `oakdepo.localhost` (dev). Hasil: `2026-09 | tank_in=1 | cleaning_hari_sama=0`.
Sebaran log seluruhnya: Booking 2565, Order Bongkar 1213, EIR 797, Repair 354, Cleaning 227,
Gate In 43, Gate Out 1 — **semua tertanggal 2026-09-02 s/d 2026-09-10**. Ini data seeder,
bukan riwayat operasional. **Angka ini tidak bisa dipakai memutuskan apa pun**; query di atas
perlu dijalankan ulang di DB produksi.

### REQUIRED
Tank Empty Dirty yang sudah IN langsung terlihat Team Cleaning tanpa menunggu klik adm depo.

### GAP
1. Gate-nya **nyata tapi hanya di penemuan**, bukan di izin. Endpoint `start_cleaning`
   sudah menerima order `Service Setup`; hanya filter `cleaning.py:95` dan ketiadaan
   notifikasi yang menyembunyikannya. Membuka gate = mengubah satu daftar status.
2. Gate ini **disengaja dan punya alasan**: di `Service Setup` metode cuci belum dipilih,
   jadi `cleaning_services` masih kosong dan order belum tahu dirinya PP Wash / Steam / Standard
   (`cleaning_order.py:86`, `wash_register.py:16`). Membuka gate tanpa jawaban untuk itu
   memindahkan pertanyaan "cuci pakai apa" ke lapangan.
3. Pola yang sama dipasang **dua kali sengaja** — M&R punya gate identik
   (`Approved → Pending`, `mr.py:306-310`). Mengubah satu tanpa yang lain memecah polanya.

### Effort kasar: **S**
Perubahannya satu daftar status di `cleaning.py:95` + satu aturan notifikasi; yang mahal
adalah keputusan produk soal metode cuci, bukan kodenya.

### Pertanyaan balik
- Kalau tim cuci boleh mulai sebelum metode dipilih, **siapa yang memilih metodenya** dan
  kapan? (Berpengaruh langsung ke tagihan — `_cleaning_lines`, `consolidated_billing.py:117`,
  membaca `cleaning_services`; order tanpa service jatuh ke tarif flat `CLEANING_ITEM`.)
- Apakah M&R ikut dibuka, atau hanya cleaning?
- Berapa jeda nyata di produksi? (query T2.3 di atas)

`[SARAN]` Tampilkan order `Service Setup` di worklist PWA sebagai baris berlabel "menunggu
metode" yang belum bisa di-Mulai — lapangan melihat antreannya tanpa gate-nya dicabut.

---

## Isu 3 — Remarks EIR tidak muncul di Repair Order

### AS-IS

**L3.1 — RO dibuat dari apa.** Dari EIR, dan **hanya dari damage row-nya**.
`create_repair_order_from_eir` (`eir_followups.py:221`) dijalankan saat EIR-In submit dengan
checkbox "Buat M&R" (`inspection.py:389-390`). Ia memanggil `seed_damages_from_eir`
(`eir_followups.py:169-219`) yang menyalin baris `Inspection Damage Entry` ke
`Repair Damage Entry`. RO juga bisa dibuat kosong manual di Desk.

**L3.2 — kerusakan yang hanya ada di remarks.** **Tidak sampai ke tim repair lewat jalur mana
pun.** Kalau tidak ada damage row, `eir_real_damage_rows()` (`eir_followups.py:36`) kosong;
kecuali surveyor mencentang "Buat M&R" secara manual, RO tidak dibuat sama sekali
(`eir_followups.py:234-235`). Kalaupun RO dipaksa dibuat (`force=True`), ia lahir **tanpa
damage row dan tanpa remarks** — tim repair membuka order kosong.
Satu-satunya tempat remarks EIR terbaca ulang adalah **panel perbandingan EIR-Out**
(`eir.py:508`, dirender `EirOutForm.vue:73`) — jauh di hilir, sesudah repair.

**L3.3 — remarks di RO untuk siapa.** Untuk **tim repair sendiri**, bukan penerima catatan EIR.
Field-nya `remarks`, label `"Remarks"`, description `"Opsional."`
(`doctype/repair_order/repair_order.json`) — netral, tanpa arah. Bandingkan `damages` yang
description-nya eksplisit: `"Salinan temuan kerusakan dari EIR — hanya dibaca."`

**T3.1 — fungsi pembuat RO & field yang di-copy.**
`eir_followups.create_repair_order_from_eir()` (`:221`) menyalin:

| ke RO | dari | baris |
|---|---|---|
| `container` | `Inspection.container` | `:270` |
| `inspection` | nama EIR | `:271` |
| `reff_doc` | `Inspection.reff_doc` | `:272` |
| `status = "Draft"`, `billing_status = "Unbilled"` | konstan | `:273-274` |
| `depot` | `Inspection.depot` ⟶ `Container.depot` | `:275-277` |
| `damages[]` | `seed_damages_from_eir()` | `:278` |
| `container_booking` | `booking_link.booking_of_inspection` (jalur adopsi) | `:255-263` |

**`remarks` TIDAK termasuk.** Tidak ada di daftar `frappe.get_all` `seed_damages_from_eir`
(`:191-198`), tidak ada di blok pembuatan (`:268-279`).

**T3.2 — struktur damage row di Inspection.**
Child DocType **`Inspection Damage Entry`** (`doctype/inspection_damage_entry/`):
`checklist_item` (Link Inspection Checklist Item), `area`, `component`,
`damage_type` (Link Inspection Damage Code), `repair_code` (Link Inspection Repair Code),
`damage_description` (Small Text, `reqd=0`), `severity` (Select Minor/Moderate/Major/Critical,
**`reqd=1`** — satu-satunya wajib), `location`, `part_face`, `coordinate_x/y`,
`before_photo` (Attach Image), `after_photo` (Attach Image), `estimated_repair_hours`,
`repair_status`.
**Foto TIDAK wajib per damage row** — `before_photo`/`after_photo` tanpa `reqd`.
Foto sebenarnya hidup di dua child table terpisah yang di-key ke `checklist_item`, bukan ke
baris damage: `Inspection Damage Photo` (`photo` `reqd=1`, `checklist_item` `reqd=1`) dan
`Inspection Item Photo` (`photo` `reqd=1`). Tidak ada validasi jumlah minimal foto di mana pun.

**T3.3 — Link RO → Inspection.** **ADA**: `Repair Order.inspection` (Link → Inspection).
Jadi `fetch_from: "inspection.remarks"` pada satu field baru di RO memang perubahan sekecil
itu — secara teknis.

### REQUIRED
Catatan bebas inspector di EIR ("gusset plate penyot") terbaca tim repair.

### GAP
1. `Inspection.remarks` tidak pernah disalin ke RO. Link-nya sudah ada, jadi gap-nya murni
   satu field.
2. **Gap yang lebih dalam, dan ini yang sebenarnya menggigit:** kerusakan yang hanya ditulis
   di remarks **tidak memicu pembuatan RO sama sekali**. Menampilkan remarks di RO tidak
   menolong kalau RO-nya tidak pernah lahir.
3. Kalau EIR dibuka lagi (`eir.revert_to_draft`, `eir.py:2161`) dan damage row baru
   ditambahkan lalu di-submit ulang: `create_repair_order_from_eir` berhenti di penjaga
   `spawned` (`:243-248`) dan mengembalikan RO lama **tanpa menyeed damage baru**.
   Temuan susulan tidak sampai ke RO.

### Effort kasar: **S** untuk remarks-nya; **M** kalau remarks juga harus bisa memicu RO.

### Pertanyaan balik
- Remarks EIR di RO: read-only (fetch) atau boleh diedit tim repair? Kalau boleh diedit, ia
  butuh field sendiri terpisah dari `remarks` RO yang sekarang.
- Apakah remarks berisi kerusakan harus **memicu** RO, atau cukup terbaca kalau RO sudah ada
  karena sebab lain?

`[SARAN]` Tambah field read-only `eir_remarks` dengan `fetch_from: inspection.remarks` di
RO — tapi jangan berhenti di situ, karena akar masalahnya ada di poin GAP 2, yang sama
dengan Isu 5.

---

## Isu 4 — Touch-up tidak punya jalur

### AS-IS

**L4.1 — lifecycle RO.** State machine tunggal di `mr.py:48-88` (`MR_TRANSITIONS`):
```
Draft ──────────────► Pending Approval ──► Approved ──► Pending ──► In Progress ──► Pending Review ──► Completed
  │                          │                 │
  │                          ├──► Rejected     └──► Completed          (potong kompas)
  │                          └──► Revision Requested
  └──────────────────────────────► Approved                            (BYPASS Admin Ops)
```
**ADA jalur yang tidak melewati principal**, dan ia sudah dipakai:
- `Draft → Approved` = **bypass Admin Ops** (`mr.py:53-56`), lewat
  `mr.bypass_approval()` (`mr.py:681-704`), endpoint `/api/v1/ess/mr-bypass-approval`
  (`hooks.py:274` → `ess/repairs.py:261`), digerbangi role Admin Ops di layer ESS
  (`ess/repairs.py:158 _require_admin_ops`). `owner_note` diisi otomatis
  *"Disetujui langsung oleh Admin Ops (bypass owner)"* (`mr.py:704`).
- `Approved → Completed` = potong kompas untuk kerja lima menit (`mr.py:63-68`).
- `mr.submit_direct()` (`mr.py:1074-1093`) menggabung keduanya jadi satu tekan.

**L4.2 — principal menjawab "no repair".** `mr.decision()` menulis `ro.status = "Rejected"`
(`mr.py:769`). `Rejected` ada di `DONE_REPAIR` (`container_status.py:35`), jadi ia
**berhenti menahan tank**: `container_open_orders` melewatinya dan `recompute_availability`
(`container_status.py:156-167`) memindahkan tank ke `Available`. **Tank tidak stuck** — ia
lanjut ke Survey/AVL dengan kerusakan tetap tercatat di EIR-In.

**L4.3 — "kerusakan tercatat tapi tidak dikerjakan" terbawa ke EIR Out.** **YA, sudah ada.**
`eir.py:495-545` membangun payload `reference_eir_in` yang memuat `remarks`, seluruh
damage row EIR-In yang lolos `is_real_finding()`, beserta fotonya. Dirender sebagai panel
"perbandingan" di `frontend/src/pages/EirOutForm.vue:57-80`. Panel itu tidak tahu-menahu
apakah kerusakannya sudah diperbaiki — ia menampilkan apa yang ditemukan saat masuk.

**T4.1 — options `status` Repair Order** (`repair_order.json`):
`Draft`, `Pending Approval`, `Approved`, `Rejected`, `Revision Requested`, `Pending`,
`In Progress`, `Pending Review`, `Completed`, `Cancelled`. Transisi lengkap di
`mr.py:48-88`; setiap status juga boleh mundur ke `Draft` (`reopen_to_draft`) kecuali
`Completed`.

**T4.2 — field klasifikasi (billable / touch-up / no repair).**
TIDAK ADA field klasifikasi di RO maupun di `Repair Damage Entry`.
Yang paling dekat — dan sudah dipakai — adalah **`Repair Used Item.decision`**
(Select: `Pending` / `Approved` / `Rejected`), yaitu approval per-baris oleh owner.
Baris `Rejected` dikecualikan dari total order dan dari invoice
(`consolidated_billing.py:225`, `mr._attach_counts` `mr.py:340`).
Kalau `repair_class` (Select) mau ditambah, tabel yang tepat adalah **`Repair Used Item`**,
bukan `Repair Damage Entry`: `Repair Used Item` yang menjadi baris invoice
(`_work_order_lines`, `consolidated_billing.py:183`), sedangkan `Repair Damage Entry` adalah
salinan read-only temuan EIR (`repair_order.json`: *"Salinan temuan kerusakan dari EIR —
hanya dibaca"*) dan tidak pernah menyentuh billing.

**T4.3 — RO masuk billing.**
`consolidated_billing._work_order_lines()` (`:183-252`) dengan spec
`_WORK_ORDERS[0]` (`:167-175`, `party_field = "principal"`). Filter:
```python
{"status": "Completed", "principal": customer,
 "billing_status": "Unbilled", "completion_date": ["between", [lo, hi]]}
```
Satu baris invoice per `Repair Used Item`, kecuali baris `decision == "Rejected"` (`:225`).
**Item rate 0:** baris tetap dibuat (`:230`, komentar `:194-195`: *"A line whose part is free
(rate 0) is still billed: it may carry nothing but labour"*). Yang menjaga adalah gerbang
di level order — `_bills_something()` (`:418-434`): order dibuang dari invoice hanya kalau
**total rate 0 DAN total manhour 0**. Jadi baris rate 0 yang membawa `manhour` **tetap
menagih** lewat header manhour charge. Tidak error, tidak di-skip diam-diam.

**T4.4 — filter worklist Team Repair.**
`ess/repairs.py:175 mr_execution` → `mr.list_mr_execution()` (`mr.py:386-400`), filter
`{"status": ["in", MR_EXECUTION_STATUSES]}` = **`["Pending", "In Progress"]`**
(`mr.py:310`), plus scoping depot. Order `Approved` **belum** di sini — Admin Ops harus
`forward_to_team` dulu (`mr.py:935-953`).

### REQUIRED
Kerusakan minor (silicone, body belakang bolong sedikit) dikerjakan tim repair tanpa diajukan
ke principal dan tanpa ditagih.

### GAP
1. **Jalur "tanpa principal" sudah ada** (`bypass_approval`) — asumsi "RO = ajukan ke owner"
   tidak akurat. Yang tidak ada adalah **nama** untuk jalur itu: sebuah RO bypass tidak bisa
   dibedakan dari RO yang owner-nya kebetulan menjawab cepat, kecuali dengan membaca
   `owner_note`.
2. **"Tidak ditagih" belum punya cara yang jujur.** Satu-satunya cara sekarang: rate 0 **dan**
   manhour 0 di semua baris, supaya `_bills_something()` membuangnya. Tapi manhour 0 juga
   berarti jam kerja tim tidak tercatat — depo membayar dengan menghapus datanya sendiri.
   Alternatif `decision = "Rejected"` per baris juga salah arti: itu berarti *owner menolak*,
   bukan *depo memutuskan menanggung*.
3. TIDAK ADA klasifikasi `billable / touch-up / no repair` di level apa pun.
4. Konsep "kerusakan dicatat, sengaja tidak dikerjakan" tidak punya penanda — sebuah RO
   `Rejected` dan sebuah temuan yang diabaikan terlihat sama dari EIR-Out.

### Effort kasar: **M**
Satu field Select di `Repair Used Item` + satu cabang di `_work_order_lines` /
`_bills_something`, tapi menyentuh jalur invoice yang sudah punya aturan rollback dan
manifest, jadi butuh uji yang teliti.

### Pertanyaan balik
- Touch-up: **jam kerjanya dicatat tapi tidak ditagih**, atau tidak dicatat sama sekali?
  (Menentukan apakah gerbangnya di baris invoice atau di `_bills_something`.)
- Siapa yang berhak menandai sebuah baris "touch-up" — Admin Ops saja, atau tim repair juga?
- Apakah touch-up boleh melewati approval sepenuhnya (langsung `Pending`, tanpa `Approved`),
  atau tetap lewat bypass Admin Ops seperti sekarang?

`[SARAN]` `Repair Used Item.repair_class` (Select: Billable / Touch-up / No Repair) yang
dibaca `_work_order_lines`, bukan status baru di RO — klasifikasinya per pekerjaan, dan satu
RO nyata memuat campuran.

---

## Isu 5 — Gap EIR → Repair → Photo Out, siapa tanggung jawab apa

### AS-IS

**L5.1 — titik yang menerima input kerusakan.** Dugaan dokumen **BENAR**.
Hanya `Inspection` (EIR-In dan EIR-Out) yang punya struktur kerusakan:
`has_damage` (Check), `damage_log` (Table → `Inspection Damage Entry`),
`damage_photos` (Table → `Inspection Damage Photo`) — `inspection.json`.
Titik-titik lain:

| Tahap | DocType | Bisa input kerusakan? |
|---|---|---|
| EIR In | `Inspection` (EIR-In) | **YA** — damage_log + damage_photos |
| Cleaning | `Cleaning Order` | TIDAK — hanya `remarks` (Small Text) + `qc_photos` (foto QC hasil cuci) |
| Leak Check | — | **DocType-nya tidak ada** |
| Repair | `Repair Order` | TIDAK sebagai *temuan baru* — `damages` read-only salinan EIR; yang bisa ditambah hanya `used_items` (pekerjaan) + `work_photos` + `remarks` |
| Survey (lowering) | `Survey Order Tank` | TIDAK — hanya `lowering_note`, `survey_notes` (Small Text); tidak ada tabel foto |
| Posisi tank | `Container Position` | TIDAK — `location_note` (reqd), `notes`, `position_photos` |
| Photo Out | — | **DocType-nya tidak ada** |
| EIR Out | `Inspection` (EIR-Out) | **YA** — struktur sama dengan EIR-In |

**L5.2 — Team Survey menemukan kerusakan di luar EIR-In.** **Tidak ada opsi sistem.**
Yang tersedia hanya `Survey Order Tank.survey_notes` — Small Text bebas, tanpa foto, tanpa
kode kerusakan, tanpa pemicu apa pun ke M&R. `tank_survey.finish_survey()`
(`tank_survey.py:851`) menerima `notes` dan menyimpannya; tidak ada cabang yang membaca isinya.
Sisanya lapor manual.

**L5.3 — Photo Out / EIR Out melihat foto EIR In.** **SUDAH BISA — asumsi dokumen keliru.**
`eir.py:495-545` mengumpulkan dari EIR-In referensi: `inspection_id`, `eir_date`,
`tank_status`, `remarks`, seluruh damage row nyata beserta **foto per checklist item**
(`photos_by_item`, `:515-524`), dan seluruh `Inspection Fitting` sebagai baseline.
Dirender penuh di `EirOutForm.vue:57-80` (panel `git-compare`), foto bisa dibuka lightbox.
`reference_eir_in` diisi otomatis saat EIR-Out dibuat (`eir.py:414`, `eir.py:1334`).
**Yang belum:** foto walk-around (`Inspection Item Photo`) yang **tidak** menempel pada
checklist item bertemuan kerusakan tidak ikut tampil — `photos_by_item` hanya dibaca untuk
item yang punya damage row (`eir.py:541`).

**L5.4 — amend EIR setelah submit.** `Inspection.allow_amend` tidak diset (`inspection.json`),
jadi amend Frappe standar tidak dipakai. Yang ada adalah **buka-ulang dokumen yang sama**:
`eir.request_revision()` (`eir.py:2122`) → Admin Ops memutuskan → `eir.revert_to_draft()`
(`eir.py:2161`) mengembalikan `docstatus` ke 0, membatalkan efek submit
(`unwind_submitted_eir`), dan memicu `release_followups_for_eir()` (`eir_followups.py:284`)
yang **membatalkan** Cleaning Order / M&R yang belum tersentuh.
**Submit ulang TIDAK memicu RO/EOR baru untuk temuan tambahan:**
`create_repair_order_from_eir` berhenti di penjaga `spawned` (`eir_followups.py:243-248`) —
"one M&R per EIR, forever" — dan `_ensure_repair_order_draft` (`inspection.py:449-452`)
membandingkan daftar RO sebelum/sesudah lalu diam kalau tidak ada yang baru.
Damage row baru **tidak** diseed ke RO yang sudah ada.

**T5.1 — damage row standalone?** **TIDAK ADA.** `Inspection Damage Entry` adalah child table
murni (`istable`, dipakai lewat `parent`/`parenttype` di `eir_followups.py:191-193`,
`eir.py:522`). `Repair Damage Entry` juga child, dan isinya salinan read-only.
TIDAK ADA `Damage Finding` / `Container Damage` standalone. Konsekuensinya: **temuan
lintas-tahap tidak bisa dicatat tanpa membuat Inspection baru.**

**T5.2 — field remarks/foto per DocType job.**

| DocType | remarks | foto |
|---|---|---|
| `Inspection` | `remarks` (Small Text) | `item_photos`, `damage_photos`, `exterior_photos` — semua `photo` `reqd=1` per baris |
| `Cleaning Order` | `remarks`, `cleaning_instructions`, `revision_note` | `qc_photos` (`Cleaning QC Photo`: `photo` `reqd=1`, `caption`), `surveyor_signature` |
| `Repair Order` | `remarks`, `owner_note`, `reopen_note`, `revision_note`; per baris `Repair Used Item.remark` / `owner_remark` | `work_photos` (`Repair Work Photo`: `item` `reqd=1`, `photo` `reqd=1`), `damages[].before_photo`/`after_photo` |
| `Survey Order` | — (header tidak punya remarks) | — |
| `Survey Order Tank` | `lowering_note`, `survey_notes`, `reopen_note` | — |
| `Container Position` | `location_note` (`reqd=1`), `notes` | `position_photos` (`photo` `reqd=1`) |

**T5.3 — event notifikasi yang di-seed.** **29 event, bukan 18** (`install.py:2078-2167`):
`eir_created`, `eir_submitted`, `eir_pending_review`, `cleaning_pending_review`,
`cleaning_order_created`, `cleaning_order_forwarded`, `repair_order_created`,
`repair_order_service_setup`, `repair_order_forwarded`, `repair_order_pending_approval`,
`repair_order_decided`, `repair_revision_requested`, `eir_revision_requested`,
`cleaning_revision_requested`, `order_gate_in`, `order_gate_out`, `order_muat_survey`,
`eir_out_hold`, `survey_order_scheduled`, `position_survey_pending`, `position_order_pending`,
`position_surveyed`, `position_confirmed`, `gate_out`, `booking_created`, `booking_submitted`,
`contract_created`, `contract_activated`, `invoice_submitted`.
**TIDAK ADA event untuk "kerusakan ditemukan di luar EIR".** Yang paling dekat
`repair_order_created` — tapi itu berbunyi hanya lewat submit EIR (`inspection.py:460`).
Event baru memang perlu ditambah.

**T5.4 — komponen Vue Photo Out.** `frontend/src/pages/EirOutForm.vue`. Sudah fetch foto
EIR-In untuk container yang sama: `reference` → `refEirIn` (`:418`) → panel `:57-80`,
`prevFittings` (`:420`). Foto sendiri diunggah lewat `CameraHost.vue` / `PhotoTile.vue`.

### REQUIRED
Kerusakan bisa dicatat by-sistem di tahap mana pun (survey/cleaning), bukan hanya di EIR In
yang dicek 1× oleh adm ops.

### GAP
1. **Kerusakan terkurung di Inspection.** Tidak ada DocType temuan standalone, jadi "catat
   kerusakan" secara struktural = "buat EIR". Ini gap arsitektural, bukan gap field.
2. Cleaning / Survey / Position **punya** `remarks` dan (sebagian) foto, tapi semuanya teks
   bebas yang tidak dibaca siapa pun dan tidak memicu apa pun.
3. Tidak ada event notifikasi untuk temuan di luar EIR.
4. Temuan susulan pada EIR yang dibuka-ulang tidak masuk ke RO yang sudah ada
   (penjaga `spawned`, `eir_followups.py:243`) — **ini bug perilaku, bukan sekadar fitur
   yang belum ada.**
5. Foto walk-around EIR-In yang tidak menempel pada damage row tidak muncul di panel
   perbandingan EIR-Out.

### Effort kasar: **L**
Butuh doctype temuan lintas-tahap (atau memperluas Inspection jadi bisa lahir dari tahap
lain), plus event notifikasi, plus penyesuaian penjaga idempoten M&R.

### Pertanyaan balik
- Temuan dari Survey/Cleaning: masuk ke **RO yang sedang berjalan**, atau membuka RO baru?
  (Kalau RO sedang `Pending Approval` di meja owner, menambah baris berarti approval-nya harus
  diulang.)
- Apakah temuan lintas-tahap perlu foto wajib? (Sekarang foto di EIR pun tidak wajib per
  damage row.)
- Berapa lama setelah EIR-In sebuah temuan baru masih "temuan EIR yang kelewatan" dan kapan ia
  jadi "kerusakan baru yang terjadi di depo"? Ini menentukan siapa yang menanggung.

`[SARAN]` Perlakukan ini sebagai gap arsitektural — jangan tambal per-doctype dengan field
remarks; satu tempat temuan yang bisa ditulis dari tahap mana pun akan menyelesaikan Isu 3
GAP 2 sekaligus.

---

## Isu 6 — Format tampilan label survey/job

### AS-IS

**L6.1 — Survey Order merepresentasikan apa.** **Satu kunjungan surveyor untuk satu booking
Tank Out**, bisa banyak tank. `tank_survey.py:1-13`: *"one Survey Order per outbound booking,
one row per tank"*. Dibuat oleh `provision_survey_order_for_booking()` (`tank_survey.py:198`)
dari booking **draft** (bukan submit), idempoten, dan mengikuti perubahan booking.
Field: `booking` (Link), `principal`, `surveyor`, `survey_date`, `plan_date`,
`tank_count`, `lowered_count`, `survey_done_count`, `per_surveyed`, `tanks` (child).

**Multi-depo:** header punya **satu** `depot` dan **satu** `branch`, disalin dari booking
(`tank_survey.py:254-255`). Tapi `Survey Order Tank` punya `depot` sendiri per baris
(`survey_order_tank.json`). Jadi `DEPO 1 (3) DEPO 2 (2)` **bisa dihitung dari baris**, tapi
hanya kalau satu booking Tank Out memang mencampur depo — dan header-nya akan tetap menyebut
satu depo saja. Kalau kenyataannya satu kunjungan surveyor mencakup **beberapa booking**,
format itu tidak bisa dihasilkan sama sekali dari satu Survey Order.

**L6.2 — konsep depo/yard/lokasi.**
- **`Depot`** (DocType sendiri): `depot_code` (Data), `depot_name`, `branch` (Link → Branch),
  `city`, `address`, `is_active`.
- **`Branch`** — doctype standar ERPNext, dipakai untuk scoping user (`user_branch.py`).
- Zone/yard **sudah dihapus**: `Container.yard_zone` masih ada sebagai Data sisa, tapi peta
  yard (blok/baris/slot) dihapus di patch v0_36 (`ess/inventory.py:592-595`). Letak tank kini
  kalimat bebas `Container.current_location` + `Container Position.location_note`.

**L6.3 — data yang belum ada untuk placeholder.**
| Placeholder | Status |
|---|---|
| `[TGL SURVEY]` | **ADA** — `Survey Order.survey_date` |
| `[TGL PICKUP]` | **ADA** — `Survey Order.plan_date` (dari `Container Booking.plan_date`) |
| principal (`STOLT`, `BERTSCHI`) | **ADA** — `Survey Order.principal` (Link → Customer) |
| `DEPO 1 (3) DEPO 2 (2)` | **SEBAGIAN** — `Depot.depot_code` ada; hitungan per depo bisa diturunkan dari `Survey Order Tank.depot`, tapi hanya dalam satu Survey Order |
| `P5`, `P7` | **TIDAK ADA** — perlu klarifikasi lapangan |
| `MM` | **TIDAK ADA** — perlu klarifikasi lapangan |

**T6.1 — field Survey Order.** `booking`, `principal`, `surveyor`, `status`
(Scheduled/In Progress/Completed/Cancelled), `survey_date`, `plan_date`, `target_urgent_on`,
`branch`, `depot`, `tank_count`, `lowered_count`, `survey_done_count`, `per_surveyed`,
`container_summary` (Data), `tanks` (Table → Survey Order Tank).
`autoname = "SVO-.YYYY.-.#####"`. **`title_field` TIDAK diset** (`null`).
`container_summary` diisi `build_container_summary()`
(`container_booking.py:59-74`) — sekadar `", ".join(nomor_tank)` yang dipotong dengan
penanda `(+N)` bila melebihi panjang field Data. Bukan format yang bisa diperluas.

**T6.2 — Settings tempat menyimpan format string.** **TIDAK ADA.** Tidak ada Single yang
menyimpan template Jinja, dan tidak ada endpoint yang me-render satu pun label
(`grep` nihil). Kandidat paling tepat: `Depot Settings` baru (belum ada — lihat Isu 1 T1.3),
di-render oleh `tank_survey.list_all_survey_orders()` (`tank_survey.py:457`) dan
`tank_survey.list_survey_orders()` (`:408`) yang menjadi sumber list PWA.

**T6.3 — judul job Team Survey di PWA.** `frontend/src/pages/SurveyOrderList.vue`:
- Judul baris: `{{ o.booking || o.name }}` (`:156`) — nomor booking, jatuh ke nomor Survey Order.
- Nomor SVO ditampilkan kecil di kanan (`:158`).
- Sub-baris: `[o.principal, fmtDate(o.survey_date), "{n} tank"]` (`:278`).
- Badge urgensi: `LiftOnBadge` dengan `survey_date` / `plan_date` / `target_urgent_on` (`:162`).
Format ini **hard-coded di Vue**, bukan dibaca dari server.

### REQUIRED
Label job seperti `MM P5 STOLT DEPO 1 [TGL SURVEY] [TGL PICKUP]` atau
`MM P5 BERTSCHI DEPO 1 (3) DEPO 2 (2) [..] [..]`.

### GAP
1. Semua komponen tanggal + principal **sudah ada**; yang hilang adalah `MM` dan kode
   lokasi `P5`/`P7`, yang belum diketahui artinya.
2. Format label hidup di Vue (`SurveyOrderList.vue:156,278`), bukan di data. Mengubah format
   = mengubah frontend, dan setiap tempat yang menampilkan Survey Order (list, kalender
   `schedule.py:412`, detail) punya rangkaiannya sendiri.
3. Multi-depo dalam satu label bertabrakan dengan model data: Survey Order = satu booking =
   satu `depot` di header.
4. TIDAK ADA tempat menyimpan format (tidak ada Depot Settings).

### Effort kasar: **S** kalau format tetap (satu helper server-side + satu field label);
**M** kalau harus bisa dikonfigurasi lewat Settings.

### Pertanyaan balik — **memblokir**
- **`MM` itu apa?** perlu klarifikasi lapangan.
- **`P5` / `P7` itu apa?** Kode depo? Kode posisi/blok? Kalau kode depo, apakah ia
  `Depot.depot_code`, dan kalau ya apa nilainya sekarang di produksi? perlu klarifikasi lapangan.
- Satu label = satu Survey Order (satu booking), atau satu hari kerja surveyor yang bisa
  mencakup beberapa booking? Kalau yang kedua, ini bukan soal format — model datanya yang
  berubah.

`[SARAN]` Jangan sentuh apa pun sampai `MM` dan `P5` dijelaskan; sisanya sudah tersedia dan
hanya perlu satu fungsi perakit label di sisi server.

---

## Isu 7 — BIG GAP: Leak Check & Interior Photo sebagai job operasional

### AS-IS

**L7.1 — bagaimana sistem menentukan urutan job setelah EIR In.**
**Tidak ada urutan. Semua job independen.**
- State machine tank sudah dimatikan: `state_machine.assert_transition()` no-op
  (`state_machine.py:43-45`), `is_allowed()` selalu `True` (`:38-40`).
- `Container.status` hanya presence: `container_status.py:1-16`.
- Satu-satunya "urutan" yang tersisa adalah **apa yang lahir otomatis dari EIR-In**:
  Cleaning Order kalau `tank_status = Empty Dirty` (`inspection.py:381`), Draft M&R kalau ada
  damage row (`inspection.py:389`). Keduanya lahir bersamaan, tidak saling menunggu.
- **AVL didefinisikan sebagai KETIADAAN pekerjaan terbuka, bukan sebagai selesainya urutan**:
  `recompute_availability()` (`container_status.py:156-167`) → `Available` begitu
  `container_open_orders()` kosong. Komentarnya eksplisit (`container_status.py:52-54`):
  *"A tank that needed no cleaning has no cleaning to finish… readiness is the ABSENCE of open
  work, never the presence of a completed record."*
- Prioritas kerja diurutkan, bukan diurutkan-wajibkan: `worklist.sort_by_priority`
  (`worklist.py`) menyusun antrean per tanggal survey/urgensi.

**L7.2 — tiap baris tabel, bisa atau tidak.**

| # | Kondisi | Verdict |
|---|---|---|
| 1 | Dirty → Cleaning → Leak Check → Survey → AVL | **TIDAK** — Leak Check tidak ada sebagai job (T7.1). Cleaning → Survey → AVL bisa, tapi urutannya tidak dijaga: tank jadi `Available` begitu Cleaning `Completed`, tanpa menunggu survey. |
| 2 | Dirty + Repair → Cleaning → Leak Check → Repair → Survey → AVL | **TIDAK** — selain Leak Check, Cleaning dan M&R lahir **bersamaan** dari EIR-In (`inspection.py:381,389`) dan berjalan paralel. Tidak ada yang memaksa Repair sesudah Cleaning. |
| 3 | Dirty + Periodic → Periodic → Cleaning → Survey → AVL, leak check TIDAK ditagih | **TIDAK** — Periodic Test (RO `job_type`) harus dibuat manual, tidak pernah otomatis; dan tidak ada yang mencegah leak test ditagih (L7.4). |
| 4 | Dirty, periodic susulan → Cleaning → Leak Check → standby → Periodic → Survey → AVL | **TIDAK** — konsep "standby" tidak ada; Leak Check tidak ada. Bagian yang benar: tagihan lama memang aman (L7.5). |
| 5 | Clean → Survey → Leak Check → AVL | **TIDAK** — Leak Check tidak ada. Sisanya (Empty Clean langsung `Available`) memang jalan. |
| 6 | Clean + Repair/periodic → ikut aturan Dirty, skip Cleaning | **SEBAGIAN** — skip Cleaning otomatis (checkbox `create_cleaning_order` tidak tercentang untuk tank clean, `inspection.py:126`), tapi selebihnya sama gagalnya dengan baris 1–4. |
| 7 | Clean, Bertschi → Leak Check → Interior Photo → Survey → AVL | **TIDAK** — Leak Check tidak ada, Interior Photo tidak ada, dan tidak ada flag per principal (T7.4). |

**L7.3 — leak check masuk invoice bagaimana.**
Sebagai **baris `Container Booking Charge` yang diketik manual**. Item `Leak Test 1 Bar`
(kode `TEST-LEAK-1BAR`) diseed sebagai service Item
(`patches/v0_11/seed_service_items.py:33,59`; `seed_dev.py:81,137`), dipetakan dari kosakata
portal di `pricing.py:21`, dan ikut dalam bundle
(`patches/v0_11/seed_product_bundles.py:34-37`: Empty Clean Tank Package, Light/Medium/Hard
Cleaning Package). Operator menambahkan barisnya sendiri ke `Container Booking.charges`;
`_price_charges()` (`container_booking.py:842-892`) hanya mengisi `item_name`, `currency`,
`qty` (mengikuti jumlah container) dan menyeed `rate` dari price list bila belum pernah diisi.
**Tidak ada yang menyeed baris leak test secara otomatis.**
Lalu ia masuk invoice lewat `consolidated_billing._booking_lines()` (`:68-114`).
**Siapa menandai leak check "dilakukan": tidak ada.** Tidak ada status, tidak ada timestamp,
tidak ada `assigned_to`. **Bukti foto: tidak ada.**

**L7.4 — apakah sistem mencegah leak check ditagih saat ada Periodic Test.**
**TIDAK. Sepenuhnya bergantung ingatan adm ops.** Leak test adalah baris charge di booking;
Periodic Test adalah Repair Order. Keduanya dikumpulkan oleh **kategori billing yang
berbeda** (`consolidated_billing.CATEGORIES = ("Booking", "Cleaning", "M&R", "Storage")`,
`:324`) dan tidak pernah saling melihat. Tidak ada validasi silang di mana pun.

**L7.5 — mekanisme yang bisa membatalkan tagihan lama secara otomatis.**
**TIDAK ADA — dan ini kabar baik.** Yang ada hanya rollback yang dipicu manusia:
`consolidated_billing.rollback_billed_sources()` (`:726`) berjalan pada `on_trash`/`on_cancel`
Sales Invoice, membalik `sales_invoice` + `billing_status`/`payment_status` sumbernya.
Terbitnya Periodic Test **belakangan tidak menyentuh invoice mana pun**. Booking yang sudah
ber-`sales_invoice` juga tidak akan tersapu lagi (`_booking_lines` memfilter
`"sales_invoice": ["is", "not set"]`, `:85`). Risiko yang dikhawatirkan catatan web tidak ada.

**L7.6 — special-case nama principal di kode.**
Di **logika**: TIDAK ADA. Grep `Bertschi` / `Stolt` hanya menemukan:
- `seed_dev.py` — data seeder dev (customer contoh, Item Group `Gasket (Bertschi)`,
  paket `Empty Cleaned Tank Package (Stolt)`), bukan logika.
- `frontend/src/utils/labels.js:1595` — satu kalimat SOP yang **ditampilkan**:
  *"OAK 2 hanya menerima Empty Clean (principal Bertschi & Eway)."* Teks panduan, tidak
  bercabang di kode.
Tidak ada `if principal == "Bertschi"` di mana pun. Pola yang mau dihindari **belum terjadi**.

**T7.1 — grep `leak` seluruh repo.** Hanya sebagai **Item / tarif**, tidak pernah sebagai
field maupun DocType:
- `seed_dev.py:81` `("1 Bar Leak Test", 20.00, 1.0)`, `:137` `('TEST-LEAK-1BAR', 'Testing Charges', 'Nos', '1 Bar Leak Test')`
- `pricing.py:21` `"Leak Test": "Leak Test 1 Bar"`
- `patches/v0_11/seed_service_items.py:33` (Item Group `Testing Charges`), `:59` (harga 23.0)
- `patches/v0_11/seed_product_bundles.py:34-37` (masuk 4 bundle)
- `eir_checklist_data.py:17` `('59', 'Leakage')` — kode **kerusakan** EIR, bukan uji.
Tidak ada checkbox, tidak ada status, tidak ada job.

**T7.2 — DocType job yang bisa jadi template.**
**Tidak ada abstraksi bersama** — `Cleaning Order`, `Repair Order`, `Inspection`, `Survey
Order` berdiri sendiri-sendiri. Yang **dibagi** hanyalah modul helper:
- `work_claim.py` — klaim "siapa menekan Mulai" (`filter_claimed`, `guard_claim`), sudah
  dipakai EIR / Cleaning / M&R.
- `worklist.py` — `sort_by_priority`, urutan antrean seragam.
- `container_status.py` — `recompute_availability`, `container_open_orders`.
- `notify.py` + `Depot Notification Rule` — bel.
- `user_branch.py` — scoping depot.
**Template paling generik: `Cleaning Order`.** Ia punya persis bentuk yang dibutuhkan job
lapangan: `status` (Service Setup→Pending→In_Progress→Pending Review→Completed),
`cleaning_start`/`cleaning_end` (Datetime), `assigned_to`/`completed_by` (Link User),
child table foto (`qc_photos`), `remarks`, tanda tangan, `is_submittable`, link ke
`inspection`/`container_booking`, dan `sales_invoice` untuk billing.
`Repair Order` lebih kaya (approval owner, stock entry, per-line decision) tapi jauh lebih
berat untuk sekadar "foto bukti + selesai".

**T7.3 — cara foto disimpan.** Selalu **child table dengan `Attach Image` per baris**,
tidak pernah `Attach` tunggal:
`Cleaning QC Photo` (`photo` `reqd=1`, `caption`), `Repair Work Photo` (`item` `reqd=1`,
`photo` `reqd=1`, `caption`), `Inspection Item Photo` / `Inspection Damage Photo`
(`photo` `reqd=1`), `Container Position Photo` (`photo` `reqd=1`).
**TIDAK ADA validasi jumlah minimal foto di mana pun** — `reqd` hanya menjamin baris yang
sudah ada tidak kosong, bukan bahwa barisnya ada.

**T7.4 — field custom di Customer.** `install.CUSTOM_FIELDS["Customer"]` (`install.py:261-303`):
`oak_roles_section` (Section Break), `is_tank_owner`, `is_transporter`, `is_agent`,
`is_surveyor` — semuanya Check, `in_standard_filter=1`.
TIDAK ADA flag terkait foto/prosedur. **Tempatnya jelas ada**: blok yang sama, mengikuti pola
Check + description, di-upsert idempoten oleh `setup_custom_fields()` (`install.py:597-602`)
yang jalan tiap `migrate` (`install.py:53-56`).

**T7.5 — fungsi pembuatan invoice & hook point.**
`consolidated_billing.collect_units()` (`:380`) → `_collect()` (`:394`) menjalankan
`_BUILDERS` (`:334`) per kategori:
`Booking → _booking_lines` (`:68`), `Cleaning → _cleaning_lines` (`:117`),
`M&R → _mr_lines` (`:273` → `_work_order_lines` `:183`), `Storage → _storage_lines` (`:278`).
Semua unit lalu disaring `_bills_something()` (`:418`).
**Hook point untuk aturan "skip leak check bila ada Periodic Test":**
- Tempat yang benar secara arsitektur adalah `_booking_lines()` (`:97-105`), tempat baris
  charge disaring — di situ item `TEST-LEAK-1BAR` bisa dijatuhkan bila ada RO Periodic Test
  pada visit yang sama.
- `_bills_something()` **tidak cocok**: ia bekerja per-unit (satu booking utuh), bukan per-baris.
- Masalahnya: `_booking_lines` hanya tahu `Container Booking`, sedangkan Periodic Test hidup
  di `Repair Order`; "visit yang sama" harus dijembatani lewat `Repair Order.container_booking`
  (`booking_link.py`).

**T7.6 — Periodic Test punya DocType job sendiri?**
**TIDAK — dan ini sudah keputusan sadar.** `Periodic Test Order` dihapus total di
`patches/v0_66/drop_periodic_test_and_survey_order.py` (5 doctype, data, number card, chart,
Container Activity, ToDo). Penggantinya `Repair Order.job_type = "Periodic Test"` + `pt_type`
(`patches/v0_85/seed_periodic_test_menu.py:1-15`). Jadi **Isu 1 dan Isu 7 memang bertumpu
pada doctype yang sama (`Repair Order`)** dan harus didesain sekali — persis seperti dugaan
dokumen, hanya doctype-nya bukan yang baru melainkan yang sudah ada.

### REQUIRED
Leak check = job dengan foto bukti, posisinya berpindah-pindah dalam alur menurut kondisi
tank, tidak boleh ditagih bila ada Periodic Test. Interior Photo wajib untuk Empty Clean
principal tertentu (Bertschi).

### GAP
1. **Leak Check tidak ada sebagai job** — nol field, nol status, nol foto, nol bukti. Yang
   ada hanya Item tarif yang diketik manual ke booking.
2. **Interior Photo tidak ada.**
3. **Tidak ada mesin urutan.** State machine sudah dibongkar sengaja (`state_machine.py:1-11`),
   dan AVL didefinisikan sebagai ketiadaan pekerjaan terbuka. Tabel alur tujuh baris di catatan
   web **tidak punya tempat sama sekali** untuk ditulis. Ini gap terbesar dari ketujuh isu:
   bukan "fitur belum dibuat", tapi "konsepnya sudah dibuang sebelumnya".
4. **Tidak ada validasi silang leak-test vs periodic-test**; kategori billing-nya bahkan
   berbeda dan tidak saling melihat.
5. **Tidak ada flag per principal** — tapi tempatnya tersedia dan polanya jelas.
6. Periodic Test tidak pernah dibuat otomatis; ia selalu keputusan manual, sehingga baris 3
   dan 4 tabel alur tidak punya pemicu.

### Effort kasar: **L**
Butuh doctype job baru (Leak Check, ± Interior Photo), flag Customer, aturan billing silang
antar-kategori, dan — yang paling mahal — keputusan apakah urutan job mau dihidupkan kembali
setelah sengaja dibuang.

### Pertanyaan balik — **memblokir**
- **Urutan job mau ditegakkan sistem, atau cukup ditampilkan sebagai saran/checklist?**
  Menegakkan berarti menghidupkan lagi sesuatu yang sengaja dihapus, dan mengubah arti `AVL`
  dari "tidak ada pekerjaan terbuka" jadi "semua tahap wajib sudah selesai" — itu menyentuh
  gate-out, booking Tank Out, dan seluruh dashboard inventory.
- Leak Check: job berdiri sendiri, atau satu langkah bertimestamp+foto **di dalam** Survey
  Order / Cleaning Order? (Yang kedua jauh lebih murah dan tidak menambah antrean PWA baru.)
- "Tidak ditagih kalau ada Periodic Test" — periodic test **siapa**: yang dikerjakan depo
  (Repair Order), atau yang dikerjakan pihak ketiga dan depo hanya tahu tanggalnya?
- Interior Photo: berapa foto minimal, dan siapa yang mengerjakannya (tim cuci atau tim EIR)?
  (Perlu diketahui karena tidak ada satu pun validasi jumlah foto di app ini sekarang.)
- Flag principal: satu `require_interior_photo`, atau daftar prosedur wajib per principal
  yang bisa tumbuh? (Bertschi hari ini, principal lain besok.)

`[SARAN]` Pisahkan isu ini jadi dua keputusan terpisah — "Leak Check jadi job berfoto"
(kecil, berdiri sendiri, bisa jalan sekarang) dan "urutan job ditegakkan" (besar, membalik
keputusan arsitektur v0_36/v0_66) — karena menggabungkannya membuat yang kecil ikut tersandera.

---

## Ringkasan dependensi antar isu

```
                    ┌──────────────────────────────────────────┐
                    │  Repair Order.job_type = "Periodic Test"  │
                    │  (satu-satunya wujud uji berkala)         │
                    └────────────┬──────────────┬──────────────┘
                                 │              │
                    Isu 1 (badge jatuh tempo)   Isu 7 (leak test tak ditagih
                    butuh anchor tanggal        bila ada periodic)
                    dari order yang sama
                                 │              │
                                 └──────┬───────┘
                                   HARUS SEKALI DESAIN
```

1. **Isu 1 ⟷ Isu 7** — terikat erat. Keduanya bertanya "kapan tank ini terakhir/berikutnya
   diuji", dan jawabannya hanya ada di `Repair Order` + `Container.last_test_date`. Kalau
   dikerjakan terpisah, jatuh tempo akan dihitung dua kali dengan cara berbeda. **Kerjakan
   perhitungan anchor-nya sekali** (angkat `_history()`/`_due()` dari
   `periodic_test_register.py` jadi helper) sebelum menyentuh badge maupun aturan billing.

2. **Isu 3 ⟷ Isu 5** — Isu 3 adalah gejala, Isu 5 akarnya. Menambahkan `fetch_from` remarks
   ke RO (Isu 3) tidak menolong kalau RO-nya tidak pernah lahir, dan itu persis GAP 2 Isu 5.
   Kalau Isu 5 dikerjakan (tempat temuan lintas-tahap), Isu 3 ikut selesai. Kalau hanya Isu 3
   yang dikerjakan, sifatnya tambal cepat — sah, asal disadari.

3. **Isu 4 ⟷ Isu 5** — klasifikasi `touch-up` (Isu 4) hanya berguna kalau temuannya sampai
   ke RO. Keduanya menyentuh jalur EIR→RO yang sama.

4. **Isu 2 berdiri sendiri** — satu daftar status di `cleaning.py:95`. Tidak bergantung pada
   isu lain, tapi keputusannya berpasangan dengan gate M&R yang identik (`mr.py:310`):
   ubah satu, pertimbangkan yang lain, atau polanya pecah.

5. **Isu 6 berdiri sendiri** dan **terblokir klarifikasi lapangan** (`MM`, `P5`). Tidak ada
   isu lain yang menunggunya.

6. **Isu 7 GAP 3 (urutan job) adalah induk diam-diam.** Kalau urutan job jadi ditegakkan,
   arti `AVL` berubah dan itu menyentuh gate-out, booking Tank Out, `recompute_availability`,
   dashboard inventory, dan tidak langsung juga Isu 2 (kapan cleaning boleh mulai) dan Isu 4
   (apakah RO Rejected melepas tank). Keputusan ini sebaiknya diambil **sebelum** isu lain
   dieksekusi.

**Urutan yang paling sedikit membuang kerja:**
`Isu 6 (klarifikasi dulu)` → `Isu 7 keputusan urutan job` → `Isu 1+7 anchor periodic sekali`
→ `Isu 5 (+3, +4)` → `Isu 2`.

---

## Daftar [ASUMSI] yang belum terverifikasi

Semua klaim di atas `[VERIFIED]` dari kode kecuali yang berikut:

1. `[ASUMSI]` **Data produksi berbeda dari dev.** Semua angka DB di dokumen ini berasal dari
   `oakdepo.localhost` (dev): 19 tank, 0 punya `last_test_date`, Container Activity hanya
   2026-09-02 s/d 2026-09-10, 2 Cleaning Order, 1 Repair Order Periodic Test. Ini data seeder.
   Query T2.3 dan kelengkapan `last_test_date` **harus dijalankan ulang di produksi** sebelum
   dipakai memutuskan apa pun.

2. `[ASUMSI]` **"Delegasi" yang dimaksud catatan web = "Teruskan ke Team"
   (Service Setup → Pending).** Pemetaan ini dari nama tombol, alur, dan gejala yang dilaporkan
   — bukan konfirmasi pengguna. Kalau yang dimaksud adalah hal lain (mis. assignment ToDo
   Frappe), analisis Isu 2 berubah.

3. `[ASUMSI]` **`AVL` di tabel alur Isu 7 = `Container.status = "Available"`.** Tidak ada
   istilah `AVL` di kode.

4. `[ASUMSI]` **`P5` / `P7` adalah kode lokasi dan `MM` adalah kode dokumen/perusahaan.**
   Tidak ada padanannya di kode; ditandai "perlu klarifikasi lapangan" di Isu 6.

5. `[ASUMSI]` **"Photo Out" = EIR-Out.** Tidak ada DocType/menu bernama Photo Out; EIR-Out
   adalah satu-satunya inspeksi keluar. Kalau Photo Out adalah tahap terpisah sebelum EIR-Out,
   ia sama tidak adanya dengan Leak Check.

6. `[ASUMSI]` **Interior Photo dimaksudkan sebagai bukti foto bagian dalam tank pasca-cuci,
   bukan sebuah jenis inspeksi.** Tidak ada apa pun di kode untuk diperiksa.

7. `[ASUMSI]` **Siklus periodic yang dimaksud catatan web (30 bulan) = `pt_type "2,5Y"`.**
   Kode mengenal dua siklus (30 dan 60 bulan, `periodic_test_register.py:42`); catatan web
   hanya menyebut satu.

8. `[ASUMSI]` **Tidak ada override runtime di DB yang mengubah perilaku di atas.**
   Analisis ini membaca kode + JSON DocType. `Custom DocPerm`, `Property Setter`, Server
   Script, atau `Depot Notification Rule` yang diubah lewat UI tidak diperiksa.

9. `[ASUMSI]` **`erp_oakdepo` di working tree ini adalah kode yang berjalan di produksi.**
   Head `7621fd2` (2026-09-10); tidak diverifikasi terhadap deployment.
