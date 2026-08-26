// Filters for "Storage Charges" — the storage days ledger.
//
// Dibuka tanpa filter: semua kunjungan tampil. Pilih "Sesuai Kontrak" kalau mau menyaring
// ke apa yang boleh ditagih menurut kontrak tiap owner (Depot Contract -> Cara Charge
// Storage); dua pilihan lainnya menyaring berdasarkan kunjungannya sendiri, bukan kontrak.
//
// Satu baris = satu KUNJUNGAN. Defaultnya hanya kunjungan terbaru tiap tank — kecuali
// kunjungan lama yang masih punya hari belum ditagih, yang selalu ikut tampil supaya tidak
// hilang. Centang "Semua kunjungan" untuk melihat seluruh riwayat.
//
// This report never bills anything. It shows the days so they can be checked against the
// gate records BEFORE any invoice exists.
frappe.query_reports["Storage Charges"] = {
	filters: [
		{
			fieldname: "mode",
			label: __("Cara Charge"),
			fieldtype: "Select",
			options: ["", "Sesuai Kontrak", "Masih Menginap", "Sudah Keluar"].join("\n"),
			default: "",
		},
		{
			fieldname: "from_date",
			label: __("Dari Tanggal"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("Sampai Tanggal"),
			fieldtype: "Date",
			default: frappe.datetime.month_end(),
			reqd: 1,
		},
		{
			fieldname: "principal",
			label: __("Tank Owner"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "depot",
			label: __("Depot"),
			fieldtype: "Link",
			options: "Depot",
		},
		{
			fieldname: "container",
			label: __("Container"),
			fieldtype: "Link",
			options: "Container",
		},
		{
			fieldname: "all_visits",
			label: __("Semua kunjungan"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "show_zero",
			label: __("Tampilkan yang 0 hari"),
			fieldtype: "Check",
			default: 0,
		},
	],

	// A stay whose dates come from the status audit trail is timestamped when the tank was
	// SAVED, not when the truck moved — accurate for same-day entry, off by however long a
	// late entry was late. Colour it so a wrong-looking day count is traced to its cause
	// rather than to the arithmetic.
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "source" && data && data.source !== "Gate Entry") {
			value = `<span style="color: var(--text-muted)">${value}</span>`;
		}
		if (column.fieldname === "chargeable_days" && data && data.chargeable_days > 0) {
			value = `<b>${value}</b>`;
		}
		return value;
	},

	onload(report) {
		report.page.add_inner_message(
			"Laporan hitungan hari saja — tidak membuat invoice apa pun. " +
				"Cara charge storage & free days diatur per pelanggan di <b>Depot Contract</b>, " +
				"defaultnya di <b>Depot Finance Settings</b>."
		);
	},
};
