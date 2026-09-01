// Filter register cuci — sama untuk ketiga jenis. Tanggal disaring pada ORDER DATE,
// bukan tanggal cuci: order yang belum dicuci belum punya tanggal cuci, dan justru
// merekalah backlog yang dicari halaman ini.
frappe.query_reports["PP Wash Register"] = {
	filters: [
		{ fieldname: "principal", label: __("Principle"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "depot", label: __("Depot"), fieldtype: "Link", options: "Depot" },
		{ fieldname: "from_date", label: __("Order Date Dari"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("Order Date Sampai"), fieldtype: "Date" },
		{ fieldname: "only_outstanding", label: __("Hanya yang belum selesai"), fieldtype: "Check", default: 0 },
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "status" && data && data.status) {
			const colour = data.status === "Completed" ? "green" : "orange";
			value = `<span class="indicator-pill ${colour}">${data.status}</span>`;
		}
		return value;
	},
};
