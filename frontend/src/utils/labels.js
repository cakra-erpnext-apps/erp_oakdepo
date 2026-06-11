// Indonesian-primary UI labels with English fallback (PRD §7 Localisation).
// Keep this as the single source of label strings so pages stay translatable.
export const labels = {
	appName: "Depot ESS",
	home: "Beranda", // Home
	inventory: "Inventaris Tank", // Tank Inventory
	loggedInAs: "Masuk sebagai", // Logged in as
	logout: "Keluar", // Logout
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
	gateDesc: "Validasi kode booking & catat gate-in", // Validate booking & gate-in
	bookingCode: "Kode Booking", // Booking code
	bookingCodePlaceholder: "OAK-XXXXXX", // placeholder
	validate: "Validasi", // Validate
	direction: "Arah", // Direction
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
	// Virtual signature (EIR creator)
	signature: "Tanda Tangan Pembuat EIR", // EIR creator signature
	signedBy: "Ditandatangani oleh", // Signed by
	signHint: "Tanda tangani di area di atas.", // Sign in the box above
	signAgain: "Tanda tangan ulang", // Re-sign
	clear: "Hapus", // Clear
	signatureError: "Gagal mengunggah tanda tangan", // Signature upload failed
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
	ready: "bg-green-100 text-green-800",
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
