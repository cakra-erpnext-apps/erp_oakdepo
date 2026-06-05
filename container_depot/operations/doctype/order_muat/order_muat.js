// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Order Muat', {
	refresh(frm) {
		// Add/revise: only this booking's still-pending (Active) Booking Codes.
		frm.set_query('booking_code', 'containers', () => ({
			filters: { booking: frm.doc.booking, state: 'Active' }
		}));
		// A Bon Muat needs a Cleaning Certificate per container — show + require it.
		const grid = frm.fields_dict.containers.grid;
		grid.update_docfield_property('cleaning_certificate', 'in_list_view', 1);
		grid.update_docfield_property('cleaning_certificate', 'reqd', 1);
		grid.refresh();
	},
	booking(frm) {
		if (frm.doc.booking && !frm.doc.shipper) {
			frappe.db.get_value('Isotank Booking', frm.doc.booking, 'customer', (r) => {
				if (r && r.customer) frm.set_value('shipper', r.customer);
			});
		}
	}
});
