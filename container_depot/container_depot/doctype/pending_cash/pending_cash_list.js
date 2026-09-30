// Pending Cash list: state indicator and the bulk actions. Each menu is one undo pair; which
// way it goes follows each selected document (public/js/pending_cash_actions.js).
frappe.listview_settings["Pending Cash"] = {
	add_fields: ["validated", "paid", "void", "settled", "modul", "company", "bank_account", "date", "direction"],

	get_indicator(doc) {
		if (doc.void) return [__("Void"), "gray", "void,=,1"];
		// Completed before Paid: Paid only says the money left, Completed that a submitted
		// payment has taken it into account.
		if (doc.paid && doc.settled) return [__("Completed"), "purple", "settled,=,1"];
		if (doc.paid) return [__("Paid"), "green", "paid,=,1"];
		if (doc.validated) return [__("Validated"), "blue", "validated,=,1"];
		return [__("Draft"), "orange", "validated,=,0"];
	},

	formatters: {
		// Source No is a Dynamic Link: its doctype is the row's `modul`.
		number(value, df, doc) {
			return doc.modul ? container_depot.pending_cash.doc_links(value, doc.modul) : "<span></span>";
		},
		payment_no(value) {
			return container_depot.pending_cash.doc_links(value, "Payment Entry");
		},
	},

	onload(listview) {
		const action = (kind) => () =>
			container_depot.pending_cash.run(kind, listview.get_checked_items(), () => listview.refresh());
		listview.page.add_actions_menu_item(__("Validate / Invalidate"), action("validate"), true);
		listview.page.add_actions_menu_item(__("Pay / Unpaid"), action("pay"), true);
		listview.page.add_actions_menu_item(__("Void / Unvoid"), action("void"), true);
		// From the list always ALL that is left; part of it is refunded from the form.
		listview.page.add_actions_menu_item(__("Refund"), action("refund"), true);
	},
};
