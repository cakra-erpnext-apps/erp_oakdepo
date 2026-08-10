// Indonesian-primary UI labels with English fallback (PRD §7 Localisation).
// Keep this as the single source of label strings so pages stay translatable.
export const labels = {
	appName: "Depot OAK",
	home: "Beranda", // Home
	loggedInAs: "Masuk sebagai", // Logged in as
	logout: "Keluar", // Logout
	// Bottom nav + greeting (redesign)
	navHome: "Beranda", // Home tab
	navGate: "Gate",
	navEir: "EIR",
	navMonitor: "Monitor", // Monitor Container tab
	navProfile: "Profil", // Profile tab
	navHistory: "Riwayat", // History tab (reachable from Home tile + EIR checklist)
	// --- Profil (account + access overview) ---
	profileTitle: "Profil",
	profileBranchTitle: "Cakupan Branch",
	profileBranchAll: "Semua branch — tidak dibatasi",
	profileRolesTitle: "Peran",
	profileRolesEmpty: "Belum ada peran depot",
	profileAccessTitle: "Menu yang bisa dibuka",
	profileAccessEmpty: "Belum ada menu yang bisa dibuka",
	profileAccessHint: "Ditentukan dari izin akun Anda. Hubungi admin bila ada yang kurang.",
	// --- Ubah password (Profil) ---
	pwTitle: "Ubah Password",
	pwHint: "Ganti kata sandi akun Anda",
	pwOld: "Password Lama",
	pwNew: "Password Baru",
	pwConfirm: "Ulangi Password Baru",
	pwShow: "Tampilkan password",
	pwSubmit: "Simpan Password",
	pwSaving: "Menyimpan…",
	pwIncomplete: "Lengkapi semua kolom.",
	pwMismatch: "Password baru dan ulangannya tidak sama.",
	pwSame: "Password baru tidak boleh sama dengan yang lama.",
	pwSuccess: "Password berhasil diubah.",
	pwFailed: "Password gagal diubah.",
	pwWrongOld: "Password lama salah.",
	greeting: "Halo", // "Halo, {name}"
	homeHint: "Pilih menu untuk mulai bekerja", // Pick a menu to start
	// --- Dashboard (home KPI sections + menu groups) ---
	dashSummaryTitle: "Ringkasan Operasional", // collapsible KPI section header
	dashSummaryUnit: "unit", // "{n} unit" in collapsed summary
	dashSummaryTask: "tugas", // "{n} tugas" pending count in collapsed summary
	dashSummaryAlert: "alert", // "⚠ {n} alert" in collapsed summary
	dashSummaryLoading: "Memuat ringkasan…", // collapsed summary while loading
	dashSummaryUnavailable: "Ringkasan tidak tersedia", // collapsed summary on error
	dashSummaryHide: "Ketuk untuk sembunyikan", // expanded-state hint
	dashStatusTitle: "Status Container", // Container per status bucket
	dashStatusTotal: "Total", // "Total {n}" badge
	dashPtDue: "uji periodik jatuh tempo", // periodic-test-due flag suffix
	dashTodayTitle: "Aktivitas Hari Ini", // Today's activity
	dashTodayIn: "Gate In",
	dashTodayOut: "Gate Out",
	dashTodayEir: "EIR",
	dashPendingTitle: "Tugas Tertunda", // Pending tasks
	dashPendingApproval: "approval", // "{n} approval" sub-badge on M&R
	dashNoPending: "Tidak ada tugas tertunda 🎉", // empty pending state
	dashActiveJobs: "tank dengan job aktif", // supervisor card: tanks with work running
	dashPosSurvey: "Survey Posisi", // pending survey-position queue
	dashPosFix: "Position Fix", // pending "udah turun" approval queue
	// Shown when the server grants this account no PWA menu at all (office staff, or a
	// field user whose roles have not been assigned yet).
	menuEmptyTitle: "Belum ada menu untuk akun ini",
	menuEmptyBody: "Akun Anda belum diberi role lapangan. Hubungi Admin Ops untuk mendapatkan akses.",
	// Shortcut back to the Desk (ERPNext). Only rendered for accounts that actually have
	// Desk access — see menu.deskAccess.
	openDesk: "Buka Desk",
	openDeskHint: "Kelola booking, tarif, dan laporan di ERPNext.",
	// --- Offline / antrean kirim (data/outbox.js) ---
	draftRestored: "Draf lokal dipulihkan — isian terakhir Anda belum sempat terkirim.",
	queuedOffline: "Tersimpan di HP. Otomatis terkirim saat internet tersambung.",
	queueTitle: "Menunggu Terkirim",
	queueSending: "Mengirim…",
	queueOffline: "Tidak ada internet",
	queueFailedOne: "gagal",
	queueRetry: "Coba lagi",
	queueDiscard: "Buang",
	queueDiscardConfirm: "Data ini belum pernah terkirim ke server. Kalau dibuang, isinya hilang permanen.",
	queueSessionExpired: "Sesi berakhir. Login lagi supaya antrean bisa terkirim.",
	queueEmpty: "Semua sudah terkirim",
	queuePhotoPending: "menunggu kirim",
	dashYardTitle: "Okupansi Yard", // Yard occupancy
	dashYardEmpty: "Belum ada zona yard aktif", // empty yard state
	dashMenuTitle: "Menu", // menu section heading
	grpGate: "Gate", // workflow group: gate
	grpInspeksi: "Inspeksi", // workflow group: EIR / EIR Out
	grpPerawatan: "Perawatan", // workflow group: Cleaning / M&R
	grpYard: "Yard & Monitor", // workflow group: Storage / Monitor
	grpSurvey: "Survey Posisi", // workflow group: Container Position Survey (Lift On)
	// In-PWA notification bell
	notifications: "Notifikasi", // Notifications
	notifEmpty: "Belum ada notifikasi", // No notifications yet
	notifMarkAll: "Tandai semua dibaca", // Mark all read
	notifSound: "Suara notifikasi", // Notification sound toggle
	notifSoundOn: "Suara notifikasi aktif", // sound turned on
	search: "Cari nomor tank…", // Search tank number
	filter: "Filter",
	principal: "Prinsipal", // Principal
	status: "Status",
	yardZone: "Zona Yard", // Yard zone
	depot: "Depo", // Depot
	all: "Semua", // All
	loading: "Memuat…", // Loading
	error: "Terjadi kesalahan", // Something went wrong
	retry: "Coba lagi", // Retry
	empty: "Tidak ada data", // No data
	detail: "Detail Tank", // Tank detail
	type: "Tipe", // Type
	capacity: "Kapasitas", // Capacity
	tare: "Tara (kg)", // Tare
	maxGross: "Berat Kotor Maks (kg)", // Max gross weight
	lastCargo: "Muatan Terakhir", // Last cargo
	lastTest: "Tes Terakhir", // Last test date
	eirInDate: "Last EIR-In Date", // last EIR-In date from the Container master
	eirOutDate: "Last EIR-Out Date", // last EIR-Out date from the Container master
	location: "Lokasi Yard", // Yard location
	documents: "Dokumen", // Documents
	noDocuments: "Belum ada dokumen", // No documents yet
	viewPrint: "Lihat / Cetak", // View / Print
	repairs: "Perbaikan", // Repairs
	noRepairs: "Tidak ada perbaikan", // No repairs
	estimateTotal: "Total Estimasi", // Estimate total
	billing: "Penagihan", // Billing
	technician: "Teknisi", // Technician
	gate: "Gate", // Gate
	gateDesc: "Scan / validasi booking & terbitkan bon", // Scan/validate booking & issue bon
	bookingCode: "Kode Booking", // Booking code
	bookingCodePlaceholder: "OAK-XXXXXX", // placeholder
	validate: "Validasi", // Validate
	direction: "Arah", // Direction
	// Gate — scan/type a Booking or Order code → detail panel → per-container bon
	gateScanTitle: "Scan / Ketik Kode", // Scan / type code
	gateScanPlaceholder: "Kode / No. Kontainer (OAK-… / ORD-… / ABCD1234567)",
	gateChoicesTitle: "Beberapa booking aktif — pilih satu", // multiple active bookings, pick one
	gateScan: "Scan Kamera", // Scan with camera
	gateScanClose: "Tutup", // Close scanner
	gateScanError: "Tidak bisa akses kamera — ketik kode manual.", // camera error
	gateScanHint: "Arahkan kamera ke QR booking / bon.", // aim camera hint
	gateLookup: "Cari", // Look up
	branch: "Cabang", // Branch
	bookingStatus: "Status Booking", // Booking status
	customer: "Customer", // the booking's party — the hauler is its own `shipper` field now
	liftService: "Lift Service",
	paymentType: "Tipe Bayar", // Payment type
	paymentStatus: "Status Bayar", // Payment status
	doReference: "DO Reference",
	gateContainers: "Daftar Container", // Container list
	gatePayBlocked: "Pembayaran harus dibayar cash terlebih dahulu di kasir.", // Cash unpaid
	gateNotSubmitted: "Booking sudah dibayar tapi belum dikonfirmasi/disubmit — hubungi admin.", // paid but draft
	gateBlockedTitle: "Belum bisa diproses di gate", // gate blocked heading
	gateInvoiceNo: "No. Invoice", // Invoice no
	gateGenerate: "Generate Bon", // Generate bon
	gateSelectMax2: "Pilih maksimal 2 container per bon.", // max 2 per voucher
	gateGenerated: "Bon berhasil dibuat", // bon created
	gateNoContainers: "Tidak ada container.", // no containers
	gateBon: "Bon", // bon (short)
	// Gate — what the operator is actually doing right now: letting a tank in or out
	gateSectionBooking: "Data Booking", // booking identity block
	gateSectionPayment: "Pembayaran", // payment block (hidden when finance is off)
	gateSectionNote: "Catatan", // DO / remarks block
	gateReadyOut: "Siap keluar", // no open work — free to leave
	gateHeldBy: "Belum selesai", // container still held by open orders
	gateHeldHint: "Container ini tidak bisa keluar sebelum order di bawah selesai.",
	gateAlreadyOut: "Sudah keluar", // code already consumed by a bon
	// Gate — Shipper picker (Customer master, EMKL first)
	gateShipperEmkl: "EMKL / Transporter", // group header: customers flagged is_transporter
	gateShipperOther: "Customer", // group header: everyone else
	gateShipperEmpty: "Customer tidak ditemukan",
	// Gate — vehicle / driver form before generating a bon (mirrors the Desk dialog)
	gateVehicleTitle: "Data Kendaraan & Sopir", // Vehicle & driver data
	gateVehicleHint: "Auto-isi dari container pertama — lengkapi bila perlu.",
	optional: "opsional", // optional-field tag on the vehicle/driver form
	gateRequiredMissing: "Lengkapi field wajib", // required field(s) still empty
	vCondition: "Kondisi", // Condition
	vRo: "R/O",
	vShipper: "Shipper / Angkutan / EMKL", // one hauler field, three names in daily use
	vDestination: "Tujuan", // Destination
	vDateBongkar: "Tanggal Bongkar",
	vDateMuat: "Tanggal Muat",
	cancelBtn: "Batal", // Cancel
	truckPlate: "Nopol Truk", // Truck plate
	driverName: "Nama Sopir", // Driver name
	registerGate: "Catat Gate-In", // Register gate-in
	gateOk: "Gate-in tercatat", // Gate registered
	codeInvalid: "Kode tidak valid / tidak aktif", // Invalid/inactive code
	reset: "Ulangi", // Reset/again
	ptDue: "Tes Periodik Jatuh Tempo", // Periodic test due
	ptDueFlag: "PT Jatuh Tempo", // PT due (short)
	// EIR (Equipment Interchange Receipt) checklist
	eir: "EIR",
	eirDesc: "Buat laporan kondisi kontainer (EIR)", // Create container condition report
	eirTitle: "Checklist EIR",
	eirCombinedSubtitle: "Pemeriksaan masuk & keluar dalam satu daftar", // In & Out in one worklist
	eirStartTitle: "Mulai Pemeriksaan", // start-work gate title
	eirStartHint: "Tekan mulai untuk membuka checklist. Waktu pengerjaan mulai dihitung dari sini.",
	eirStartBtn: "Mulai", // start button
	eirStartedAt: "Dimulai", // started-at label
	eirBadgeIn: "Masuk", // EIR-In badge
	eirBadgeOut: "Keluar", // EIR-Out badge
	eirBadge: "EIR", // queue navigator counter prefix ("EIR 2 / 5")
	eirNavPrev: "Sebelumnya", // queue navigator: previous EIR
	eirNavNext: "Berikutnya", // queue navigator: next EIR
	eirSelect: "Pilih", // enter batch-select mode
	eirSelectCancel: "Batal", // leave batch-select mode
	eirBatchOpen: "Buka", // open the picked EIRs as a navigable batch (no Mulai/submit needed)
	eirBatchExit: "Keluar dari batch", // leave the batch navigator
	eirPendingCount: "menunggu", // pending count suffix
	eirSource: "Sumber Data", // Source
	eirFetch: "Ambil Data", // Fetch
	containerNumber: "Nomor Container", // Container number (EIR is keyed on the unit)
	containerNumberPlaceholder: "mis. EIRU1234567",
	eirType: "Tipe EIR", // EIR type
	eirHeader: "Data Tank", // Tank header
	prefix: "Prefix",
	number: "Number",
	checkDigit: "Cd",
	vessel: "Vessel",
	serialNo: "Serial No",
	dateManufacture: "Tgl. Manufaktur", // Date of manufacture
	ownerPrincipal: "Prinsipal (Pemilik)", // Principal / owner (from Container master)
	exVessel: "Ex Vessel", // Ex vessel (from Container master)
	tanggal: "Tanggal", // Date
	tankStatus: "Status Tank", // Tank status
	emptyClean: "Empty Clean",
	emptyDirty: "Empty Dirty",
	laden: "Laden",
	cargo: "Cargo", // Cargo (sets the container's Last Cargo on submit)
	cargoSearch: "Cari cargo…", // Search cargo (searchable select)
	selectPlaceholder: "Pilih…", // Generic searchable-select placeholder
	selectSearch: "Cari…", // Generic searchable-select search box
	cargoHint: "Mengubah Last Cargo container — tersimpan saat EIR disubmit.",
	checklist: "Checklist Pemeriksaan", // Inspection checklist
	colItem: "Item",
	colDamage: "Kode Kerusakan", // Damage code
	colRepair: "Kode Perbaikan", // Repair code
	colRemarks: "Keterangan", // Remarks
	colRemarksManual: "Keterangan (isi manual, opsional)", // Note: manual only, never auto-filled
	photo: "Foto", // Photo
	addPhoto: "Tambah Foto", // Add photo
	photoError: "Gagal mengunggah foto", // Photo upload failed
	acceptableHint: "Kosongkan baris yang kondisinya baik (Acceptable).", // Leave good rows blank
	// Search-to-add checklist (only damaged parts are added)
	checklistSearchDamaged: "Cari section / part yang rusak…", // Search a section/part to add
	checklistEmpty: "Belum ada kerusakan. Cari section / part di atas untuk menambah.", // No damage added yet
	bookingCode: "Kode Booking", // Booking code (header)
	// Mandatory-before-submit (EIR-In)
	eirNeedComplete: "Lengkapi dulu sebelum submit:", // Complete before submitting
	eirNeedCargo: "Cargo (Last Cargo)",
	eirNeedTankStatus: "Status Tank",
	eirNeedSignature: "Tanda tangan",
	// Bulk "foto cepat" (no section) + section search
	bulkPhotoTitle: "Foto Cepat", // Quick photos (bulk, no section)
	bulkPhotoHint: "Foto dulu tanpa pilih section — admin yang menyortir ke section-nya nanti.", // Shoot first, sort later
	sectionSearch: "Cari section / item…", // Search section (area) or item
	sectionSearchEmpty: "Tidak ada yang cocok.", // Nothing matched
	// EIR photo sorting (admin)
	eirSortTitle: "Sortir Foto", // Sort photos
	eirSortDesc: "Beri section untuk foto cepat", // Assign a section to bulk photos
	eirSortEmpty: "Tidak ada EIR dengan foto belum disortir.", // No EIR needs sorting
	eirSortPhotosEmpty: "Semua foto sudah disortir. 🎉", // All photos sorted
	eirSortPick: "Pilih section untuk foto ini", // Pick a section for this photo
	eirSortAssigned: "Foto diberi section", // Photo assigned to a section
	eirSortUnsortedCount: "foto belum disortir", // N photos unsorted
	eirSortOpen: "Sortir", // Sort (button)
	signOff: "Tanda Tangan & Catatan", // Sign-off
	truckNo: "No. Truk", // Truck no
	emkl: "EMKL",
	driverPhone: "Nomor Driver", // Driver phone (from voucher)
	shipper: "EMKL", // read-only display (EIR detail) — kept short for the 2-col grid
	referredVoucher: "Voucher Referensi", // Referred voucher (bon)
	voucherHintIn: "EIR-In: data diambil dari Order Bongkar.",
	voucherHintOut: "EIR-Out: data diambil dari Order Muat.",
	eirRemarks: "Catatan", // Remarks
	reffDoc: "Reff Doc", // Reference document (optional; flows EIR -> Cleaning/M&R)
	reffDocHint: "No. dokumen referensi (opsional).", // reff doc hint
	reffDocAutoHint: "Terisi dari EIR, bisa diubah.", // reff doc auto-filled hint (cleaning/M&R)
	officer: "Petugas", // Officer
	saveDraft: "Simpan Draf", // Save draft
	submitEir: "Submit EIR",
	eirCreated: "EIR berhasil dibuat", // EIR created
	eirDraftHint: "Draf EIR otomatis dibuat/ dibuka saat ambil data.", // auto draft hint
	eirAutosaveHint: "Perubahan tersimpan otomatis.", // changes auto-saved
	autosaveHint: "Perubahan tersimpan otomatis.", // generic auto-save hint (cleaning + M&R)
	// Confirm-before-submit dialog (2-step "Anda yakin?")
	confirmSubmitTitle: "Submit order?",
	confirmSubmitMessage: "Anda yakin untuk submit order ini? Tindakan ini tidak bisa dibatalkan.",
	confirmSubmitYes: "Ya, Submit",
	confirmCancel: "Batal",
	// TANK OUT — gate-out / load-complete action (Monitor)
	gateOutAction: "Gate-Out",
	gateOutConfirmTitle: "Gate-Out / Muat Selesai?",
	gateOutConfirmMessage: "Konfirmasi isotank keluar depo (muat selesai)? Tindakan ini tidak bisa dibatalkan.",
	gateOutDone: "Isotank keluar depo — gate-out selesai",
	// SIAP KELUAR — antrean pengingat antara EIR-Out bersih dan tank benar-benar keluar.
	readyOutTitle: "Siap Keluar",
	readyOutDesc: "ACC tank yang sudah lolos EIR-Out untuk keluar depo",
	readyOutSubtitle: "Menunggu ACC keluar",
	readyOutSearch: "Cari container / bon muat / truk…",
	readyOutEmpty: "Tidak ada tank yang menunggu ACC keluar",
	readyOutCount: "tank menunggu",
	readyOutHint: "Tank di bawah sudah lolos EIR-Out. Tekan ACC Keluar hanya setelah tank benar-benar naik truk dan meninggalkan depo.",
	readyOutSince: "Siap sejak",
	readyOutWaitingMin: "menit",
	readyOutWaitingHour: "jam",
	readyOutWaitingDay: "hari",
	readyOutBon: "Bon Muat",
	readyOutNoBon: "Tanpa Bon Muat",
	readyOutDest: "Tujuan",
	readyOutAcc: "ACC Keluar",
	readyOutAccTitle: "ACC keluar depo?",
	readyOutAccMessage: "Tank sudah naik truk dan meninggalkan depo? Setelah di-ACC, container tercatat Gate-Out dan tidak bisa dibatalkan.",
	readyOutOrderDone: "Bon muat selesai",
	// EIR Out (Fase G — surveyor load-out inspection vs last EIR-In)
	eirOutTitle: "EIR Out",
	eirOutSubtitle: "Survey keluar — banding EIR-In terakhir",
	eirOutDesc: "Inspeksi tank sebelum dimuat keluar",
	eirOutSearch: "Cari no. container / Order Muat…",
	eirOutEmpty: "Tidak ada EIR-Out menunggu",
	eirOutNoOrder: "Tanpa Order Muat",
	eirOutCompare: "Banding EIR-In Terakhir",
	eirOutPrevDamage: "Temuan saat EIR-In",
	eirOutPrevClean: "EIR-In: tidak ada temuan",
	eirOutPrevPhotos: "Foto EIR-In",
	eirOutNoBaseline: "Tidak ada EIR-In sebelumnya untuk dibandingkan",
	eirOutWillReady: "Akan jadi READY TO LOAD",
	// Seal numbers fitted at load-out — the one thing EIR-Out records beyond photos
	eirOutSealsTitle: "No. Seal",
	eirOutSealsHint: "Catat setiap segel yang terpasang. Tambah baris sebanyak segelnya.",
	eirOutSealNoPlaceholder: "Nomor segel",
	eirOutSealRemarkPlaceholder: "Keterangan (posisi segel, dll) — opsional",
	eirOutSealAdd: "Tambah Seal",
	// Field submit is a HAND-OFF, not a finalisation: it parks the EIR-Out on Pending
	// Review for Adm Ops. Ready To Load — and the Kalmar notification — only happen
	// when Adm Ops submits it on the Desk, so the wording must not promise them now.
	eirOutConfirmReadyTitle: "Kirim EIR-Out untuk review?",
	eirOutConfirmReadyMsg: "EIR-Out dikirim ke Adm Ops — setelah mereka submit, Order Muat jadi READY TO LOAD dan Operator Kalmar diberi tahu.",
	eirOutSealsRecorded: "Seal tercatat",
	eirOutNoSealWarn: "⚠ Belum ada nomor seal yang dicatat.",
	eirOutBackToList: "Kembali ke daftar",
	savingDraft: "Menyimpan…", // Saving…
	draftSaved: "Tersimpan", // Saved
	eirSubmitted: "EIR berhasil disubmit", // EIR submitted
	eirSendReview: "Kirim untuk Review", // field submit -> Pending Review (Admin Ops finalises)
	eirSentForReview: "EIR terkirim untuk review Adm Ops", // sent-for-review toast
	newEir: "EIR container lain", // Start another container
	// EIR history (the user's own EIRs)
	eirHistory: "Riwayat", // History (short link on the checklist)
	eirHistoryTitle: "Riwayat EIR", // EIR history
	eirHistoryDesc: "Daftar EIR yang Anda buat", // EIRs you created
	eirHistorySearch: "Cari no. container / EIR…", // Search container no / EIR id

	// --- Riwayat (history) menus — shared ---
	historySection: "Riwayat", // Home section heading for all history menus
	depotLabel: "Depot", // generic depot field label (detail grids)

	// Gate history
	gateHistoryTitle: "Riwayat Gate",
	gateHistoryDesc: "Voucher gate-in/out yang sudah dibuat",
	gateHistorySearch: "Cari container / truk / booking…",
	gateHistoryCount: "gate entry",
	gateTruck: "No. Truk",
	gateDriver: "Sopir",
	gateBooking: "Booking",
	gateInTime: "Gate In",
	gateOutTime: "Gate Out",
	gateOrder: "Order",
	gateEir: "EIR",
	gateStatus: {
		Active: "Aktif",
		Gate_In_Completed: "Gate-In Selesai",
		EIR_Completed: "EIR Selesai",
		Gate_Out_Completed: "Gate-Out Selesai",
		Cancelled: "Batal",
	},

	// Cleaning history
	cleaningHistoryTitle: "Riwayat Cleaning",
	cleaningHistoryDesc: "Cleaning order selesai / batal",
	cleaningHistoryCount: "cleaning order",
	cleaningStatusCompleted: "Selesai",
	cleaningStatusCancelled: "Batal",
	cleaningDateIssue: "Tgl. Terbit",

	// M&R history
	mrHistoryTitle: "Riwayat M&R",
	mrHistoryDesc: "Repair order selesai / ditolak / batal",
	mrHistorySearch: "Cari no. container / repair…",
	mrHistoryCount: "repair order",
	mrDamages: "Kerusakan",
	mrUsedItems: "Item Dipakai",
	mrTechnician: "Teknisi",

	// Storage (yard movement) history
	storageHistoryTitle: "Riwayat Storage",
	storageHistoryDesc: "Pergerakan & penempatan container di yard",
	storageHistorySearch: "Cari no. container…",
	storageHistoryCount: "pergerakan",
	storageZoneMove: "Perpindahan Zona",
	storageStatusMove: "Perubahan Status",
	storageMovedBy: "Oleh",
	storageEvent: { Yard: "Yard", Status: "Status", Combined: "Yard + Status" },

	// Monitor (container activity) history
	monitorHistoryTitle: "Riwayat Monitor",
	monitorHistoryDesc: "Linimasa aktivitas container",
	monitorHistorySearch: "Cari no. container / aktivitas…",
	monitorHistoryCount: "aktivitas",
	monitorRefDoc: "Dokumen",
	monitorPerformedBy: "Oleh",

	// EIR history detail
	eirHistoryCount: "EIR",
	eirTankStatus: "Status Tank",
	eirDate: "Tanggal",
	eirVoucher: "Voucher",
	eirTruck: "No. Truk",
	eirDriver: "Sopir",
	eirEmkl: "Shipper / EMKL", // one hauling party — the EIR's own emkl field was merged into shipper
	eirDamages: "Kerusakan",
	eirNoDamage: "Tidak ada kerusakan dicatat.",
	eirDamageCode: "D",
	eirRepairCode: "R",
	// Request edit/revision on a completed EIR (notifies Admin Ops)
	eirReqRevision: "Ajukan Revisi ke Admin Ops", // Request revision
	eirReqRevisionHint: "Minta Admin Ops membuka EIR ini agar bisa diperbaiki.",
	eirReqRevisionReason: "Alasan revisi (opsional)", // Revision reason
	eirReqRevisionSend: "Kirim Permintaan", // Send request
	eirReqRevisionSent: "Permintaan revisi terkirim ke Admin Ops", // Sent toast
	// Withdraw a Pending-Review EIR back to Draft (operator fixes it themselves)
	eirWithdrawReview: "Tarik & Perbaiki", // Withdraw from review + edit
	eirWithdrawReviewHint: "Tarik EIR ini dari antrean review agar bisa diperbaiki, lalu kirim ulang.",
	eirWithdrawReviewDone: "EIR ditarik — silakan perbaiki lalu kirim ulang", // Done toast

	prev: "Sebelumnya", // Previous
	next: "Berikutnya", // Next
	eirStatusDraft: "Draf", // Draft
	eirStatusSubmitted: "Selesai", // Submitted (finalised by Admin Ops)
	eirStatusCancelled: "Batal", // Cancelled
	eirStatusPendingReview: "Menunggu Review", // Pending Review (sent for Admin Ops review)
	eirStatusRevision: "Revisi Diminta", // Submitted EIR with a pending revision request
	// Quick lists on the checklist landing (latest drafts / completed)
	eirDraftList: "EIR Draf", // Draft EIRs
	eirCompleteList: "EIR Selesai", // Completed EIRs
	eirReviewList: "Diajukan Review", // Sent for Admin Ops review (Pending Review)
	eirReviewEmpty: "Tidak ada EIR menunggu review.", // No EIRs awaiting review
	eirReviewCount: "menunggu review", // review count suffix
	eirListMore: "Lihat semua", // See all (-> history)
	eirDraftEmpty: "Belum ada draf EIR.", // No drafts yet
	eirCompleteEmpty: "Belum ada EIR selesai.", // No completed EIRs yet
	eirResume: "Lanjutkan", // Resume (open a draft)
	// Pending EIR worklist (auto-created per container when an Order Bongkar is submitted)
	eirPendingList: "EIR Menunggu Pemeriksaan", // EIRs awaiting inspection
	eirPendingEmpty: "Belum ada EIR menunggu. EIR otomatis dibuat saat Order Bongkar di-submit.", // none pending
	eirPendingSearch: "Cari no. container / voucher…", // search container no / voucher
	// Worklist status split — a draft EIR is "belum" until Mulai stamps work_started_on,
	// then "dikerjakan"; submitted ones live in the Selesai section below.
	eirFilterAll: "Semua", // All
	eirFilterNotStarted: "Belum", // Not started
	eirFilterStarted: "Dikerjakan", // In progress
	eirChipStarted: "Dikerjakan", // row badge for an in-progress EIR
	eirFilterEmptyStarted: "Belum ada EIR yang sedang dikerjakan.", // no in-progress EIRs
	eirFilterEmptyNotStarted: "Semua EIR sudah mulai dikerjakan. 🎉", // nothing left unstarted
	eirOpenBtn: "Buka", // Open (a pending EIR)
	eirBackToList: "Daftar EIR", // Back to the EIR worklist
	eirVoucherLocked: "Otomatis dari Order Bongkar saat bon dibuat.", // voucher fixed at creation
	// Follow-up order opt-outs on the EIR (create Cleaning Order / M&R on submit)
	eirFollowupTitle: "Tindak Lanjut (Order Otomatis)", // follow-up orders section
	eirCreateCleaning: "Buat Cleaning Order", // create cleaning order toggle
	eirCreateCleaningHint: "Tank Empty Dirty — buat Cleaning Order saat submit.", // hint
	eirCreateRepair: "Buat M&R (Repair Order)", // create repair order toggle
	eirCreateRepairHint: "Ada kerusakan — buat draft M&R saat submit.", // hint
	// Virtual signature (EIR creator)
	signature: "Tanda Tangan Pembuat EIR", // EIR creator signature
	signedBy: "Ditandatangani oleh", // Signed by
	signHint: "Tanda tangani di area di atas.", // Sign in the box above
	signAgain: "Tanda tangan ulang", // Re-sign
	clear: "Hapus", // Clear
	signatureError: "Gagal mengunggah tanda tangan", // Signature upload failed
	// Cleaning Order (ISO tank cleanliness — cleaning team)
	cleaningTitle: "Cleaning Order", // page + Home tile + nav title
	cleaningDesc: "Kerjakan cleaning order & terbitkan sertifikat", // Home tile subtitle
	cleaningOrdersHint: "Pilih cleaning order untuk dikerjakan", // worklist hint
	cleaningCargoHistory: "Riwayat Cargo", // cargo history (from booking items)
	cleaningNoCargoHistory: "Belum ada riwayat cargo.", // no cargo history
	cleaningStartFull: "Mulai Cleaning", // start button (in form)
	cleaningStartFirst: "Mulai cleaning dulu sebelum bisa diselesaikan.", // gate hint
	cleaningStartGate: "Order ini belum dimulai. Mulai dulu untuk mengisi detail cleaning.", // detail-access gate
	cleaningSave: "Simpan", // save draft
	cleaningComplete: "Selesaikan (Submit)", // complete/submit
	cleaningSaved: "Tersimpan", // saved toast
	navCleaning: "Cleaning", // bottom-nav label
	cleaningOrdersSearch: "Cari no. container / order…",
	cleaningOrdersEmpty: "Tidak ada cleaning order terbuka.",
	createdOn: "Dibuat", // worklist row: created-on date prefix
	cleaningOrder: "Cleaning Order",
	cleaningType: "Metode Cleaning", // cleaning method (now one or more billable service items)
	cleaningNoMethod: "Metode cleaning belum diset oleh Admin Ops.", // read-only method not yet chosen upstream
	cleaningTypeUnset: "Belum diset", // not set
	cleaningSelectServices: "Pilih layanan cleaning (bisa lebih dari satu)", // multi-select hint
	cleaningServicesCount: "layanan", // worklist + count chip: "<n> layanan" (count, NOT price)
	cleaningSearchServices: "Cari layanan…", // catalogue search placeholder
	cleaningNoMatch: "Tidak ada layanan cocok.", // no catalogue match for the search
	cleaningNoPricedItems: "Owner belum punya layanan cleaning di price list.", // no priced items
	cleaningPending: "Pending",
	cleaningInProgress: "Dikerjakan", // In Progress
	cleaningStart: "Mulai", // start cleaning button
	cleaningStarted: "Cleaning dimulai", // started toast
	cleaningBack: "Kembali", // back to list
	cleaningTankDetails: "Data Tank",
	cleaningRefEir: "Referensi EIR",
	cleaningChecklist: "Checklist Kebersihan",
	cleaningYes: "Ya", // Yes
	cleaningNo: "Tidak", // No
	cleaningNote: "Catatan (bila tidak)…", // note when result is No
	cleaningGasFree: "Gas Free",
	cleaningO2: "O₂ %",
	cleaningLel: "LEL %",
	cleaningSeals: "Nomor Segel", // Seal numbers
	cleaningSealManhole: "Segel Manhole",
	cleaningSealAirline: "Segel Airline",
	cleaningSealBottom: "Segel Bottom Outlet",
	// QC photos
	cleaningQcPhotos: "Foto QC", // QC photos
	cleaningQcPhotoAdd: "Tambah Foto", // add photo
	cleaningQcPhotoEmpty: "Belum ada foto QC", // empty state
	cleaningSignature: "Tanda Tangan Surveyor", // surveyor signature
	cleaningResign: "Tanda tangan ulang", // re-sign
	cleaningUploading: "Mengunggah…", // uploading
	cleaningSubmitted: "Cleaning order selesai & sertifikat terbit", // completed toast
	cleaningPrint: "Cetak / Unduh PDF", // print / download
	cleaningTankType: "Tipe Tank",
	cleaningClient: "Client / Prinsipal",
	cleaningCapacity: "Kapasitas (L)",
	cleaningTare: "Tare (kg)",
	cleaningMgw: "MGW (kg)",
	cleaningPrevCargo: "Cargo Sebelumnya",
	cleaningMfgDate: "Tgl. Pembuatan",
	cleaningLastTest: "Last Test",
	// M&R (Maintenance & Repair — workshop team; auto-created from EIRs with damage)
	mrTitle: "M&R", // page + Home tile + nav title
	mrTitleFull: "M&R (Maintenance & Repair)",
	mrDesc: "Perbaikan/ganti part container dari temuan EIR", // Home tile subtitle
	navMr: "M&R", // bottom-nav label
	mrOrdersHint: "Pilih M&R untuk dikerjakan", // worklist hint
	mrOrdersSearch: "Cari no. container / M&R…",
	mrOrdersEmpty: "Tidak ada M&R terbuka.",
	mrBack: "Kembali",
	mrTankDetails: "Data Tank",
	mrRefEir: "Referensi EIR",
	// Source warehouse (top of form)
	mrWarehouse: "Gudang", // the gudang a used-item row is issued from (read-only here)
	// Section 1 — EIR damage entries (read-only copy, with photos)
	mrDamagesTitle: "Temuan Kerusakan (EIR)",
	mrNoDamages: "Tidak ada temuan kerusakan dari EIR.",
	mrCodeDamage: "Kerusakan",
	mrCodeRepair: "Perbaikan",
	// Section 2 — services & parts used (from the owner's Item Price)
	mrUsedTitle: "Service & Part Terpakai",
	mrUsedHint: "Pilih service/part dari Item Price owner. Stok part berkurang saat selesai.",
	mrAddUsed: "Tambah Item",
	mrNoUsed: "Belum ada item.",
	mrItem: "Item (Service / Part)",
	mrPickItem: "Pilih service / part…",
	mrPhotos: "Foto Bukti",
	mrAddPhoto: "Tambah Foto",
	mrPhotoUploading: "Mengunggah…",
	mrPhotoError: "Gagal mengunggah foto",
	mrQty: "Qty",
	mrOnHand: "Stok", // on-hand stock
	mrRemark: "Catatan",
	mrRemarks: "Catatan Umum",
	mrSearchItem: "Cari item…",
	mrItemsEmpty: "Item tidak ditemukan (cek Item Price owner).",
	mrStartFull: "Mulai Perbaikan", // start repair (in form)
	mrStartFirst: "Mulai perbaikan dulu sebelum bisa diselesaikan.", // gate hint
	mrStart: "Mulai", // start (worklist)
	mrStarted: "Perbaikan dimulai", // started toast
	mrInProgress: "Dikerjakan", // In Progress chip
	mrSave: "Simpan", // save draft
	mrSaved: "Tersimpan",
	mrComplete: "Selesaikan", // complete (issues stock)
	mrCompleted: "M&R selesai & part dikeluarkan dari stok", // completed toast
	mrRemove: "Hapus", // remove part row
	// Owner approval (Fase B — depot records the owner's decision)
	mrStatus: "Status",
	mrTotal: "Total Estimasi", // estimate total
	mrSubmitApproval: "Ajukan ke Owner", // Draft/Revision -> Pending Approval
	mrSubmittedToast: "Diajukan ke owner",
	mrApprovalTitle: "Persetujuan Owner",
	mrApprovalHint: "Owner memutuskan tiap item. Hanya item disetujui yang dikerjakan & ditagih.",
	mrOwnerNote: "Catatan Owner",
	mrOwnerNotePlaceholder: "Alasan revisi / penolakan (opsional)…",
	mrLineApprove: "Setujui",
	mrLineReject: "Tolak",
	mrApprove: "Setujui Semua / Sebagian",
	mrReject: "Tolak Semua",
	mrRequestRevision: "Minta Revisi",
	mrDecisionToast: "Keputusan tersimpan",
	mrRevisionBanner: "Owner minta revisi. Sesuaikan item lalu ajukan lagi.",
	mrRejectedBanner: "M&R ditolak owner.",
	mrApprovedReadonly: "Estimasi disetujui — siap dikerjakan.",
	mrAwaitingDecision: "Menunggu keputusan owner.",
	mrNeedItemFirst: "Tambahkan minimal satu item dulu.",
	// PWA M&R = execution-only console (divisi lapangan): only approved work, start -> done.
	mrExecInProgress: "Sedang dikerjakan.",
	mrExecPartsTitle: "Part Disetujui",
	mrExecOrdersHint: "M&R siap dikerjakan", // worklist hint
	mrExecEmpty: "Tidak ada M&R siap dikerjakan.",
	mrExecErpBanner: "Order ini masih dalam persetujuan — dikelola di ERP.",
	mrExecStartGate: "Mulai perbaikan dulu untuk melihat detail pekerjaan.", // start-first gate
	// --- Periodic Test (Uji Periodik 2,5Y / 5Y) — M&R-style execution console ---
	navPt: "Uji Periodik", // Home tile + history label
	ptTitleFull: "Uji Periodik (Periodic Test)",
	ptDesc: "Uji tekanan berkala tank (2,5Y / 5Y)", // Home tile subtitle
	ptSearch: "Cari no. container / PTO…",
	ptBack: "Kembali",
	ptExecOrdersHint: "Uji periodik siap dikerjakan", // worklist hint
	ptExecEmpty: "Tidak ada uji periodik siap dikerjakan.",
	ptExecErpBanner: "Order ini masih dalam persetujuan — dikelola di ERP.",
	ptExecStartGate: "Mulai uji dulu untuk melihat detail pekerjaan.", // start-first gate
	ptExecInProgress: "Sedang dikerjakan.",
	ptStartFull: "Mulai Uji", // start (in form)
	ptStarted: "Uji dimulai", // started toast
	ptComplete: "Selesaikan", // complete (issues stock + advances due date)
	ptCompleted: "Uji periodik selesai — jatuh tempo berikutnya diperbarui", // completed toast
	ptPartsTitle: "Jasa & Part Disetujui",
	ptTestInfoTitle: "Detail Uji",
	ptTestType: "Jenis Uji",
	ptPeriodicDate: "Tanggal Uji",
	ptPeriodicDateHint: "Tanggal uji dilakukan — jadi dasar jatuh tempo berikutnya.",
	ptNextDue: "Jatuh Tempo Berikutnya",
	ptLastTest: "Uji Terakhir",
	ptHistoryTitle: "Riwayat Uji Periodik",
	ptHistorySearch: "Cari no. container / PTO…",
	ptHistoryCount: "uji periodik",
	// Depot Storage (yard placement — Operator Kalmar)
	storage: "Depot Storage", // Home tile title
	storageDesc: "Susun & lacak isotank per zona", // tile subtitle
	// --- Container Position Survey (Lift On) ---
	surveyPosTitle: "Survey Container Position", // Surveyor menu/screen
	surveyPosDesc: "Cari & petakan posisi container", // tile subtitle
	surveyPosSearch: "Cari no. container / CPS…",
	surveyPosEmpty: "Tidak ada container untuk disurvei.",
	surveyPosCount: "container",
	surveyPosSection: "Letak Container",
	surveyPosLocation: "Letak container di mana?",
	surveyPosLocationHint: "mis. blok kanan dekat pos, tumpukan 2",
	surveyPosPhotos: "Foto Posisi",
	surveyPosNotes: "Catatan Tambahan",
	surveyPosSave: "Simpan Posisi",
	surveyPosSaved: "Posisi tersimpan",
	// Operator Kalmar approval
	posFixTitle: "Opt Kalmar Container Position Fix", // Kalmar menu/screen
	posFixDesc: "Approve container 'udah turun'", // tile subtitle
	posFixEmpty: "Tidak ada posisi menunggu approval.",
	posFixSurveyed: "Posisi Hasil Survey",
	posFixNote: "Catatan (opsional)",
	posFixNoteHint: "mis. sudah diturunkan ke ground slot",
	posFixApprove: "Approve (Udah Turun)",
	posFixApproved: "Posisi di-approve",
	posFixConfirmTitle: "Approve posisi?",
	posFixConfirmMsg: "Konfirmasi container sudah turun & posisinya benar. Setelah di-approve, survey difinalisasi.",
	// Survey Posisi history (finished surveys — Confirmed / Cancelled)
	surveyPosHistoryTitle: "Riwayat Survey Posisi",
	surveyPosHistoryDesc: "Survey posisi selesai / batal",
	surveyPosHistoryCount: "survey",
	surveyPosStatusConfirmed: "Selesai", // Confirmed
	surveyPosStatusSurveyed: "Disurvei", // Surveyed
	surveyPosStatusPending: "Menunggu", // Pending Survey
	surveyPosStatusCancelled: "Batal", // Cancelled
	surveyPosApprovedBy: "Di-approve oleh",
	surveyPosSurveyedBy: "Disurvei oleh",
	// Monitor Container (inventory list, filter by status + principal)
	monitorTitle: "Monitor Container", // page title
	monitorDesc: "Pantau container per status & prinsipal", // Home tile subtitle
	monitorSearch: "Cari nomor container…", // search placeholder
	monitorAll: "Semua", // all statuses
	monitorAllPrincipals: "Semua Prinsipal", // principal filter default
	monitorAllDepots: "Semua Depot", // depot filter default
	monitorEmpty: "Tidak ada container untuk filter ini.", // empty state
	monitorPtDue: "PT jatuh tempo", // periodic test due flag
	monitorToday: "Hari Ini", // today filter
	storageTitle: "Depot Storage",
	storagePlaceTitle: "Tempatkan Isotank", // Place an isotank
	storagePlaceHint: "Masukkan nomor isotank — sistem menyarankan zona sesuai status.",
	storageContainerPlaceholder: "mis. NICU1234567",
	storageCheck: "Cek Rekomendasi", // Check recommendation
	storageStatus: "Status", // Status
	storageCondition: "Kondisi", // Tank condition
	storageTargetCategory: "Kategori Tujuan", // Target category
	storageCurrentPos: "Posisi Sekarang", // current placement of the tank
	storageEirTitle: "Hasil Inspeksi EIR Terakhir", // Latest EIR result
	storageEirCargo: "Cargo", // Cargo
	storageEirTank: "Status Tank", // Tank status
	storageEirBy: "Pembuat EIR", // EIR created by
	storageDamages: "Kerusakan", // Damages
	storageNoDamage: "Tidak ada kerusakan tercatat.", // no damage logged
	storageShowPhotos: "Lihat foto", // show damage photos
	storageHidePhotos: "Sembunyikan foto", // hide damage photos
	storageRemarks: "Catatan", // Remarks
	storageNoEir: "Belum ada EIR yang disubmit untuk container ini.", // no submitted EIR
	storageRecommended: "Disarankan", // Recommended
	storageNoRecommend: "Tidak ada zona yang cocok untuk status ini.", // no match
	storageNoDepot: "Container belum di-assign ke depot — set depot-nya dulu (master Container) sebelum atur zona.", // container has no depot
	storageSelectZone: "Pilih zona penempatan", // pick a zone
	storageManualPick: "Pilih zona manual / lainnya", // manual zone picker toggle
	storageRow: "Baris", // Row
	storageTier: "Tumpukan", // Tier
	storageBay: "Bay",
	storageOptional: "opsional", // optional
	storagePlace: "Tempatkan", // Place
	storagePlaced: "Isotank ditempatkan", // placed ok
	storageOccupancy: "Okupansi Zona", // Zone occupancy
	storageFull: "Penuh", // Full
	storageSlotsFree: "slot kosong", // slots free
	storageNoZones: "Belum ada zona untuk depo ini.", // no zones
	storageZoneTanks: "Isotank di zona", // Tanks in zone
	storageNoTanks: "Belum ada isotank di zona ini.", // no tanks
	storageSop: "Panduan SOP Penyusunan", // Stacking SOP guide
	storageBranch: "Branch", // branch label in the storage header
	storageLoadMore: "Muat lebih", // load more
	storageSearchTank: "Cari nomor container…", // search containers in a zone
	storageShowing: "menampilkan", // "X dari Y menampilkan"
	storageOf: "dari", // X dari Y
}

// Canonical Monitor status buckets — order-state per container (Indonesian / English).
// Keys match the server-derived `status` buckets from the ESS endpoints.
export const statusLabels = {
	available: "Available", // no open order
	draft: "Draft", // M&R created, not submitted
	pending: "Pending", // queued / awaiting approval
	in_progress: "Dikerjakan", // cleaning / M&R started
	gate_out: "Keluar", // Gate Out
}

// Tailwind chip colours per bucket (frappe-ui theme tokens).
export const statusColors = {
	available: "bg-leaf-100 text-leaf-800",
	draft: "bg-gray-100 text-gray-700",
	pending: "bg-amber-100 text-amber-800",
	in_progress: "bg-blue-100 text-blue-800",
	gate_out: "bg-gray-200 text-gray-700",
}

export function statusLabel(bucket) {
	return statusLabels[bucket] || bucket || "—"
}

// Repair Order raw statuses -> Indonesian (English fallback via the raw value).
export const repairStatusLabels = {
	Draft: "Draf",
	"Pending Approval": "Menunggu Persetujuan",
	Approved: "Disetujui",
	Rejected: "Ditolak",
	"Revision Requested": "Minta Revisi",
	"In Progress": "Dikerjakan",
	Completed: "Selesai",
	Cancelled: "Dibatalkan",
}

export const billingLabels = {
	Unbilled: "Belum Ditagih",
	"Client Billed": "Ditagih ke Klien",
	"Principal Billed": "Ditagih ke Prinsipal",
	Completed: "Selesai",
}

export function repairStatusLabel(s) {
	return repairStatusLabels[s] || s || "—"
}

export function billingLabel(s) {
	return billingLabels[s] || s || "—"
}

export const directionLabels = {
	"Tank In": "Tank Masuk",
	"Tank Out": "Tank Keluar",
}

export function directionLabel(s) {
	return directionLabels[s] || s || "—"
}

// The same booking direction, in the gate operator's own words. The document says
// "Tank In / Tank Out"; the sign over their head says GATE IN / GATE OUT. Tailwind
// classes are spelled out in full because the scanner cannot see interpolated names.
export const gateDirections = {
	"Tank In": {
		label: "GATE IN",
		desc: "Container masuk depo",
		icon: "log-in",
		chip: "bg-leaf-100 text-leaf-800",
		tile: "bg-leaf-50 text-leaf-600",
		bar: "bg-leaf-500",
	},
	"Tank Out": {
		label: "GATE OUT",
		desc: "Container keluar depo",
		icon: "log-out",
		chip: "bg-amber-100 text-amber-800",
		tile: "bg-amber-50 text-amber-600",
		bar: "bg-amber-500",
	},
}

export function gateDirection(s) {
	return (
		gateDirections[s] || {
			label: directionLabel(s),
			desc: "",
			icon: "package",
			chip: "bg-gray-100 text-gray-700",
			tile: "bg-gray-100 text-gray-500",
			bar: "bg-gray-300",
		}
	)
}

// Format a number as Indonesian Rupiah.
export function rupiah(v) {
	if (v === null || v === undefined || v === "") return "—"
	return "Rp " + Number(v).toLocaleString("id-ID")
}

// Yard Zone category -> Indonesian label (keys match the server `category` enum).
export const categoryLabels = {
	"Empty Dirty Queue": "Antrean Cuci (Empty Dirty)",
	"Cleaning Bay": "Cleaning Bay",
	Ready: "Tank Ready",
	"Empty Clean": "Empty Clean",
	Workshop: "Workshop (Repair)",
	Survey: "Survey",
	Gate: "Gate",
}

export function categoryLabel(c) {
	return categoryLabels[c] || c || "—"
}

// Placement-relevant rules distilled from the OAK Isotank Workflow SOP — shown in
// the in-app "Panduan SOP" panel so the operator doesn't need the PDF on hand.
export const storageSopRules = [
	"Empty Dirty: tumpuk di Blok Kiri (antrean cuci); pasca-cuci pindah ke Blok Kanan sebagai Ready, dikelompokkan per principal.",
	"Empty Clean: letakkan di area siap pakai (Blok Kiri); bila penuh, alihkan ke Blok Kanan.",
	"OAK 2 hanya menerima Empty Clean (principal Bertschi & Eway).",
	"Stacking: maksimal 5 tumpuk ke atas; normal 5 baris, boleh sampai 6 baris saat depo penuh.",
	"Susun isotank hanya setelah Teknisi Foto & EIR selesai.",
]
