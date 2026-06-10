// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

// Tank In / Lift Off booking. Branch scopes the depot; Customer drives the payment
// modes and resolves the active Price List server-side (its currency — USD / IDR —
// drives the Lift Rate, no exchange rate); the operator only picks the Lift Service.
// Principal (Tank Owner) scopes the container picker on each line.
frappe.ui.form.on('Container Booking', {
	onload(frm) {
		frm.trigger('_set_queries');
	},
	refresh(frm) {
		frm.trigger('_set_queries');
		frm.trigger('_lock_actions');
		// A confirmed booking can spawn multiple bon/voucher (Order Bongkar),
		// each carrying up to 3 of its still-pending containers.
		if (!frm.is_new() && frm.doc.booking_status === 'Confirmed') {
			frm.add_custom_button(__('Generate Bon / Order'), () => open_generate_dialog(frm));
		}
	},
	_lock_actions(frm) {
		// A booking is never permanently deleted or silently discarded — it is voided
		// (Cancel) so its cancelled invoice + audit trail stay. Strip both menu items
		// (server also blocks delete in on_trash).
		['Delete', 'Discard'].forEach((label) => {
			frm.page.menu.find(`a[data-label="${encodeURIComponent(__(label))}"]`).parent().remove();
		});
		// Saved draft → the only undo is Cancel = void: cancel the draft's invoice (kept
		// linked) + release reservations and mark it Cancelled. Submit (Approve) stays
		// the primary action.
		if (!frm.is_new() && frm.doc.docstatus === 0) {
			frm.add_custom_button(__('Cancel'), () => _confirm_void(frm)).addClass('btn-danger');
		}
	},
	branch(frm) {
		// Depot is scoped to the branch; drop a now-mismatched depot.
		if (frm.doc.depot) frm.set_value('depot', null);
		frm.trigger('_set_queries');
	},
	customer(frm) {
		// New customer -> reset the lift pick + rate; the active price list / currency is
		// re-resolved server-side on save. Re-derive the allowed payment modes.
		frm.set_value('lift_item', null);
		frm.set_value('lift_rate', 0);
		frm.set_value('currency', null);
		frm.trigger('_set_queries');
		frm.trigger('_apply_payment_modes');
	},
	principal(frm) {
		// Container picker filters to this owner's tanks; clear lines that no longer fit.
		(frm.doc.items || []).forEach((row) => {
			if (row.container) frappe.model.set_value(row.doctype, row.name, 'container', null);
		});
		frm.trigger('_set_queries');
	},
	lift_item(frm) {
		frm.trigger('_fetch_lift_rate');
	},
	_set_queries(frm) {
		frm.set_query('depot', () => ({ filters: { branch: frm.doc.branch || '' } }));
		frm.set_query('container', 'items', () => ({ filters: { principal: frm.doc.principal || '' } }));
		// Lift services are scoped to the customer's active price list (resolved server-side).
		frm.set_query('lift_item', () => ({
			query: 'container_depot.operations.doctype.container_booking.container_booking.lift_item_query',
			filters: { customer: frm.doc.customer },
		}));
	},
	_apply_payment_modes(frm) {
		// Payment Type is constrained to the customer's contract mode (Cash / TOP / Both).
		// No active contract -> no options; the operator must create a contract first.
		if (!frm.doc.customer) return;
		frappe.call({
			method: 'container_depot.operations.doctype.container_booking.container_booking.customer_payment_modes',
			args: { customer: frm.doc.customer },
			callback(r) {
				const modes = r.message || [];
				if (!modes.length) {
					frappe.msgprint(__('{0} has no active contract / price list. Create one for this customer first.', [frm.doc.customer]));
					frm.set_df_property('payment_type', 'options', ['']);
					frm.set_value('payment_type', null);
					return;
				}
				frm.set_df_property('payment_type', 'options', modes.join('\n'));
				if (!modes.includes(frm.doc.payment_type)) frm.set_value('payment_type', modes[0]);
				// Single mode -> lock; Both -> let the operator choose.
				frm.set_df_property('payment_type', 'read_only', modes.length === 1 ? 1 : 0);
			},
		});
	},
	_fetch_lift_rate(frm) {
		if (!frm.doc.customer || !frm.doc.lift_item) { frm.set_value('lift_rate', 0); return; }
		frappe.call({
			method: 'container_depot.operations.doctype.container_booking.container_booking.lift_rate_for',
			args: { customer: frm.doc.customer, item: frm.doc.lift_item },
			callback(r) {
				const d = r.message || {};
				// Set currency first so Lift Rate formats in the price-list currency (USD/IDR).
				if (d.currency) frm.set_value('currency', d.currency);
				frm.set_value('lift_rate', d.rate || 0);
			},
		});
	},
});

function _confirm_void(frm) {
	frappe.confirm(
		__('Cancel this booking? Its draft invoice and container reservations will be rolled back. The record is kept (not deleted).'),
		() => {
			frappe.call({
				method: 'container_depot.operations.doctype.container_booking.container_booking.void_draft',
				args: { booking: frm.doc.name },
				freeze: true,
				freeze_message: __('Cancelling …'),
				callback: () => frm.reload_doc(),
			});
		}
	);
}

const MAX_CONTAINERS_PER_ORDER = 2;

// Voucher detail (same fields as a Container Booking Item line): auto-filled from the
// first picked container's booking line, and written back onto the booking lines on
// Generate. Sent as vehicle_data to the server.
const BONGKAR_DETAIL_FIELDS = [
	'condition', 'cargo', 'truck_plate', 'driver', 'driver_phone', 'ro', 'tanggal_bongkar', 'remarks',
];

function open_generate_dialog(frm) {
	frappe.call({
		method: 'container_depot.api.get_booking_pending_containers',
		args: { booking: frm.doc.name },
		callback(r) {
			const pending = r.message || [];
			if (!pending.length) {
				frappe.msgprint(__('No pending containers left on this booking.'));
				return;
			}
			const cont_by_code = {};
			pending.forEach(p => { cont_by_code[p.booking_code] = p; });
			let last_first = null;

			const d = new frappe.ui.Dialog({
				title: __('Generate Order Bongkar'),
				size: 'large',
				fields: [
					{
						fieldname: 'codes',
						fieldtype: 'MultiSelectPills',
						label: __('Containers (max {0})', [MAX_CONTAINERS_PER_ORDER]),
						reqd: 1,
						get_data: () => pending.map(p => ({
							value: p.booking_code,
							description: `${p.container_no || p.booking_code} · ${p.status_tag || ''}`,
						})),
						onchange() {
							const codes = d.get_value('codes') || [];
							if (codes.length > MAX_CONTAINERS_PER_ORDER) {
								frappe.show_alert({
									message: __('Max {0} containers per voucher.', [MAX_CONTAINERS_PER_ORDER]),
									indicator: 'orange',
								});
							}
							// Auto-fill the voucher from the FIRST picked container's booking line.
							const first = codes[0];
							if (first && first !== last_first) {
								last_first = first;
								_fill_bongkar_detail(d, cont_by_code[first]);
							}
						},
					},
					{ fieldtype: 'Section Break', label: __('Detail (auto-isi dari container pertama)') },
					{ fieldname: 'condition', fieldtype: 'Select', label: __('Condition'), options: 'EMPTY CLEAN\nEMPTY DIRTY\nLADEN' },
					{ fieldname: 'cargo', fieldtype: 'Link', label: __('Cargo'), options: 'Cargo' },
					{ fieldname: 'tanggal_bongkar', fieldtype: 'Date', label: __('Estimation Tanggal Bongkar'), default: frappe.datetime.get_today() },
					{ fieldtype: 'Column Break' },
					{ fieldname: 'truck_plate', fieldtype: 'Data', label: __('Truck Number') },
					{ fieldname: 'driver', fieldtype: 'Data', label: __('Name Driver') },
					{ fieldname: 'driver_phone', fieldtype: 'Data', label: __('No. Driver') },
					{ fieldname: 'ro', fieldtype: 'Data', label: __('R/O') },
					{ fieldtype: 'Section Break', label: __('Order') },
					{ fieldname: 'shipper', fieldtype: 'Link', label: __('Shipper'), options: 'Customer', default: frm.doc.customer },
					{ fieldname: 'ex_vessel', fieldtype: 'Data', label: __('Ex Vessel') },
					{ fieldname: 'remarks', fieldtype: 'Small Text', label: __('Remarks') },
				],
				primary_action_label: __('Generate'),
				primary_action(values) {
					const codes = values.codes || [];
					if (codes.length < 1 || codes.length > MAX_CONTAINERS_PER_ORDER) {
						frappe.msgprint(__('Pick 1 to {0} containers.', [MAX_CONTAINERS_PER_ORDER]));
						return;
					}
					const vehicle_data = { shipper: values.shipper, ex_vessel: values.ex_vessel };
					BONGKAR_DETAIL_FIELDS.forEach((f) => { vehicle_data[f] = values[f]; });
					submit_generation(frm, d, codes, vehicle_data);
				},
			});
			d.show();
		},
	});
}

function _fill_bongkar_detail(d, p) {
	// Copy the booking line's detail into the voucher's shared fields.
	if (!p) return;
	BONGKAR_DETAIL_FIELDS.forEach((f) => {
		if (p[f] != null && p[f] !== '') d.set_value(f, p[f]);
	});
}

function submit_generation(frm, dialog, codes, vehicle_data) {
	frappe.call({
		method: 'container_depot.api.generate_order_from_booking',
		args: {
			booking: frm.doc.name,
			selected_codes: JSON.stringify(codes),
			vehicle_data: JSON.stringify(vehicle_data)
		},
		freeze: true,
		freeze_message: __('Generating bon …'),
		callback(r) {
			if (r.message && r.message.success) {
				dialog.hide();
				frappe.show_alert({
					message: __('Created {0} {1}', [r.message.order_doctype, r.message.order_name]),
					indicator: 'green'
				});
				frappe.set_route('Form', r.message.order_doctype, r.message.order_name);
			}
		}
	});
}
