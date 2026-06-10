// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

// A single bon/voucher carries at most this many containers.
const MAX_CONTAINERS_PER_ORDER = 2;

// Vehicle/paperwork fields a second container inherits from the first row as an
// editable default. Everything else (condition / cargo / Tgl. Bongkar / remarks)
// defaults from that container's own booking line, not from row one.
const MIRROR_FROM_FIRST_ROW = ['truck_plate', 'driver', 'driver_phone', 'ro'];

frappe.ui.form.on('Order Bongkar', {
	refresh(frm) {
		// Add/revise: only this booking's still-pending (Active) Booking Codes.
		// Codes already placed on another, unfinished voucher are Used, so they
		// won't appear here.
		frm.set_query('booking_code', 'containers', () => ({
			filters: { booking: frm.doc.booking, state: 'Active' }
		}));
		// Manual add picks a Container — restrict it to containers with an Active
		// Booking Code on THIS voucher's booking, so a single bon can never mix
		// containers from different bookings (one booking → many vouchers, but a
		// voucher → one booking).
		frm.set_query('container', 'containers', () => ({
			query: 'container_depot.operations.doctype.order_bongkar.order_bongkar.pending_container_query',
			filters: { booking: frm.doc.booking },
		}));
		const grid = frm.fields_dict.containers.grid;
		// A Bon Bongkar has no cleaning certificate.
		grid.update_docfield_property('cleaning_certificate', 'hidden', 1);
		_lock_actions(frm);
		_strip_row_buttons(frm);
		_enforce_max_rows(frm);
		grid.refresh();
	},
	booking(frm) {
		_default_shipper(frm);
		_default_principal(frm);
	},
	containers_add(frm, cdt, cdn) {
		// A second container mirrors the first row's truck / driver / R-O as an
		// editable default; the rest comes from its own container's booking line.
		const rows = frm.doc.containers || [];
		if (rows.length <= 1) return;
		const first = rows[0];
		const row = locals[cdt][cdn];
		if (!first || first.name === row.name) return;
		MIRROR_FROM_FIRST_ROW.forEach((f) => {
			if (first[f] && !row[f]) frappe.model.set_value(cdt, cdn, f, first[f]);
		});
	}
});

function _lock_actions(frm) {
	// A bon is never deleted, duplicated, or used as a template for a New one —
	// it is Cancelled to release its containers. Strip those menu items (server
	// also hard-blocks delete in on_trash).
	['Delete', 'Duplicate', __('New {0}', [__('Order Bongkar')])].forEach((label) => {
		frm.page.menu.find(`a[data-label="${encodeURIComponent(__(label))}"]`).parent().remove();
	});
	// Saved draft → offer Cancel = void: release the booking codes (back to Active)
	// so the containers can be put on a fresh voucher, and mark it Cancelled. A
	// submitted bon keeps the native Cancel action (on_cancel releases the codes).
	if (!frm.is_new() && frm.doc.docstatus === 0) {
		frm.add_custom_button(__('Cancel'), () => _confirm_cancel(frm)).addClass('btn-danger');
	}
}

function _confirm_cancel(frm) {
	frappe.confirm(
		__('Cancel this bon? Its containers are released (back to pending) so they can be put on a new voucher.'),
		() => {
			frappe.call({
				method: 'container_depot.operations.doctype.order_bongkar.order_bongkar.cancel_order',
				args: { order: frm.doc.name },
				freeze: true,
				freeze_message: __('Cancelling …'),
				callback: () => frm.reload_doc(),
			});
		}
	);
}

function _default_shipper(frm) {
	if (frm.doc.booking && !frm.doc.shipper) {
		frappe.db.get_value('Container Booking', frm.doc.booking, 'customer', (r) => {
			if (r && r.customer) frm.set_value('shipper', r.customer);
		});
	}
}

function _default_principal(frm) {
	if (frm.doc.booking && !frm.doc.principal) {
		frappe.db.get_value('Container Booking', frm.doc.booking, 'principal', (r) => {
			if (r && r.principal) frm.set_value('principal', r.principal);
		});
	}
}

// Editing a container row should only let the operator tweak that row's values —
// not spawn extra rows. Hide Insert Above / Insert Below / Duplicate (which is how a
// duplicate Booking Code row appeared); the collapse (save) + Delete stay.
function _strip_row_buttons(frm) {
	frm.fields_dict.containers.grid.wrapper.addClass('ob-no-row-insert');
	if (!document.getElementById('ob-grid-row-style')) {
		const style = document.createElement('style');
		style.id = 'ob-grid-row-style';
		style.textContent =
			'.ob-no-row-insert .grid-insert-row,' +
			'.ob-no-row-insert .grid-insert-row-below,' +
			'.ob-no-row-insert .grid-duplicate-row,' +
			'.ob-no-row-insert .grid-append-row { display: none !important; }';
		document.head.appendChild(style);
	}
}

// Cap the grid at MAX_CONTAINERS_PER_ORDER: block the Add Row button past the cap
// (the server validate enforces the same 1..MAX as the hard guarantee).
function _enforce_max_rows(frm) {
	const grid = frm.fields_dict.containers.grid;
	grid.cannot_add_rows = (frm.doc.containers || []).length >= MAX_CONTAINERS_PER_ORDER;
	if (!grid._max_patched) {
		const orig = grid.add_new_row.bind(grid);
		grid.add_new_row = function (...args) {
			if ((frm.doc.containers || []).length >= MAX_CONTAINERS_PER_ORDER) {
				frappe.show_alert({
					message: __('Max {0} containers per voucher.', [MAX_CONTAINERS_PER_ORDER]),
					indicator: 'orange',
				});
				return;
			}
			return orig(...args);
		};
		grid._max_patched = true;
	}
}
