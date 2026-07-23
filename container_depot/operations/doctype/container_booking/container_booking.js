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
		frm.trigger('_set_grid_import_button');
		frm.trigger('_flag_open_conflicts');
		// A confirmed booking can spawn multiple bon/voucher (Order Bongkar),
		// each carrying up to 3 of its still-pending containers.
		if (!frm.is_new() && frm.doc.booking_status === 'Confirmed') {
			frm.add_custom_button(__('Generate Bon / Order'), () => open_generate_dialog(frm));
		}
		// A submitted (Confirmed) booking can be reopened for a data correction WITHOUT
		// reversing its payment — handy for a paid Cash booking that auto-confirmed.
		if (!frm.is_new() && frm.doc.docstatus === 1) {
			frm.add_custom_button(__('Revert to Draft'), () => _confirm_revert(frm));
		}
		// If the linked Sales Invoice was cancelled, the booking is stuck unbilled —
		// offer to generate a fresh draft invoice for THIS booking and re-link it
		// (no need to amend the dead invoice, which the booking wouldn't follow).
		if (
			!frm.is_new() &&
			frm.doc.docstatus === 1 &&
			frm.doc.booking_status !== 'Cancelled' &&
			frm.doc.sales_invoice
		) {
			frappe.db.get_value('Sales Invoice', frm.doc.sales_invoice, 'docstatus', (r) => {
				if (r && cint(r.docstatus) === 2) {
					frm.add_custom_button(__('Regenerate Invoice'), () => _confirm_regenerate(frm)).addClass(
						'btn-primary'
					);
				}
			});
		}
	},
	_flag_open_conflicts(frm) {
		// Draft-time heads-up in a single intro banner for the two things a draft can't
		// surface until Submit (codes / status gates only run there):
		//   1. the container is already held by another active booking, and
		//   2. its status won't pass the chosen Lift service's gate (Lift Off wants a tank
		//      NOT in the depot; Lift On wants one that is Available).
		// Both call the SAME server helpers that back the actual submit blocks, so the
		// warning can never disagree with what Submit will do. Non-blocking.
		if (frm.doc.docstatus !== 0) {
			frm.set_intro('');
			return;
		}
		const rows = (frm.doc.items || [])
			.filter((it) => it.container || it.container_no)
			.map((it) => ({ container: it.container || null, container_no: it.container_no || null }));
		if (!rows.length) {
			frm.set_intro('');
			return;
		}
		const payload = JSON.stringify(rows);
		const base = 'container_depot.operations.doctype.container_booking.container_booking';
		Promise.all([
			frappe.xcall(`${base}.open_booking_conflicts`, { booking: frm.doc.name, containers: payload }),
			// lift_item drives the direction the same way the server does, so the status
			// warning is right the instant a Lift service is picked — before the save that
			// would sync frm.doc.direction.
			frappe.xcall(`${base}.status_direction_warnings`, {
				lift_item: frm.doc.lift_item || null,
				direction: frm.doc.direction || null,
				containers: payload,
			}),
		])
			.then(([conflicts, mismatches]) => {
				const lines = [];
				(conflicts || []).forEach((c) => {
					lines.push(__('Container {0} is already on booking {1} ({2}).', [c.container_no, c.booking, c.direction || '-']));
				});
				(mismatches || []).forEach((m) => {
					if (m.direction === 'Tank In') {
						lines.push(__('Container {0} is already in the depot (status {1}) — a Tank In (Lift Off) will be refused.', [m.container_no, m.status]));
					} else {
						lines.push(__('Container {0} is not ready to leave (status {1}) — a Tank Out (Lift On) needs it Available.', [m.container_no, m.status]));
					}
				});
				if (!lines.length) {
					frm.set_intro('');
					return;
				}
				frm.set_intro(__('Heads up — these will be refused at Submit:') + '<br>' + lines.join('<br>'), 'orange');
			})
			.catch(() => {
				/* non-blocking — a failed warning must never get in the operator's way */
			});
	},
	_set_grid_import_button(frm) {
		// "Import Excel" sits in the Containers grid footer next to Add Row
		// (grid.add_custom_button dedups by label, so calling it on every refresh is
		// safe). Parses the file server-side and adds the rows client-side, so it works
		// on a brand-new, unsaved booking too. Mirrors Depot Contract's tariff import.
		const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
		if (!grid) return;
		// Editable only while the booking is an unsaved / draft record.
		if (!(frm.is_new() || frm.doc.docstatus === 0)) return;
		grid.add_custom_button(__('Import Excel'), () => {
			const d = new frappe.ui.Dialog({
				title: __('Import Containers from Excel'),
				fields: [
					{
						fieldname: 'hint',
						fieldtype: 'HTML',
						options: `<p class="text-muted small">${__(
							'Columns: Container, Condition (EMPTY CLEAN / EMPTY DIRTY / LADEN). A header row is skipped. A new Tank In container shows in the grid after Save.'
						)}</p>`,
					},
					{ fieldname: 'file', fieldtype: 'Attach', label: __('Excel File (.xlsx)'), reqd: 1 },
					{ fieldname: 'replace', fieldtype: 'Check', label: __('Replace existing rows') },
				],
				primary_action_label: __('Import'),
				primary_action(values) {
					frappe.call({
						method: 'container_depot.operations.doctype.container_booking.container_booking.parse_container_xlsx',
						args: { file_url: values.file },
						freeze: true,
						freeze_message: __('Reading file…'),
						callback(r) {
							const res = r.message || {};
							const rows = res.rows || [];
							if (values.replace) frm.clear_table('items');
							// Skip containers already on the grid (server also dedups on save).
							const existing = new Set();
							(frm.doc.items || []).forEach((it) => {
								if (it.container_no) existing.add(it.container_no.toUpperCase());
								if (it.container) existing.add(it.container);
							});
							let added = 0,
								skipped = 0;
							rows.forEach((ln) => {
								if (existing.has(ln.container_no) || (ln.container && existing.has(ln.container))) {
									skipped++;
									return;
								}
								const row = frm.add_child('items');
								row.container_no = ln.container_no;
								row.condition = ln.condition;
								if (ln.container) row.container = ln.container;
								existing.add(ln.container_no);
								added++;
							});
							frm.refresh_field('items');
							frm.trigger('_recompute_lift_amount');
							frm.trigger('_flag_open_conflicts');
							d.hide();
							let msg = __('Added {0} row(s).', [added]);
							if (skipped) msg += ' ' + __('{0} already on the grid, skipped.', [skipped]);
							const warns = res.errors || [];
							if (warns.length) {
								frappe.msgprint({
									title: __('Import finished with warnings'),
									message: msg + '<br><b>' + __('Not imported:') + '</b><br>' + warns.join('<br>'),
									indicator: 'orange',
								});
							} else {
								frappe.show_alert({ message: msg, indicator: 'green' });
							}
						},
					});
				},
			});
			// Downloads live in the dialog so the template + valid container numbers are one
			// click away. window.open (not frappe.call) because these stream a file back,
			// not JSON; the session cookie rides along so the GET is authenticated.
			const base = '/api/method/container_depot.operations.doctype.container_booking.container_booking';
			d.add_custom_action(__('Download Template'), () => {
				window.open(`${base}.download_container_template`);
			});
			d.add_custom_action(__('Download Master Container'), () => {
				const q = frm.doc.principal ? `?principal=${encodeURIComponent(frm.doc.principal)}` : '';
				window.open(`${base}.download_container_master${q}`);
			});
			d.show();
		});
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
		// Direction is derived from the Lift service, so the status warning changes with it.
		frm.trigger('_flag_open_conflicts');
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
				frm.trigger('_recompute_lift_amount');
			},
		});
	},
	// Qty = number of containers on the booking; the lift charge is billed per
	// container, so Lift Amount = Lift Rate × Qty (mirrors the Sales Invoice). Shown
	// live so the operator sees the total update as containers are added/removed.
	_recompute_lift_amount(frm) {
		const qty = (frm.doc.items || []).length;
		frm.set_value('lift_qty', qty);
		frm.set_value('lift_amount', (frm.doc.lift_rate || 0) * qty);
	},
	// Grid row add / remove events fire on the PARENT form — recompute Qty / Lift
	// Amount as container lines are added or removed.
	items_add(frm) {
		frm.trigger('_recompute_lift_amount');
	},
	items_remove(frm) {
		frm.trigger('_recompute_lift_amount');
		// A removed row may have cleared the last conflict — re-check.
		frm.trigger('_flag_open_conflicts');
	},
});

// A container line's own field change fires on the child-doctype handler.
frappe.ui.form.on('Container Booking Item', {
	container(frm, cdt, cdn) {
		_reject_duplicate_container(frm, cdt, cdn, 'container');
		frm.trigger('_recompute_lift_amount');
		frm.trigger('_flag_open_conflicts');
	},
	container_no(frm, cdt, cdn) {
		_reject_duplicate_container(frm, cdt, cdn, 'container_no');
		frm.trigger('_flag_open_conflicts');
	},
});

// Instant feedback on picking a container already on another line — the server
// re-checks this in validate(), but waiting for Save to say so is a poor trade when
// the operator is still filling the grid. Clears the offending cell so the row can
// be re-picked rather than leaving an invalid value that only fails later.
function _reject_duplicate_container(frm, cdt, cdn, fieldname) {
	const row = locals[cdt][cdn];
	const value = row[fieldname];
	if (!value) return;
	const clash = (frm.doc.items || []).find(
		(r) => r.name !== cdn && (r.container === value || r.container_no === value)
	);
	if (!clash) return;
	frappe.model.set_value(cdt, cdn, fieldname, null);
	frappe.msgprint({
		title: __('Duplicate Container'),
		message: __('Container {0} is already on row {1} — each container may appear only once.', [
			value,
			clash.idx,
		]),
		indicator: 'red',
	});
}

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

function _confirm_regenerate(frm) {
	frappe.confirm(
		__('The linked Sales Invoice was cancelled. Create a fresh draft invoice for this booking and link it?'),
		() => {
			frappe.call({
				method: 'container_depot.operations.doctype.container_booking.container_booking.regenerate_invoice',
				args: { booking: frm.doc.name },
				freeze: true,
				freeze_message: __('Generating invoice …'),
				callback(r) {
					frm.reload_doc();
					if (r.message) {
						frappe.show_alert({
							message: __('New draft invoice {0} created.', [r.message]),
							indicator: 'green',
						});
					}
				},
			});
		}
	);
}

function _confirm_revert(frm) {
	frappe.confirm(
		__('Reopen this confirmed booking as a draft to edit it? The payment (Sales Invoice + Payment Entries) and issued Booking Codes are kept — Submit again to re-confirm. Refused if a container is already in motion at the gate.'),
		() => {
			frappe.call({
				method: 'container_depot.operations.doctype.container_booking.container_booking.revert_booking_to_draft',
				args: { booking: frm.doc.name },
				freeze: true,
				freeze_message: __('Reverting to draft …'),
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
			// Key by container number — the picker shows the container no (not the
			// internal booking code); we translate back to codes on Generate.
			const by_value = {};
			pending.forEach(p => { by_value[p.container_no || p.booking_code] = p; });
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
							value: p.container_no || p.booking_code,
						})),
						onchange() {
							const picked = d.get_value('codes') || [];
							if (picked.length > MAX_CONTAINERS_PER_ORDER) {
								frappe.show_alert({
									message: __('Max {0} containers per voucher.', [MAX_CONTAINERS_PER_ORDER]),
									indicator: 'orange',
								});
							}
							// Auto-fill the voucher from the FIRST picked container's booking line.
							const first = picked[0];
							if (first && first !== last_first) {
								last_first = first;
								_fill_bongkar_detail(d, by_value[first]);
							}
						},
					},
					{ fieldtype: 'Section Break', label: __('Detail (auto-isi dari container pertama)') },
					// Required set mirrors the PWA gate's Tank In form (GateEntry.vue
					// vehicleFields): truck/driver/phone/condition identify the truck on the
					// bon, so a voucher without them is not usable at the gate. The two paths
					// generate the same document and must not disagree on what is mandatory.
					{ fieldname: 'condition', fieldtype: 'Select', label: __('Condition'), options: 'EMPTY CLEAN\nEMPTY DIRTY\nLADEN', reqd: 1 },
					{ fieldname: 'cargo', fieldtype: 'Link', label: __('Cargo'), options: 'Cargo' },
					// Estimation carried from the booking line (auto-filled, written back to the row) — hidden here.
					{ fieldname: 'tanggal_bongkar', fieldtype: 'Date', label: __('Estimation Tanggal Bongkar'), hidden: 1 },
					// Actual unload date for the bon; defaults to the estimation above.
					{ fieldname: 'tanggal_bongkar_actual', fieldtype: 'Date', label: __('Tanggal Bongkar'), default: frappe.datetime.get_today() },
					{ fieldtype: 'Column Break' },
					{ fieldname: 'truck_plate', fieldtype: 'Data', label: __('Truck Number'), reqd: 1 },
					{ fieldname: 'driver', fieldtype: 'Data', label: __('Name Driver'), reqd: 1 },
					{ fieldname: 'driver_phone', fieldtype: 'Data', label: __('No. Driver'), reqd: 1 },
					{ fieldname: 'ro', fieldtype: 'Data', label: __('R/O') },
					{ fieldtype: 'Section Break', label: __('Order') },
					{ fieldname: 'shipper', fieldtype: 'Link', label: __('Shipper'), options: 'Customer', default: frm.doc.customer },
					{ fieldname: 'ex_vessel', fieldtype: 'Data', label: __('Ex Vessel') },
					{ fieldname: 'remarks', fieldtype: 'Small Text', label: __('Remarks') },
				],
				primary_action_label: __('Generate'),
				primary_action(values) {
					const picked = values.codes || [];
					if (picked.length < 1 || picked.length > MAX_CONTAINERS_PER_ORDER) {
						frappe.msgprint(__('Pick 1 to {0} containers.', [MAX_CONTAINERS_PER_ORDER]));
						return;
					}
					// Translate the picked container numbers back to their Booking Codes.
					const codes = picked.map(v => (by_value[v] || {}).booking_code).filter(Boolean);
					const vehicle_data = {
						shipper: values.shipper,
						ex_vessel: values.ex_vessel,
						tanggal_bongkar_actual: values.tanggal_bongkar_actual,
					};
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
	// Default the actual unload date from the line's estimation Tgl. Bongkar.
	if (p.tanggal_bongkar) d.set_value('tanggal_bongkar_actual', p.tanggal_bongkar);
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
