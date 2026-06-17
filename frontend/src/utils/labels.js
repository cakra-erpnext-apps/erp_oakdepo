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
	navStorage: "Depot Storage", // Depot Storage tab
	navHistory: "Riwayat", // History tab (reachable from Home tile + EIR checklist)
	greeting: "Halo", // "Halo, {name}"
	homeHint: "Pilih menu untuk mulai bekerja", // Pick a menu to start
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
	gateScanPlaceholder: "Kode Booking / Order (OAK-… / ORD-…)",
	gateScan: "Scan Kamera", // Scan with camera
	gateScanClose: "Tutup", // Close scanner
	gateScanError: "Tidak bisa akses kamera — ketik kode manual.", // camera error
	gateScanHint: "Arahkan kamera ke QR booking / bon.", // aim camera hint
	gateLookup: "Cari", // Look up
	branch: "Cabang", // Branch
	bookingStatus: "Status Booking", // Booking status
	customer: "Customer (Shipper/Angkutan)", // Customer
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
	// Gate — vehicle / driver form before generating a bon (mirrors the Desk dialog)
	gateVehicleTitle: "Data Kendaraan & Sopir", // Vehicle & driver data
	gateVehicleHint: "Auto-isi dari container pertama — lengkapi bila perlu.",
	vCondition: "Kondisi", // Condition
	vRo: "R/O",
	vAngkutan: "Angkutan", // Transporter
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
	cargoHint: "Mengubah Last Cargo container — tersimpan saat EIR disubmit.",
	checklist: "Checklist Pemeriksaan", // Inspection checklist
	colItem: "Item",
	colDamage: "Kode Kerusakan", // Damage code
	colRepair: "Kode Perbaikan", // Repair code
	colRemarks: "Keterangan", // Remarks
	photo: "Foto", // Photo
	addPhoto: "Tambah Foto", // Add photo
	photoError: "Gagal mengunggah foto", // Photo upload failed
	acceptableHint: "Kosongkan baris yang kondisinya baik (Acceptable).", // Leave good rows blank
	signOff: "Tanda Tangan & Catatan", // Sign-off
	truckNo: "No. Truk", // Truck no
	emkl: "EMKL",
	driverPhone: "Nomor Driver", // Driver phone (from voucher)
	shipper: "Shipper", // Shipper (from voucher)
	referredVoucher: "Voucher Referensi", // Referred voucher (bon)
	voucherHintIn: "EIR-In: data diambil dari Order Bongkar.",
	voucherHintOut: "EIR-Out: data diambil dari Order Muat.",
	eirRemarks: "Catatan", // Remarks
	officer: "Petugas", // Officer
	saveDraft: "Simpan Draf", // Save draft
	submitEir: "Submit EIR",
	eirCreated: "EIR berhasil dibuat", // EIR created
	eirDraftHint: "Draf EIR otomatis dibuat/ dibuka saat ambil data.", // auto draft hint
	eirAutosaveHint: "Perubahan tersimpan otomatis.", // changes auto-saved
	savingDraft: "Menyimpan…", // Saving…
	draftSaved: "Tersimpan", // Saved
	eirSubmitted: "EIR berhasil disubmit", // EIR submitted
	newEir: "EIR container lain", // Start another container
	// EIR history (the user's own EIRs)
	eirHistory: "Riwayat", // History (short link on the checklist)
	eirHistoryTitle: "Riwayat EIR", // EIR history
	eirHistoryDesc: "Daftar EIR yang Anda buat", // EIRs you created
	eirHistorySearch: "Cari no. container / EIR…", // Search container no / EIR id
	prev: "Sebelumnya", // Previous
	next: "Berikutnya", // Next
	eirStatusDraft: "Draf", // Draft
	eirStatusSubmitted: "Submit", // Submitted
	eirStatusCancelled: "Batal", // Cancelled
	// Quick lists on the checklist landing (latest drafts / completed)
	eirDraftList: "EIR Draf", // Draft EIRs
	eirCompleteList: "EIR Selesai", // Completed EIRs
	eirListMore: "Lihat semua", // See all (-> history)
	eirDraftEmpty: "Belum ada draf EIR.", // No drafts yet
	eirCompleteEmpty: "Belum ada EIR selesai.", // No completed EIRs yet
	eirResume: "Lanjutkan", // Resume (open a draft)
	// Virtual signature (EIR creator)
	signature: "Tanda Tangan Pembuat EIR", // EIR creator signature
	signedBy: "Ditandatangani oleh", // Signed by
	signHint: "Tanda tangani di area di atas.", // Sign in the box above
	signAgain: "Tanda tangan ulang", // Re-sign
	clear: "Hapus", // Clear
	signatureError: "Gagal mengunggah tanda tangan", // Signature upload failed
	// Depot Storage (yard placement — Operator Kalmar)
	storage: "Depot Storage", // Home tile title
	storageDesc: "Susun & lacak isotank per zona", // tile subtitle
	storageTitle: "Depot Storage",
	storagePlaceTitle: "Tempatkan Isotank", // Place an isotank
	storagePlaceHint: "Masukkan nomor isotank — sistem menyarankan zona sesuai status.",
	storageContainerPlaceholder: "mis. NICU1234567",
	storageCheck: "Cek Rekomendasi", // Check recommendation
	storageStatus: "Status", // Status
	storageCondition: "Kondisi", // Tank condition
	storageTargetCategory: "Kategori Tujuan", // Target category
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

// Canonical 5-bucket status labels (Indonesian primary / English).
// Keys match the server-derived `status` buckets from the ESS endpoints.
export const statusLabels = {
	in_depot: "Di Depo", // In Depot
	cleaning: "Pencucian", // Cleaning
	repair_survey: "Perbaikan & Survei", // Repair & Survey
	ready: "Siap", // Ready
	gate_out: "Keluar Gate", // Gate Out
}

// Tailwind chip colours per bucket (frappe-ui theme tokens).
export const statusColors = {
	in_depot: "bg-blue-100 text-blue-800",
	cleaning: "bg-amber-100 text-amber-800",
	repair_survey: "bg-orange-100 text-orange-800",
	ready: "bg-leaf-100 text-leaf-800",
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
