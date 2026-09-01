// Tanggal disaring pada tanggal booking dibuat — booking yang belum dikonfirmasi belum
// punya tanggal lain apa pun, dan justru merekalah yang dicari di sini.
frappe.query_reports["Container Booking Register"] = {
	filters: [
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "principal", label: __("Principle"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "depot", label: __("Depot"), fieldtype: "Link", options: "Depot" },
		{ fieldname: "direction", label: __("Arah"), fieldtype: "Select", options: "\nTank In\nTank Out" },
		{
			fieldname: "booking_status",
			label: __("Status"),
			fieldtype: "Select",
			options: "\nDraft\nPending Payment\nPending Confirmation\nConfirmed\nCancelled\nBlocked",
		},
		{ fieldname: "from_date", label: __("Order Date Dari"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("Order Date Sampai"), fieldtype: "Date" },
		{ fieldname: "only_unpaid", label: __("Hanya yang belum dibayar"), fieldtype: "Check", default: 0 },
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "payment_status" && data && data.payment_status) {
			const colour = { Paid: "green", Invoiced: "blue", Unpaid: "orange", Cancelled: "gray" }[
				data.payment_status
			];
			if (colour) value = `<span class="indicator-pill ${colour}">${data.payment_status}</span>`;
		}
		if (column.fieldname === "booking_status" && data && data.booking_status) {
			const colour = {
				Confirmed: "green",
				Cancelled: "gray",
				Blocked: "red",
			}[data.booking_status];
			value = `<span class="indicator-pill ${colour || "orange"}">${data.booking_status}</span>`;
		}
		return value;
	},
};
