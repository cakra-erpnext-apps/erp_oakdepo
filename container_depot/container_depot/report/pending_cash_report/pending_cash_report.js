frappe.query_reports["Pending Cash Report"] = {
	filters: [
		...container_depot.report_kit.filters([
			["date", "Date"],
			["paid_date", "Paid Date"],
		]),
		{ fieldname: "direction", label: __("Arah"), fieldtype: "Select", options: "\nCash Outflow\nCash Inflow" },
		{ fieldname: "status", label: __("Status"), fieldtype: "Select", options: "\nDraft\nValidated\nPaid\nCompleted\nVoid" },
		{ fieldname: "pending_cash_type", label: __("Type"), fieldtype: "Link", options: "Pending Cash Type" },
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
	],

	onload: container_depot.report_kit.onload,

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "status" && data && data.status) {
			const colour = { Paid: "blue", Completed: "green", Void: "red", Draft: "gray" }[data.status] || "orange";
			value = `<span class="indicator-pill ${colour}">${data.status}</span>`;
		}
		return value;
	},
};
