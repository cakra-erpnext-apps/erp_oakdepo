frappe.query_reports["Lift On Register"] = {
	filters: [
		...container_depot.report_kit.filters([
			["plan_date", "Pick up Date"],
		]),
		{ fieldname: "principal", label: __("Principle"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "\nDraft\nPengajuan\nPending Payment\nPending Confirmation\nConfirmed\nCompleted\nCancelled\nBlocked",
		},
		{ fieldname: "only_open", label: __("Hanya yang belum selesai"), fieldtype: "Check", default: 0 },
	],

	onload: container_depot.report_kit.onload,

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		const live = !["Completed", "Cancelled"].includes(data && data.status);
		// Rencana yang tanggalnya sudah lewat sementara tanknya belum keluar bukan tanggal
		// biasa: itu tempat yang terpakai dan pekerjaan yang tertunda.
		if (column.fieldname === "plan_date" && data && live && data.plan_date) {
			if (frappe.datetime.get_diff(data.plan_date, frappe.datetime.get_today()) < 0) {
				value = `<span class="indicator-pill red">${value}</span>`;
			}
		}
		if (column.fieldname === "status" && data && data.status) {
			const colour = {
				Completed: "green", Cancelled: "red", Confirmed: "blue",
				Blocked: "pink", Draft: "gray",
			}[data.status] || "orange";
			value = `<span class="indicator-pill ${colour}">${data.status}</span>`;
		}
		if (column.fieldname === "bon_status" && data && data.bon_status) {
			const colour = {
				"Belum Dibon": "orange", "Sebagian Dibon": "yellow", "Bon Lengkap": "green",
			}[data.bon_status] || "gray";
			value = `<span class="indicator-pill ${colour}">${data.bon_status}</span>`;
		}
		return value;
	},
};
