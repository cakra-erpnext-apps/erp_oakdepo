// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Order Muat', {
	refresh(frm) {
		// Add/revise: only this booking's still-pending (Active) Booking Codes.
		frm.set_query('booking_code', 'containers', () => ({
			filters: { booking: frm.doc.booking, state: 'Active' }
		}));
		_lock_actions(frm);
	},
	booking(frm) {
		if (frm.doc.booking && !frm.doc.shipper) {
			frappe.db.get_value('Container Booking', frm.doc.booking, 'customer', (r) => {
				if (r && r.customer) frm.set_value('shipper', r.customer);
			});
		}
	}
});

function _lock_actions(frm) {
	// A bon is never deleted, duplicated, or used as a template for a New one —
	// it is Voided to release its containers (server also hard-blocks delete in on_trash).
	['Delete', 'Duplicate', __('New {0}', [__('Order Muat')])].forEach((label) => {
		frm.page.menu.find(`a[data-label="${encodeURIComponent(__(label))}"]`).parent().remove();
	});
	// Submitted bon → Cancel returns it to an editable Draft; Void soft-deletes it
	// (release codes, mark Cancelled, record kept). Draft bon → only Void.
	if (!frm.is_new() && frm.doc.docstatus === 1) {
		frm.add_custom_button(__('Cancel'), () => _confirm_revert(frm));
		frm.add_custom_button(__('Void'), () => _confirm_void(frm)).addClass('btn-danger');
	} else if (!frm.is_new() && frm.doc.docstatus === 0) {
		frm.add_custom_button(__('Void'), () => _confirm_void(frm)).addClass('btn-danger');
	}
}

function _confirm_revert(frm) {
	frappe.confirm(
		__('Return this bon to Draft so it can be edited? Its containers stay reserved (codes remain Used).'),
		() => {
			frappe.call({
				method: 'container_depot.operations.order_generation.revert_order_to_draft',
				args: { name: frm.doc.name, doctype: frm.doctype },
				freeze: true,
				freeze_message: __('Returning to draft …'),
				callback: () => frm.reload_doc(),
			});
		}
	);
}

function _confirm_void(frm) {
	frappe.confirm(
		__('Void this bon? Its containers are released (back to pending) and the bon is marked Cancelled — kept for audit, not deleted.'),
		() => {
			frappe.call({
				method: 'container_depot.operations.order_generation.void_order',
				args: { name: frm.doc.name, doctype: frm.doctype },
				freeze: true,
				freeze_message: __('Voiding …'),
				callback: () => frm.reload_doc(),
			});
		}
	);
}
