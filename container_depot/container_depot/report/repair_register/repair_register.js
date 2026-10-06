// Tanggal bawaan TANGGAL M&R (plan_date) — tanggal order itu sendiri, yang juga dibaca
// penagihan. Kolom tanggal lain bisa dipilih di "Tanggal".
frappe.query_reports["Repair Register"] = {
	filters: [
		...container_depot.report_kit.filters([
			["plan_date", "Tanggal M&R"],
			["order_date", "Order Date"],
			["completion_date", "Completion Date"],
		]),
		{ fieldname: "principal", label: __("Principle"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "depot", label: __("Depot"), fieldtype: "Link", options: "Depot" },
		{ fieldname: "only_outstanding", label: __("Hanya yang belum selesai"), fieldtype: "Check", default: 0 },
	],

	onload: container_depot.report_kit.onload,

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "tank_no" && data && data.tank_no) {
			return container_depot.tank_history_cell("Repair", data.tank_no);
		}
		if (column.fieldname === "status" && data && data.status) {
			const colour = { Completed: "green", Rejected: "red" }[data.status] || "orange";
			value = `<span class="indicator-pill ${colour}">${data.status}</span>`;
		}
		return value;
	},
};
