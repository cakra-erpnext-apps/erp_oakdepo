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
	ptDue: "Tes Periodik Jatuh Tempo", // Periodic test due
	ptDueFlag: "PT Jatuh Tempo", // PT due (short)
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
