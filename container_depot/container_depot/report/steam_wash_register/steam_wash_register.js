// Filter register cuci — sama untuk ketiga jenis. Tanggal bawaan ORDER DATE, bukan
// tanggal cuci: order yang belum dicuci belum punya tanggal cuci, dan justru merekalah
// backlog yang dicari halaman ini. Kolom tanggal lain bisa dipilih di "Tanggal".
frappe.query_reports["Steam Wash Register"] = {
	filters: [
		...container_depot.report_kit.filters([
			["order_date", "Order Date"],
			["plan_date", "Plan Date"],
			["wash_date", "Steam Wash Date"],
		]),
		{ fieldname: "principal", label: __("Principle"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "depot", label: __("Depot"), fieldtype: "Link", options: "Depot" },
		{ fieldname: "only_outstanding", label: __("Hanya yang belum selesai"), fieldtype: "Check", default: 0 },
	],

	onload: container_depot.report_kit.onload,

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		// Nomor tank membuka riwayat tank itu di register ini — pertanyaan berikutnya
		// setelah "order ini bagaimana" hampir selalu "sebelumnya bagaimana".
		if (column.fieldname === "tank_no" && data && data.tank_no) {
			return container_depot.tank_history_cell("Steam Wash", data.tank_no);
		}
		if (column.fieldname === "status" && data && data.status) {
			const colour = data.status === "Completed" ? "green" : "orange";
			value = `<span class="indicator-pill ${colour}">${data.status}</span>`;
		}
		return value;
	},
};
