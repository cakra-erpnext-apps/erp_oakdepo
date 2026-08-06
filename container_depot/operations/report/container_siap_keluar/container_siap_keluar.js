// Container Siap Keluar — reminder queue between a clean EIR-Out and the tank actually
// leaving. The "ACC Keluar" cell is a button rather than a value: the Desk user confirms the
// exit from the same list they read it in, and it calls the very endpoint the PWA calls
// (container_depot.ess.gate.gate_out), so both surfaces enforce the same guards.

frappe.query_reports["Container Siap Keluar"] = {
	filters: [
		{
			fieldname: "search",
			label: __("Cari"),
			fieldtype: "Data",
			description: __("No. container / bon muat / truk / sopir"),
		},
	],

	formatter(value, row, column, data, default_formatter) {
		if (column.fieldname === "acc") {
			if (!data || !data.container) return "";
			return `<button class="btn btn-xs btn-primary csk-acc" data-container="${frappe.utils.escape_html(
				data.container
			)}" data-label="${frappe.utils.escape_html(data.container_no || data.container)}">${__(
				"ACC Keluar"
			)}</button>`;
		}
		// A tank standing ready for days is the thing this report exists to surface.
		if (column.fieldname === "waiting" && data && /hari/.test(value || "")) {
			return `<span class="text-danger font-weight-bold">${frappe.utils.escape_html(value)}</span>`;
		}
		return default_formatter(value, row, column, data);
	},

	onload(report) {
		// Delegated so it survives every datatable re-render; namespaced so a report
		// refresh never stacks duplicate handlers (which would fire gate-out twice).
		$(report.page.wrapper)
			.off("click.cskAcc")
			.on("click.cskAcc", ".csk-acc", function () {
				const container = $(this).data("container");
				const label = $(this).data("label") || container;
				frappe.confirm(
					__("Konfirmasi {0} keluar depo (muat selesai)? Tindakan ini tidak bisa dibatalkan.", [
						`<b>${frappe.utils.escape_html(label)}</b>`,
					]),
					() => {
						frappe.call({
							method: "container_depot.ess.gate.gate_out",
							args: { container },
							freeze: true,
							freeze_message: __("Memproses gate-out …"),
							callback: (r) => {
								if (!r || r.exc) return;
								const done = r.message && r.message.order_completed;
								frappe.show_alert({
									message: done
										? __("{0} keluar — bon {1} selesai", [label, r.message.order_muat])
										: __("{0} keluar depo — gate-out selesai", [label]),
									indicator: "green",
								});
								report.refresh();
							},
						});
					}
				);
			});
	},
};
