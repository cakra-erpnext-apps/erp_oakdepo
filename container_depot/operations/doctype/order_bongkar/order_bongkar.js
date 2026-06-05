// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Order Bongkar', {
	refresh(frm) {
		// Add/revise: only this booking's still-pending (Active) Booking Codes.
		// Codes already placed on another, unfinished voucher are Used, so they
		// won't appear here.
		frm.set_query('booking_code', 'containers', () => ({
			filters: { booking: frm.doc.booking, state: 'Active' }
		}));
		// A Bon Bongkar has no cleaning certificate.
		const grid = frm.fields_dict.containers.grid;
		grid.update_docfield_property('cleaning_certificate', 'hidden', 1);
		grid.refresh();
	},
	booking(frm) {
		_default_shipper(frm);
	}
});

function _default_shipper(frm) {
	if (frm.doc.booking && !frm.doc.shipper) {
		frappe.db.get_value('Isotank Booking', frm.doc.booking, 'customer', (r) => {
			if (r && r.customer) frm.set_value('shipper', r.customer);
		});
	}
}
