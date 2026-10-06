frappe.query_reports["Bon Report"] = {
	filters: [
		...container_depot.report_kit.filters([["bon_date", "Tanggal Bon"]]),
		{ fieldname: "kind", label: __("Jenis"), fieldtype: "Select", options: "\nBongkar\nMuat" },
		{ fieldname: "principal", label: __("Principle"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
		{ fieldname: "only_open", label: __("Hanya yang belum selesai"), fieldtype: "Check", default: 0 },
	],

	onload: container_depot.report_kit.onload,

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "status" && data && data.status) {
			const colour = { Completed: "green", Hold: "red", Issued: "gray" }[data.status] || "orange";
			value = `<span class="indicator-pill ${colour}">${data.status}</span>`;
		}
		return value;
	},
};
