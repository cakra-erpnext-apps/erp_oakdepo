# AGENTS.md — erp_oakdepo / container_depot

Catatan serah-terima untuk asisten koding (AI atau manusia) yang baru masuk ke repo ini.
Isinya **hanya pengetahuan yang tidak bisa dibaca dari kode**: keputusan pemilik repo,
jebakan yang sudah pernah memakan waktu berhari-hari, dan hal yang sengaja dibiarkan
seperti sekarang. Fakta struktural ada di dokumen lain — jangan diduplikasi ke sini.

Bahasa: dokumen ini campur Indonesia/Inggris, mengikuti gaya repo. Istilah teknis, nama
file, nama doctype, dan pesan error selalu ditulis apa adanya.

---

## 1. Baca ini dulu

| Dokumen | Isinya |
|---|---|
| `README.md` | menjalankan stack dev, perintah bench harian, update prod, APK TWA |
| `STRUCTURE.md` | kontrak repo, aturan kode, model role 13 peran, gate log, offline PWA, notifikasi |
| `prd.md` | produk: siapa penggunanya, alur SOP PRO-OPS-009 (Tank In / Tank Out), fase rilis |
| `BILLING_MODE.md` | Cash vs Termin, statement reminder, multi-currency |
| `ANALISIS_CATATAN_WEB.md` | catatan analisis panjang (arsip, bukan spesifikasi aktif) |
| `../reference/*.md` | dokumen sumber dari pihak bisnis: SOP, gap analysis, contoh invoice/EIR |

Fakta dasar: repo bundle namanya `erp_oakdepo`, paket Frappe-nya `container_depot`
(namanya memang beda — jangan direname). Site dev `oakdepo.localhost`, prod
`app.oakdepo.com`. Frappe/ERPNext v16. Dua permukaan: Desk (`/app`) untuk kantor, PWA
Vue 3 (`/depot`) untuk lapangan.

---

## 2. Aturan kerja yang diminta pemilik repo

Ini preferensi eksplisit, bukan tebakan. Melanggarnya bikin dia harus membersihkan manual.

1. **Bersihkan data uji di sesi yang sama.** Apa pun yang dibuat untuk menguji —
   container, order, customer, dokumen konsol — dihapus lagi sebelum sesi berakhir. Site
   dev dipakai untuk melihat data sungguhan; sampah test membanjiri picker dan laporannya.
   Data yang memang diminta dibuat (seeder `seed_dev`) bukan sampah, biarkan.
2. **Commit langsung ke `main`.** Repo ini trunk-based, prod di-update dengan `git pull`
   di `main`. Jangan bikin branch atau PR.
   `origin` HTTPS tanpa credential → push lewat SSH:
   `git push git@github.com:cakra-erpnext-apps/erp_oakdepo.git main`, lalu
   `git fetch git@github.com:cakra-erpnext-apps/erp_oakdepo.git main:refs/remotes/origin/main`.
   Berlaku juga untuk repo lain di `oak_app/` (repo luar `oak_app` sendiri push ke
   `cakra-erpnext-docker`, namanya beda dari nama foldernya).
3. **Working tree ini dipakai bersama.** Sesi lain bisa sedang mengedit file yang sama;
   `git status` yang bersih di awal sesi bisa jadi 50 file berubah di tengah sesi. Sebelum
   `git add`, bandingkan mtime dengan apa yang benar-benar kamu sentuh:
   `git diff --name-only | while read f; do echo "$(stat -c %y "$f" | cut -c1-16)  $f"; done | sort`
   Kalau ada file asing yang baru berubah, tanya dulu — jangan commit campuran.
4. **Doctype yang punya aksi rollback wajib mengunci form di status terminal.** Tombol
   rollback membawa guard (cek sudah-ditagih, pengembalian stok, log) yang tidak dimiliki
   Save. Doctype submittable dapat kunci gratis kecuali field `allow_on_submit` yang
   terlihat dan tidak read-only; doctype non-submittable (Repair Order, Depot Contract)
   harus dikunci manual + guard server di `validate`.
5. **Kolom yang diisi sistem: `read_only: 1` + `depends_on: "eval:doc.<field>"`, jangan
   `hidden: 1`.** Form draft tetap bersih, nilainya muncul begitu terisi. Kalau sudah
   tampil di form, jangan diulang di sidebar `container_depot.render_system_facts`.
6. Kalau sebuah fitur diminta "hapus total", hapus beneran sampai doctype, patch, menu,
   seeder, dan test-nya — bukan disembunyikan dari menu. Master yang kelihatan hidup tapi
   tidak dibaca siapa pun lebih berbahaya daripada tidak ada.

---

## 3. Jebakan Frappe yang mahal di repo ini

Semua sudah pernah memakan waktu. Urut dari yang paling sering kena.

- **Edit JSON doctype / workspace tidak berpengaruh tanpa bump `modified`.**
  `bench migrate` membandingkan timestamp dan diam-diam melewati impor ulang. Sama untuk
  client script (`{doctype}.js`, `{doctype}_list.js`): script di-cache di browser dengan
  kunci `modified` milik doctype, jadi hard refresh dan `bench clear-cache` pun tidak
  menolong. Bump `modified` di **JSON dan DB**.
  Pengecualian: doctype `Workspace Sidebar` sinkron lewat jalur lain, tidak perlu bump.
- **Sidebar kiri Desk BUKAN `Workspace.links`.** Kartu di area konten datang dari doctype
  `Workspace` (`container_depot/container_depot/workspace/container_depot/...`); menu di sidebar kiri datang
  dari doctype terpisah `Workspace Sidebar`
  (`container_depot/container_depot/workspace_sidebar/container_depot.json`). Mengedit
  `Workspace.links` tidak akan pernah mengubah sidebar.
- **Icon Workspace harus id ikon Frappe yang valid.** Nilai `ship` tidak punya simbol SVG
  di build ini: server menyimpannya tanpa protes, lalu klien melempar "Icon is not
  correctly configured", sidebar berhenti render, dan record Workspace-nya pernah
  ikut terhapus. Pakai `stock`. Daftar valid: `id="icon-<name>"` di
  `apps/frappe/frappe/public/icons/timeless/icons.svg`.
- **RBAC ada di `container_depot/install.py`, bukan di `permissions` milik JSON doctype.**
  Seeder menulis **Custom DocPerm** (jalan di `after_migrate`) dan sifatnya **add-only**:
  baris yang sudah ada tidak pernah diupdate. Jadi mengubah matriks di kode tidak
  mengubah site yang sudah hidup — butuh patch. Dan begitu ada satu Custom DocPerm untuk
  sebuah doctype, blok `permissions` di JSON-nya diabaikan total saat runtime. Doctype
  baru hanya dapat 2 super-role sampai didaftarkan di `ROLE_DOCTYPE_PERMISSIONS`.
  Terapkan tanpa migrate penuh:
  `bench --site <site> execute container_depot.install.setup_permissions` lalu `clear-cache`.
- **`allow_copy` terbalik.** Labelnya "Hide Copy": `"allow_copy": 1` = menu **Duplicate**
  tidak muncul. Itu satu-satunya efeknya. Terpasang di Depot Contract dan lima doctype
  order; Container Booking sengaja masih boleh diduplikasi.
- **Spanduk form menumpuk di v16.** `layout.show_message` sekarang APPEND, jadi
  `frm.set_intro()` dan `frm.dashboard.add_comment()` menggambar salinan baru tiap
  `refresh` (sangat sering sesudah Save). Pakai
  `container_depot.form_message(frm, key, html, color, permanent)`
  (`public/js/form_message.js`). Masih memakai cara lama dan masih bug:
  `cleaning_order.js`, `inspection.js`, `container_booking.js`.
- **Indicator list custom tidak dipanggil untuk docstatus 0/2** kecuali
  `listview_settings[dt]` juga menyetel `has_indicator_for_draft: 1` /
  `has_indicator_for_cancelled: 1`. Gejalanya mirip cache basi, padahal bukan.
- **Versi frappe yang jalan ≠ yang ada di host.** Container dev menjalankan frappe
  **v16.18.3** yang dipanggang ke image; checkout `../frappe` di host v16.27.1 dan tidak
  dipakai siapa pun. Saat mendiagnosis bug Desk JS, baca kode yang benar-benar dideploy
  (`docker exec ... 'cd ~/frappe-bench/apps/frappe && git log --oneline -1'`) atau dump
  langsung dari halaman dengan `fn.toString()`. Backport kecil ke
  `container_depot/public/js/*_fix.js` + daftar di `app_include_js`, dengan
  **feature-detect** supaya patch mati sendiri saat frappe naik versi.
- **Link Single tidak kelihatan saat scan tabel.** `LinkExistsError` yang pesannya
  disamarkan jadi "You can disable this ... instead of deleting it" bisa datang dari
  `tabSingles` (mis. Stock Settings). Cari dengan
  `select doctype, field from tabSingles where value = %s`.
- **Setelah `frappe.db.delete` pada daun pohon (Item Group, Warehouse) wajib
  `rebuild_tree(doctype)`** — `db.delete` melewati `on_trash`, `lft/rgt` jadi basi dan
  insert berikutnya merusak pohon diam-diam.
- **Cache aset nginx.** `/assets/` dulu di-set `immutable` 1 tahun padahal nama berkas app
  tidak ber-hash → perbaikan JS klien tidak pernah sampai ke browser yang punya riwayat.
  Sudah diperbaiki dengan `map $uri $asset_cache_control` (hanya `.../dist/` yang
  immutable). Kalau ada laporan "fitur klien tidak jalan" tapi profil browser bersih
  normal, curigai cache dulu.

---

## 4. Test: cara menjalankan dan cara membacanya

Perintahnya ada di `README.md`. Yang tidak ada di sana:

- Tanpa `allow_tests`, `run-tests` mencetak "Testing is disabled for the site!" dan
  **exit 0 tanpa menjalankan apa pun**. Jangan pernah membaca exit 0 sebagai lulus —
  baca jumlah test.
- `run-tests --module X` mencetak **dua** ringkasan "Ran N tests" (dua kategori test
  frappe). `tail -3` cuma menampilkan yang kedua dan terlihat seperti modulnya tidak jalan.
- **`FrappeTestCase` TIDAK rollback per test.** Rollback didaftarkan sekali per kelas
  (`addClassCleanup`), jadi satu `frappe.db.commit()` di tengah kelas membuat semua baris
  yang sudah ditulis jadi permanen. Fixture yang commit = penguat kebocoran; buat fixture
  yang no-op kalau state sudah benar. Cleanup di `tearDownClass` **harus** commit (class
  cleanup jalan setelahnya). Test yang mengubah setting site harus memulihkannya lewat
  `addCleanup`, bukan `tearDown`.
- **Suite meracuni dirinya sendiri.** Run yang mati di tengah meninggalkan fixture;
  run berikutnya error `DuplicateEntry` di modul yang sama sekali tidak berhubungan, dan
  makin menumpuk tiap run. Modul yang merah di full-run tapi hijau sendirian = polusi,
  bukan regresi. Untuk iterasi, jalankan `--module` saja, satu full run di akhir.
- **Deadlock, bukan assertion.** `QueryDeadlockError (1213)` massal berarti ada proses
  lain menulis di site yang sama. Tersangka utama bukan sesi lain melainkan **RQ worker**
  sendiri (tiap submit meng-enqueue notifikasi; rebutan `FOR UPDATE` di `tabSeries`).
  Hentikan worker selama test — `pause_scheduler` tidak menyentuh worker:
  ```
  docker exec erp_oakdepo_dev-frappe-1 bash -lc 'W=$(pgrep -f "frappe worker" | head -1); kill -STOP $W; cd ~/frappe-bench; bench --site oakdepo.localhost run-tests --app container_depot --module <modul>; kill -CONT $W'
  ```
- **Baseline merah itu ada dan bukan salahmu.** Per 2026-09-18: dua batch,
  `973 tests (failures=1, errors=50, skipped=2)` lalu `217 tests (errors=33)`. **82 dari 84
  merah adalah drift data site**: master checklist EIR sudah dinomori ulang ke `A01…`
  sementara test masih mengirim kode numerik lama → `ValidationError: Unknown checklist
  item_code: 11`. Grep itu dulu sebelum menuduh perubahanmu.
- **Site dev bukan tempat menyimpan data ketikan tangan.** Teardown test menyapu per
  customer dengan `frappe.db.delete` mentah — nol tombstone, tidak bisa dipulihkan.
  Booking manual pernah hilang karena ini. Kalau harus mengetik data di sini: `bench backup`
  dulu, pakai Customer dan nomor tank sendiri.
- Reset permanen ada tooling-nya: `container_depot/reset_data.py` +
  `scripts/reset-site.sh`. `SEED` mengikuti `STACK`, dan `STACK=prod` menolak `SEED=dev`
  (seeder dev menanam kontrak Active berisi tarif karangan yang langsung dipakai sebagai
  rate card). Untuk site dev, `down -v && up -d` sering lebih murah: ±4 menit.

---

## 5. Build PWA

- Host WSL tidak punya `node`/`yarn` linux. Build dan lint **di dalam container**:
  ```
  docker exec erp_oakdepo_dev-frappe-1 bash -lc 'cd /home/frappe/frappe-bench/apps/container_depot/frontend && node node_modules/vite/bin/vite.js build --base=/assets/container_depot/ess/'
  ```
- **Selalu akhiri dengan** `cp container_depot/public/ess/index.html container_depot/www/depot.html`.
  `vite build` mengosongkan `public/ess/` dan menulis nama aset ber-hash baru, sedangkan
  entry point yang benar-benar disajikan adalah `www/depot.html` (salinan yang dibuat oleh
  paruh `copy-html-entry` dari `yarn build`). Keduanya gitignored, jadi tidak muncul di
  `git status` — satu-satunya gejala adalah aplikasi blank.
- Lint berisik by design (repo indentasi tab, eslint minta spasi). Nilai perubahan dari
  apakah ia **menambah** error, bukan dari run yang bersih.
- `yarn build` mengkompilasi apa pun yang ada di tree saat itu — termasuk pekerjaan
  setengah jadi sesi lain. Sebutkan kalau kamu rebuild.
- Sistem visual: brand oranye `brand-500 #F97828`, hijau `leaf-600 #078044`, font Plus
  Jakarta Sans, kelas `.oak-*` di `src/main.css`. Pakai kelas yang sudah ada, jangan
  utility ad-hoc.
- `NotifGate` memblokir seluruh PWA sampai perangkat berlangganan Web Push, tapi
  **sengaja tidak muncul** kalau site belum punya VAPID key (kalau tidak, operator
  terkunci di tombol yang tidak mungkin berhasil). Generate:
  `bench --site <site> execute container_depot.ess.push.generate_vapid_keys` — **jangan
  pernah** dengan `force=True` di prod, itu mematikan semua langganan yang ada.

---

## 6. Keputusan produk yang jangan dibalik

Semua ini keputusan eksplisit pemilik repo. Kalau kelihatan seperti bug, baca dulu alasannya.

- **Kontrak satu-satunya sumber harga.** `Depot Contract` → `Tariff Rate`. Tanpa kontrak,
  rate **0** dan kasir yang mengetik. Tidak ada fallback ke Price List site. Menu Price
  List / Item Price / Product Bundle sudah dihapus dan app tidak lagi menyentuh keduanya.
- **`Sales Invoice.conversion_rate` selalu 1** dan itu disengaja (`invoicing.py`) — finance
  yang mengganti di draft. Mengisi master Currency Exchange tidak akan berpengaruh karena
  baris itu menimpa nilainya. Jangan pernah set 0.
- **Picker item terbuka ke seluruh katalog**, tidak disaring kontrak. Item di luar kontrak
  tetap tampil dengan rate 0. Urutannya "sering dipakai" (`item_catalog.py`). Penyempitan
  yang sengaja tersisa cuma: part stok 0 disembunyikan dari picker M&R.
- **Satu Container Booking = satu payer.** Satu job dengan beberapa EMKL = booking terpisah
  dengan `reff_doc` yang sama sebagai pengikat. Jangan bangun "bill to per container".
  Alasan utamanya jalur lost-revenue di `consolidated_billing._booking_lines`.
- **Multi-currency = invoice bersaudara yang berbagi `depot_bill_group`**, bukan baris beda
  currency dalam satu dokumen (Sales Invoice Item tidak punya currency; grand_total, GL dan
  AR akan rusak). Print format OAK Invoice merender satu grup jadi satu PDF.
- **Submit booking Tank Out cuma butuh tank HADIR di depo.** Order yang belum selesai bukan
  penolakan melainkan prioritas (tanggal muat distempel ke tank dan ke order). Penolakan
  keras pindah ke bon (`OrderMuat._validate_no_open_work`), lalu submit EIR-Out butuh bon
  terbit, lalu gate.
- **Booking Cash yang `payment_status ≠ Paid` diblokir di gate** dengan pesan "bayar ke
  kasir dulu" + nomor Sales Invoice. Pembayaran tetap lewat alur kasir, bukan di app gate.
- **Letak tank hanya disimpan di master `Container`** (`current_location`,
  `location_updated_on`, `location_updated_by`), diisi lewat doctype `Container Position`
  yang berdiri sendiri. `Survey Order Tank` sengaja tidak punya field lokasi (ada test yang
  menjaganya). Setiap layar JOIN ke master dan selalu membawa umur pembacaannya — salinan
  di dokumen lain akan beku dan mulai berbohong pada koreksi pertama.
- **Zona yard tidak ada lagi.** Status container murni presence-based. `Container.yard_zone`
  / `current_location` / `row` / `bay` / `tier` tinggal kolom legacy. `Container Movement`
  sekarang cuma ledger audit status.
- **Email masuk mati total sejak 2026-09-15** (patch `v0_99`), berikut seluruh jembatan
  email→order. Satu Email Account per operator tidak muat: scheduler menarik tiap akun tiap
  10 menit, satu RQ worker `queue-short` dibagi dengan `default`, job dibunuh di 300s.
  Kalau mau dihidupkan lagi: 2-3 mailbox fungsi bersama (booking@/cs@/ops@), bukan per
  operator. Mail keluar tetap hidup.
- **Akun customer bisa login ke Desk** (role `Customer Desk`), di-scope lewat SATU User
  Permission `allow=Customer`. Empat lubang ditutup manual — baca `customer_scope.py`:
  User Permission menggabungkan tiap link field dengan **and** bukan **or**; doctype tanpa
  link Customer tidak tersentuh; flag `report` sengaja TIDAK diberikan (Query Report
  menjalankan SQL-nya sendiri, nol filter customer); akun customer mewarisi bacaan role
  `All`/`Desk User` sehingga ditutup allowlist modul, bukan deny-list.
- **Doctype `User` terlihat semua role Desk dan itu dibiarkan.** Mencabut `select` akan
  mengosongkan semua picker User (Assign To, Share, Notification).
- Tidak ada Frappe Workflow di mana pun. Semua approval = state machine Python + perm
  `write` (contoh: `operations/mr.py` `MR_TRANSITIONS`).

---

## 7. Fitur yang sudah dihapus — jangan dihidupkan lagi

Jangan menyarankan, mencari, atau "memulihkan" ini. Semua dihapus atas permintaan eksplisit.

| Fitur | Patch | Penggantinya |
|---|---|---|
| Depot Storage, Yard Zone, Yard Placement Rule | v0_36 | status presence-based |
| Gate Out Plan | v0_87 | Container Booking arah Tank Out (`lift_on.py`) |
| Periodic Test Order, Survey Order (jasa survey) | v0_66 | — (nama `Survey Order` kini dipakai untuk jadwal survey Tank Out, dokumen berbeda) |
| Depot Service Menu (+Group/Item) | v0_92 | picker katalog terbuka |
| Gasket Inventory | v0_40 | gasket = Item biasa |
| Container Leasing, Equipment Maintenance, Fuel Log, Survey Request | v0_41 | — |
| Jembatan email→order, tarik email | v0_99 | — |
| Port Sales Invoice dari erp_cakra | — | dibangun 2026-08-27/28 lalu **di-rollback penuh**; file rencananya bukan status terkini |

Sengaja **dipertahankan** meski fiturnya hilang: `Container.last_test_date` (milik master
tank, dibaca EIR dan print), opsi `Periodic Test` di OAK Monthly Invoice + item katalognya
(invoice lama itu riwayat akuntansi), `Surveyor Company`, dan doctype Self Service Terminal
(cuma disembunyikan dari menu — kodenya terjalin di jalur order).

---

## 8. Utang yang masih terbuka

- `pricing.DEFAULT_MANHOUR_HOUR = 4.0` dibaca sebagai rupiah-per-jam → biaya tenaga kerja
  tertagih ~Rp 14 di invoice jutaan. Butuh rate sungguhan, idealnya pindah ke Depot Finance
  Settings. Terkait: arti `manhour` (JAM menurut data, RATE menurut pembacaan user) belum
  disepakati — selisihnya ~8×. **Selesaikan itu sebelum menyentuh billing tenaga kerja.**
- Letterhead/bank/company di print format OAK Invoice masih hardcoded ke PT. Oasis Anugerah
  Kasih.
- `CLEANING_ITEM = "Standard Cleaning"` tidak ada di katalog (hanya jalur fallback).
- Commercial cuma punya `read` di Container Booking, jadi peran yang menangani email
  customer belum bisa membuat booking lift-on. Keputusan kebijakan, bukan bug.
- Tank terjepit (kasus PCVU2606202) ditunda ke rework EIR digital. Rencananya status item
  EIR `Pending — Awaiting Lift` + notifikasi lift, bukan mengubah `Container.status`.
- `customer_oak/` di root workspace adalah prototipe portal customer React yang sebenarnya;
  jalur Customer Desk di atas sifatnya sementara.
