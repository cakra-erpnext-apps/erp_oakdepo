// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Survey Order', {
	refresh(frm) {
		// A day still in progress (draft) ends through the shared red Cancel — Frappe's
		// discard, which cancels its unfinished tanks with it. A Completed (submitted) day is
		// never cancelled: reopen the tank's lowering / survey instead.
		if (!frm.is_new() && frm.doc.docstatus === 0 && frappe.perm.has_perm(frm.doctype, 0, 'cancel')) {
			container_depot.cancel_button(frm, () => frm._discard());
		}
	},
});
