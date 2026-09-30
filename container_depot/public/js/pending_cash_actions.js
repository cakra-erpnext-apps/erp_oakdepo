// Pending Cash actions, shared by the form and the list (hooks doctype_js / doctype_list_js).
frappe.provide("container_depot.pending_cash");

container_depot.pending_cash.run = function (names, action, extra, done) {
	const go = (args) =>
		frappe
			.call("container_depot.container_depot.doctype.pending_cash.pending_cash.run_action", {
				names: JSON.stringify(names),
				action,
				...args,
			})
			.then((r) => {
				const out = r.message || {};
				if (out.failed && out.failed.length) {
					frappe.msgprint({
						title: __("Sebagian gagal"),
						indicator: "orange",
						message: out.failed.map((f) => `<b>${f.name}</b>: ${frappe.utils.escape_html(f.error)}`).join("<br>"),
					});
				} else {
					frappe.show_alert({ message: __("{0} kasbon diproses", [out.done.length]), indicator: "green" });
				}
				done && done(out);
			});
	if (action !== "pay") return go({});
	const d = new frappe.ui.Dialog({
		title: __("Bayar Kasbon"),
		fields: [
			{ fieldtype: "Date", fieldname: "paid_date", label: __("Tanggal Bayar"), reqd: 1, default: frappe.datetime.get_today() },
			{ fieldtype: "Small Text", fieldname: "paid_notes", label: __("Catatan") },
		],
		primary_action_label: __("Bayar"),
		primary_action(v) {
			d.hide();
			go(v);
		},
	});
	d.show();
};

