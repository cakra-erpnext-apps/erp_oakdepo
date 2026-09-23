frappe.query_reports["Leak Check Register"] = {
	filters: [
		{ fieldname: "principal", label: __("Principle"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "depot", label: __("Depot"), fieldtype: "Link", options: "Depot" },
		{ fieldname: "container", label: __("Tank No"), fieldtype: "Link", options: "Container" },
		{ fieldname: "from_date", label: __("Dicek Dari"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("Dicek Sampai"), fieldtype: "Date" },
		{ fieldname: "only_leak", label: __("Hanya yang bocor"), fieldtype: "Check", default: 0 },
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "has_leak" && data) {
			value = data.has_leak
				? `<span class="indicator-pill red">${__("Bocor")}</span>`
				: `<span class="indicator-pill green">${__("Aman")}</span>`;
		}
		return value;
	},
};
