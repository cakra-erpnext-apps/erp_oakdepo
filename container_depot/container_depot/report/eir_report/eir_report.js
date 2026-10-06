frappe.query_reports["EIR Report"] = {
	filters: [
		...container_depot.report_kit.filters([["eir_date", "EIR Date"]]),
		{ fieldname: "inspection_type", label: __("Tipe EIR"), fieldtype: "Select", options: "\nEIR-In\nEIR-Out" },
		{ fieldname: "principal", label: __("Principle"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "depot", label: __("Depot"), fieldtype: "Link", options: "Depot" },
		{ fieldname: "only_damage", label: __("Hanya yang ada damage"), fieldtype: "Check", default: 0 },
	],

	onload: container_depot.report_kit.onload,

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "status" && data && data.status) {
			const colour = { Submitted: "green", "Pending Review": "purple", Draft: "gray" }[data.status] || "orange";
			value = `<span class="indicator-pill ${colour}">${data.status}</span>`;
		}
		return value;
	},
};
