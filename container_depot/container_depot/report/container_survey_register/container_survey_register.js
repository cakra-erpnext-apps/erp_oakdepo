frappe.query_reports["Container Survey Register"] = {
	filters: [
		{ fieldname: "principal", label: __("Principle"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "depot", label: __("Depot"), fieldtype: "Link", options: "Depot" },
		{ fieldname: "container", label: __("Tank No"), fieldtype: "Link", options: "Container" },
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "\nPending Survey\nIn Survey\nSurveyed\nIn Fix\nConfirmed",
		},
		{ fieldname: "from_date", label: __("Diminta Dari"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("Diminta Sampai"), fieldtype: "Date" },
		{ fieldname: "only_outstanding", label: __("Hanya yang belum selesai"), fieldtype: "Check", default: 0 },
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "status" && data && data.status) {
			const colour = {
				Confirmed: "green",
				Surveyed: "blue",
				"In Survey": "orange",
				"In Fix": "orange",
				"Pending Survey": "red",
			}[data.status];
			if (colour) value = `<span class="indicator-pill ${colour}">${data.status}</span>`;
		}
		return value;
	},
};
