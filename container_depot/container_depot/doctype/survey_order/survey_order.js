// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Survey Order', {
	setup(frm) {
		frm.set_query('booking', () => ({
			filters: { direction: 'Tank Out', docstatus: ['<', 2], booking_status: ['!=', 'Cancelled'] },
		}));
	},
	// Add manual: form ini hanya memilih booking. Jadwalnya disusun oleh sinkron booking
	// (survey_order.create_from_booking), lalu form pindah ke dokumen hasilnya.
	booking(frm) {
		if (!frm.is_new() || !frm.doc.booking) return;
		frappe.call({
			method: 'container_depot.container_depot.doctype.survey_order.survey_order.create_from_booking',
			args: { booking: frm.doc.booking },
			freeze: true,
			callback: (r) => r.message && frappe.set_route('Form', 'Survey Order', r.message),
		});
	},
	refresh(frm) {
		container_depot.form_message(frm, 'from-booking', frm.is_new()
			? __('Pilih Booking (Tank Out). Jadwal survey dibuat dari booking tersebut.') : '', 'blue');
		// A day still in progress (draft) ends through the shared red Cancel — Frappe's
		// discard, which cancels its unfinished tanks with it. A Completed (submitted) day is
		// never cancelled: reopen the tank's lowering / survey instead.
		if (!frm.is_new() && frm.doc.docstatus === 0 && frappe.perm.has_perm(frm.doctype, 0, 'cancel')) {
			container_depot.cancel_button(frm, () => frm._discard());
		}
	},
});
