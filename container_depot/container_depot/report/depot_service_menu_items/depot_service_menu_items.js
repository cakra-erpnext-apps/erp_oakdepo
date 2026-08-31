// Filter tunggal: satu menu saja, kalau yang dicari memang satu picker tertentu.
// Tanpa filter, laporan menampilkan keempat menu berurutan sesuai sequence-nya —
// itu tampilan default yang diinginkan, jadi tidak ada filter yang wajib diisi.
frappe.query_reports["Depot Service Menu Items"] = {
	filters: [
		{
			fieldname: "menu",
			label: __("Menu"),
			fieldtype: "Link",
			options: "Depot Service Menu",
		},
	],

	// Status bukan sekadar teks: menu yang tidak membatasi apa pun harus terbaca sebagai
	// masalah, bukan sebagai baris biasa yang kebetulan kosong.
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "status" && data && data.status) {
			const colour = {
				"Aktif": "green",
				"Belum dipetakan": "red",
				"Dipetakan, tanpa item": "orange",
				"Non-aktif": "gray",
			}[data.status];
			if (colour) value = `<span class="indicator-pill ${colour}">${data.status}</span>`;
		}
		return value;
	},
};
