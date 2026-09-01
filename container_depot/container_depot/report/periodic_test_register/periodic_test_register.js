// Tanggal disaring pada ORDER DATE, bukan Periodic Date: order yang belum diuji belum
// punya Periodic Date, dan justru merekalah antrean yang dicari halaman ini.
frappe.query_reports["Periodic Test Register"] = {
	filters: [
		{ fieldname: "principal", label: __("Principle"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "depot", label: __("Depot"), fieldtype: "Link", options: "Depot" },
		{ fieldname: "from_date", label: __("Order Date Dari"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("Order Date Sampai"), fieldtype: "Date" },
		{ fieldname: "only_outstanding", label: __("Hanya yang belum selesai"), fieldtype: "Check", default: 0 },
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		// Jatuh tempo yang sudah lewat sementara ujinya belum dikerjakan bukan tanggal
		// biasa: tank itu tidak boleh dipakai sampai diuji.
		if (column.fieldname === "due_date" && data && data.due_date && !data.periodic_date) {
			if (frappe.datetime.get_diff(data.due_date, frappe.datetime.get_today()) < 0) {
				value = `<span class="indicator-pill red">${value}</span>`;
			}
		}
		return value;
	},
};
