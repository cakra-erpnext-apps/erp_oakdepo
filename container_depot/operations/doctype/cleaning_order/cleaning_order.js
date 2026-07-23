// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

// The "Metode Cleaning (Service)" table picks one OR MORE cleaning services the container
// Owner (Principal) is priced for: members of the Depot Service Menu "Cleaning" that have a
// selling Item Price in the owner's active Price List (resolved server-side from the
// container). Each row's rate is filled from that price list on save, and cleaning_total is
// their sum, so the order is ready to bill the tank owner.
frappe.ui.form.on('Cleaning Order', {
	onload(frm) {
		frm.trigger('_set_queries');
	},
	refresh(frm) {
		frm.trigger('_set_queries');
		frm.trigger('_forward_button');
	},
	_forward_button(frm) {
		// Admin Ops step: while the order is in "Service Setup" they pick the cleaning
		// method(s); the button forwards it to the depot operator worklist (-> Pending).
		if (frm.is_new() || frm.doc.docstatus !== 0 || frm.doc.status !== 'Service Setup') return;
		frm.add_custom_button(__('Teruskan ke Operator'), () => {
			if (!(frm.doc.cleaning_services || []).length) {
				frappe.msgprint(__('Pilih minimal satu metode cleaning (Service) dulu.'));
				return;
			}
			frm.set_value('status', 'Pending');
			frm.save().then(() => frappe.show_alert({ message: __('Diteruskan ke operator cuci.'), indicator: 'green' }));
		}).addClass('btn-primary');
	},
	container(frm) {
		// New container → its owner may price a different cleaning catalogue; drop the picks.
		if ((frm.doc.cleaning_services || []).length) frm.clear_table('cleaning_services');
		frm.refresh_field('cleaning_services');
		frm.trigger('_set_queries');
	},
	_set_queries(frm) {
		frm.set_query('cleaning_item', 'cleaning_services', () => ({
			query: 'container_depot.operations.doctype.cleaning_order.cleaning_order.cleaning_item_query',
			filters: { container: frm.doc.container || '' },
		}));
	},
});
