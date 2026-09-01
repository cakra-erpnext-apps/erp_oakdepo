frappe.query_reports["Gate Out Plan Register"] = {
	filters: [
		{ fieldname: "principal", label: __("Principle"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "status", label: __("Status"), fieldtype: "Select", options: "\nOpen\nFulfilled\nCancelled" },
		{ fieldname: "from_date", label: __("Plan Date Dari"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("Plan Date Sampai"), fieldtype: "Date" },
		{ fieldname: "only_open", label: __("Hanya yang masih Open"), fieldtype: "Check", default: 0 },
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		// Rencana yang tanggalnya sudah lewat sementara tanknya belum keluar bukan tanggal
		// biasa: itu tempat yang terpakai dan pekerjaan yang tertunda.
		if (column.fieldname === "plan_date" && data && data.status === "Open" && data.plan_date) {
			if (frappe.datetime.get_diff(data.plan_date, frappe.datetime.get_today()) < 0) {
				value = `<span class="indicator-pill red">${value}</span>`;
			}
		}
		if (column.fieldname === "status" && data && data.status) {
			const colour = { Fulfilled: "green", Cancelled: "gray", Open: "orange" }[data.status];
			if (colour) value = `<span class="indicator-pill ${colour}">${data.status}</span>`;
		}
		return value;
	},
};
