// Tanggal disaring pada TANGGAL PERIODIC TEST (plan_date), bukan Periodic Date: order yang belum diuji belum
// punya Periodic Date, dan justru merekalah antrean yang dicari halaman ini.
frappe.query_reports["Periodic Test Register"] = {
	filters: [
		...container_depot.report_kit.filters([
			["order_date", "Tanggal Periodic Test"],
			["periodic_date", "Periodic Date"],
			["last_pt_date", "Last PT Date"],
			["due_date", "Due Date"],
		]),
		{ fieldname: "principal", label: __("Principle"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "depot", label: __("Depot"), fieldtype: "Link", options: "Depot" },
		{ fieldname: "only_outstanding", label: __("Hanya yang belum selesai"), fieldtype: "Check", default: 0 },
	],

	onload: container_depot.report_kit.onload,

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		// Nomor tank membuka riwayat uji berkala tank itu — termasuk uji sebelumnya dan
		// invoice yang menagihnya.
		if (column.fieldname === "tank_no" && data && data.tank_no) {
			return container_depot.tank_history_cell("Periodic Test", data.tank_no);
		}
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
