// "Storage Charges" — hari menginap per tank, dan berapa hari yang belum ditagih.
//
// Sengaja TANPA filter: begitu dibuka, semua tank tampil, satu baris per tank (kunjungan
// terbaru), sepanjang seluruh riwayat. Untuk melihat kunjungan-kunjungan lama sebuah tank,
// isi filter Container — daftar berubah jadi seluruh kunjungan tank itu.
//
// Kolom "Kunjungan Lama Belum Ditagih" ada supaya baris terbaru tidak menyembunyikan
// tagihan yang masih menggantung di kunjungan sebelumnya.
//
// Laporan ini tidak membuat invoice apa pun.
frappe.query_reports["Storage Charges"] = {
	filters: [
		{
			fieldname: "container",
			label: __("Container"),
			fieldtype: "Link",
			options: "Container",
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
		// Money still owed on an older visit of the same tank: set the Container filter to
		// see the visits themselves.
		if (column.fieldname === "older_unpaid_days" && data && data.older_unpaid_days > 0) {
			value = `<span style="color: var(--orange-600)"><b>${value}</b></span>`;
		}
		return value;
	},

	onload(report) {
		report.page.add_inner_message(
			"Laporan hitungan hari saja — tidak membuat invoice apa pun. " +
				"Satu baris = kunjungan terbaru tiap tank; isi filter <b>Container</b> untuk " +
				"melihat seluruh kunjungan tank itu. Cara charge storage & free days diatur " +
				"per pelanggan di <b>Depot Contract</b>."
		);
	},
};
