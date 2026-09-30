frappe.listview_settings["Pending Cash Refund"] = {
	add_fields: ["validated", "void"],

	// Draft -> Refunded (journal posted) -> Void (journal cancelled, kept as the trace).
	get_indicator(doc) {
		if (doc.void) return [__("Void"), "gray", "void,=,1"];
		if (doc.validated) return [__("Refunded"), "green", "validated,=,1"];
		return [__("Draft"), "orange", "validated,=,0"];
	},

	// PC: the Pending Cash this refund takes from — one refund may close several.
	formatters: {
		pending_cash_no(value) {
			return container_depot.pending_cash.doc_links(value, "Pending Cash");
		},
	},

	onload(listview) {
		listview.page.add_actions_menu_item(
			__("Void"),
			() => {
				const names = listview.get_checked_items(true);
				if (!names.length) return frappe.msgprint(__("Pilih dulu refund yang mau di-void."));
				frappe.confirm(__("Void {0} refund? Jurnalnya dibatalkan (tetap disimpan sebagai jejak).", [names.length]), () =>
					frappe
						.call({
							method: "container_depot.container_depot.doctype.pending_cash_refund.pending_cash_refund.bulk_void",
							args: { names },
							freeze: true,
						})
						.then((r) => {
							container_depot.pending_cash.report(r.message);
							listview.refresh();
						})
				);
			},
			true
		);
	},
};
