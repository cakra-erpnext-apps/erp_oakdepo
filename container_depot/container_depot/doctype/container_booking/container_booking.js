// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

// Container booking. Direction is the operator's pick — Tank In = Lift Off (tank dropped
// at the depot), Tank Out = Lift On (tank taken from it) — and drives the gates, the bon
// type and the BKG-IN/BKG-OUT number. Branch scopes the depot; Customer drives the payment
// modes and resolves the active Price List server-side (its currency — USD / IDR — formats
// every charge, no exchange rate). Charges are a free table: any number of services from
// the "Booking" Depot Service Menu, or none at all. Principal (Tank Owner) scopes the
// container picker on each line.
// Whether this site raises invoices at all (Depot Finance Settings, published at boot).
// With finance off the depot runs operationally — charges are still priced and stored, but
// nothing is billed — so the billing buttons are hidden rather than left to fail server-side.
function _finance_on() {
	return frappe.boot.depot_finance_enabled !== 0;
}

frappe.ui.form.on('Container Booking', {
	onload(frm) {
		frm.trigger('_set_queries');
	},
	refresh(frm) {
		frm.trigger('_set_queries');
		frm.trigger('_lock_actions');
		frm.trigger('_set_grid_import_button');
		frm.trigger('_mark_new_containers');
		frm.trigger('_flag_open_conflicts');
		frm.trigger('_apply_billing_lock');
		frm.trigger('_render_work_per_container');
		// Draft -> Pending Payment. Nothing is generated until this is pressed, so the
		// operator can get the booking right before it reaches the Cashier's queue.
		// Each button below mirrors the permission its endpoint enforces, so nobody is
		// offered an action that will bounce. `write` for the invoice actions
		// (has_permission(..., "write") in container_booking.py), `cancel` for the revert
		// (doc.check_permission("cancel")), and create-on-the-order for Generate Bon.
		const may_write = frappe.perm.has_perm(frm.doctype, 0, 'write');
		if (
			!frm.is_new() &&
			may_write &&
			_finance_on() &&
			frm.doc.docstatus === 0 &&
			frm.doc.booking_status === 'Draft' &&
			frm.doc.charges_total > 0 &&
			frm.doc.payment_type === 'Cash'
		) {
			frm.add_custom_button(__('Generate Invoice'), () => _confirm_generate_invoice(frm)).addClass(
				'btn-primary'
			);
		}
		// Pending Payment -> Draft. The way back while nothing has settled: voids the draft
		// invoice and reopens the charges. Refused server-side once the invoice is submitted.
		if (
			!frm.is_new() &&
			may_write &&
			frm.doc.docstatus === 0 &&
			['Pending Payment', 'Pending Confirmation'].includes(frm.doc.booking_status)
		) {
			frm.add_custom_button(__('Rollback ke Draft'), () => _confirm_rollback(frm));
		}
		// A confirmed booking can spawn multiple bon/voucher (Order Bongkar),
		// each carrying up to 3 of its still-pending containers.
		//
		// `frappe.model.can_create`, NOT `frappe.perm.has_perm`: the latter reads the
		// permissions off `frappe.get_meta(doctype)`, and when that meta is not loaded
		// client-side it falls back to `{read: …}` with every other right at 0 — so the
		// answer is a silent `false`, not an error. Nothing on this form links to the bon
		// doctypes (they reach it through the Connections tab, which loads later and
		// asynchronously), so the meta is reliably absent at refresh() time and the button
		// never rendered for anyone but Administrator, who short-circuits to all rights.
		// `can_create` reads `frappe.boot.user.can_create`, which is computed server-side
		// from the real permissions and is always present. Same reasoning wherever we ask
		// about a doctype other than `frm.doctype` — see container.js / survey_order.js.
		const order_dt = frm.doc.direction === 'Tank In' ? 'Order Bongkar' : 'Order Muat';
		if (
			!frm.is_new() &&
			frm.doc.booking_status === 'Confirmed' &&
			frappe.model.can_create(order_dt)
		) {
			frm.add_custom_button(__('Generate Bon / Order'), () => open_generate_dialog(frm));
		}
		// A submitted (Confirmed) booking can be reopened for a data correction WITHOUT
		// reversing its payment — handy for a paid Cash booking that auto-confirmed. Both
		// undos die the moment a bon exists; that decision needs a round trip, so it lives
		// in its own trigger.
		frm.trigger('_gate_undo_actions');
		// A confirmed CASH booking that bills something but has no live invoice is stuck
		// unbilled — its invoice was cancelled (which unlinks it, see
		// resync_booking_on_invoice_cancel). Offer a fresh draft invoice rather than
		// amending the dead one, which the booking would not follow.
		//
		// TOP is excluded, and the exclusion is load-bearing: "submitted, charges > 0, no
		// sales_invoice" is the NORMAL resting state of a postpaid booking waiting for the
		// monthly run, not a broken one — _auto_invoice skips TOP on purpose. Without this
		// check the button showed on every unbilled TOP booking, and pressing it wrote a
		// standalone invoice into `sales_invoice`, which is exactly the field
		// consolidated_billing.bill_customer requires to be EMPTY. The charge would drop
		// out of the customer's monthly statement silently. A TOP booking never needs this
		// button: _unmark_billed already clears the link when a consolidated invoice is
		// cancelled, and the next bill_customer picks the booking back up on its own.
		if (
			!frm.is_new() &&
			may_write &&
			_finance_on() &&
			frm.doc.docstatus === 1 &&
			frm.doc.booking_status !== 'Cancelled' &&
			frm.doc.payment_type !== 'TOP' &&
			!frm.doc.sales_invoice &&
			frm.doc.charges_total > 0
		) {
			frm.add_custom_button(__('Regenerate Invoice'), () => _confirm_regenerate(frm)).addClass(
				'btn-primary'
			);
		}
	},
	// A bon is the point of no return. Once one has been raised from this booking the two
	// undos are gone — no Revert to Draft, no Cancel — because the bon is paper a driver
	// was handed at the gate and it names this booking. Reopening the booking for edits, or
	// voiding it, leaves that paper pointing at a record that no longer says what it said.
	// Enforced server-side (`_block_if_bon_raised`, reached from `before_cancel`,
	// `revert_booking_to_draft` and `void_draft`); this only keeps the screen honest.
	//
	// Asynchronous, and it has to be: nothing on this form links to a bon — they are
	// reachable only through the Connections tab — so there is no way to answer "has one
	// been raised?" without asking the server. The buttons are therefore ADDED in the
	// callback rather than added-then-removed, which would flicker.
	_gate_undo_actions(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 1) return;
		const may_cancel = frappe.perm.has_perm(frm.doctype, 0, 'cancel');
		frappe.call({
			method: 'container_depot.container_depot.doctype.container_booking.container_booking.revision_state',
			args: { booking: frm.doc.name },
			callback(r) {
				const state = r.message || {};
				const bons = state.bons || [];
				const locked = state.locked_containers || [];
				if (!bons.length) {
					if (may_cancel) {
						frm.add_custom_button(__('Revert to Draft'), () => _confirm_revert(frm));
					}
				} else if (may_cancel) {
					// Frappe's own Cancel lives in the Menu, so it is stripped the same way
					// _lock_actions strips Delete / Discard.
					frm.page.menu
						.find(`a[data-label="${encodeURIComponent(__('Cancel'))}"]`)
						.parent()
						.remove();
				}
				if (bons.length) {
					frm.dashboard.add_comment(
						__('Bon sudah terbit ({0}) — booking ini tidak bisa dikembalikan ke draft atau dibatalkan. Data lain masih bisa direvisi langsung di sini, tanpa mengubah status.', [
							bons.join(', '),
						]),
						'orange',
						true
					);
				}
				// Name the frozen tanks up front. The server refuses the save with the
				// container and the field it refused, but by then the operator has already
				// typed — and on a booking with several containers it is not obvious which
				// rows the bon took.
				if (locked.length) {
					frm.dashboard.add_comment(
						__('Container yang sudah masuk bon tidak bisa diubah atau dihapus: {0}. Baris lain bebas direvisi.', [
							locked.join(', '),
						]),
						'blue',
						true
					);
				}
			},
		});
	},
	// Mirror the server lock in the UI: outside Draft the billing facts are frozen, so
	// showing them as editable would only let the operator type into a field whose save
	// is about to be refused. Everything else on the booking stays editable.
	_apply_billing_lock(frm) {
		const locked = frm.doc.docstatus === 0 && !['Draft', 'Cancelled'].includes(frm.doc.booking_status);
		frm.set_df_property('charges', 'read_only', locked ? 1 : 0);
		frm.set_df_property('customer', 'read_only', locked ? 1 : 0);
		if (locked) {
			frm.dashboard.add_comment(
				__('Charges terkunci karena invoice sudah dibuat. Tekan Rollback ke Draft untuk mengubahnya.'),
				'blue',
				true
			);
		}
	},
	_render_work_per_container(frm) {
		// "What happened to these tanks?" — the question a booking is opened to answer once
		// the tanks are in the yard. The Connections tab has the same records but as four
		// flat lists, which stops being readable the moment a booking carries more than one
		// container: you cannot tell which EIR belongs to which tank without opening it.
		const wrapper = frm.get_field('orders_by_container_html')?.$wrapper;
		if (!wrapper) return;
		if (frm.is_new()) {
			wrapper.empty();
			return;
		}
		frappe.call({
			method: 'container_depot.container_depot.doctype.container_booking.container_booking.orders_by_container',
			args: { booking: frm.doc.name },
			callback(r) {
				wrapper.html(_work_html(r.message || []));
			}
		});
	},
	_flag_open_conflicts(frm) {
		// Draft-time heads-up in a single intro banner for the two things a draft can't
		// surface until Submit (codes / status gates only run there):
		//   1. the container is already held by another active booking, and
		//   2. its status won't pass the chosen Direction's gate (Tank In / Lift Off wants a
		//      tank NOT in the depot; Tank Out / Lift On wants one that is Available).
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
		const base = 'container_depot.container_depot.doctype.container_booking.container_booking';
		Promise.all([
			frappe.xcall(`${base}.open_booking_conflicts`, { booking: frm.doc.name, containers: payload }),
			frappe.xcall(`${base}.status_direction_warnings`, {
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
					} else if ((m.open_orders || []).length) {
						// Name the work holding the tank. "Not ready" alone sends the operator
						// hunting; the order number is what they can actually go and finish.
						const orders = m.open_orders
							.map((o) => `${o.label} <b>${frappe.utils.escape_html(o.name)}</b> (${frappe.utils.escape_html(o.status || '-')})`)
							.join(', ');
						lines.push(
							__('Container {0} masih punya order belum selesai: {1}', [m.container_no, orders])
						);
					} else {
						lines.push(
							__('Container {0} tidak ada di depo (status {1}) — booking keluar akan ditolak.', [m.container_no, m.status])
						);
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
	_mark_new_containers(frm) {
		// Tell apart, at a glance, the rows whose Container master this import registered
		// from the ones that picked an existing tank. A badge appended to the Container No
		// column rather than a column of its own: the grid's ten column-widths are already
		// spoken for, and the badge belongs next to the number it qualifies anyway.
		const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
		const df = grid && grid.get_docfield('container_no');
		if (!df || df.formatter) return;
		// Append to what the stock formatter returns rather than replacing it. `value`
		// arrives already HTML-escaped — the grid pre-escapes plain-text fieldtypes before
		// formatting (grid_row.js `_escape_for_format`) — so don't escape it twice.
		const base = frappe.form.get_formatter(df.fieldtype);
		df.formatter = (value, _df, _options, row) => {
			const cell = base(value, _df, _options, row);
			if (!row || !row.is_new_container) return cell;
			return `${cell} <span class="indicator-pill green" title="${__(
				'Master Container dibuat oleh booking ini'
			)}">${__('Baru')}</span>`;
		};
		// The grid's columns were already painted by the time a refresh script runs
		// (frm.refresh_fields precedes it), so the freshly attached formatter needs one
		// repaint to show. Guarded above, this happens once per form load.
		grid.refresh();
	},
	_set_grid_import_button(frm) {
		// "Import Excel" sits in the Containers grid footer next to Add Row
		// (grid.add_custom_button dedups by label, so calling it on every refresh is
		// safe). Parses the file server-side and adds the rows client-side, so it works
		// on a brand-new, unsaved booking too. Mirrors Depot Contract's tariff import.
		const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
		if (!grid) return;
		// Editable only while the booking is an unsaved / draft record, and only for
		// someone who could save the rows it adds.
		if (!(frm.is_new() || frm.doc.docstatus === 0)) return;
		if (!frappe.perm.has_perm(frm.doctype, 0, 'write')) return;
		grid.add_custom_button(__('Import Excel'), () => {
			const d = new frappe.ui.Dialog({
				title: __('Import Containers from Excel'),
				fields: [
					{
						fieldname: 'hint',
						fieldtype: 'HTML',
						options: `<p class="text-muted small">${__(
							'Columns: Container, Condition (EMPTY CLEAN / EMPTY DIRTY / LADEN), Last Cargo (optional — must match the Cargo master; the downloads carry the list). A header row is skipped. On a Tank In, a number the Container master does not know is registered on the spot (owned by this booking\'s Principal, badged <b>Baru</b> in the grid); on a Tank Out it is skipped and reported.'
						)}</p>`,
					},
					{ fieldname: 'file', fieldtype: 'Attach', label: __('Excel File (.xlsx)'), reqd: 1 },
					{ fieldname: 'replace', fieldtype: 'Check', label: __('Replace existing rows') },
				],
				primary_action_label: __('Import'),
				primary_action(values) {
					frappe.call({
						method: 'container_depot.container_depot.doctype.container_booking.container_booking.parse_container_xlsx',
						args: {
							file_url: values.file,
							direction: frm.doc.direction || null,
							// A Container cannot be created without an owner; the header carries it.
							principal: frm.doc.principal || frm.doc.customer || null,
						},
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
							// Numbers this import registered a Container master for — collected
							// from the rows actually added, not from the file, so a duplicate
							// that never reached the grid is not announced as new.
							const fresh = [];
							rows.forEach((ln) => {
								if (existing.has(ln.container_no) || (ln.container && existing.has(ln.container))) {
									skipped++;
									return;
								}
								const row = frm.add_child('items');
								row.container_no = ln.container_no;
								row.condition = ln.condition;
								// add_child doesn't fire items_add — default the EMKL here too.
								row.shipper = frm.doc.customer;
								if (ln.container) row.container = ln.container;
								if (ln.cargo) row.cargo = ln.cargo;
								// Set here, re-derived from the Container's own created_by_booking
								// on save — so an operator who repoints the row at an existing
								// tank does not keep a stale badge.
								row.is_new_container = ln.is_new ? 1 : 0;
								if (ln.is_new) fresh.push(ln.container_no);
								existing.add(ln.container_no);
								added++;
							});
							frm.refresh_field('items');
							frm.trigger('_sync_charge_qty');
							frm.trigger('_flag_open_conflicts');
							d.hide();
							let msg = __('Added {0} row(s).', [added]);
							if (skipped) msg += ' ' + __('{0} already on the grid, skipped.', [skipped]);
							// Three outcomes worth naming separately: numbers that will become new
							// Container masters, numbers the master does not know and will not get
							// (Tank Out — skipped outright), and rows dropped for a bad value.
							const notes = [];
							// Registering a Container master is the one thing an import does outside
							// this booking, so the numbers it created are named first and by name —
							// a typo caught here costs nothing, one found later is a phantom tank.
							if (fresh.length) {
								notes.push(
									'<b>' +
										__('Registered in the Container master ({0}):', [fresh.length]) +
										'</b><br>' +
										fresh.join(', ') +
										'<br><span class="text-muted">' +
										__(
											'Badged <b>Baru</b> in the grid. Registered outside the depot (Gate_Out) like any new master — saving this booking reserves them (Booked). Drop the row and delete the container if the number is a typo.'
										) +
										'</span>'
								);
							}
							const unknown = res.unknown || [];
							if (unknown.length) {
								notes.push(
									'<b>' +
										__('Not in Container master — skipped ({0}):', [unknown.length]) +
										'</b><br>' +
										unknown.join(', ') +
										'<br><span class="text-muted">' +
										__('Register these in the Container master first, then import again.') +
										'</span>'
								);
							}
							const warns = res.errors || [];
							if (warns.length) {
								notes.push('<b>' + __('Not imported:') + '</b><br>' + warns.join('<br>'));
							}
							if (notes.length) {
								frappe.msgprint({
									title: __('Import finished with notes'),
									message: msg + '<br><br>' + notes.join('<br><br>'),
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
			const base = '/api/method/container_depot.container_depot.doctype.container_booking.container_booking';
			d.add_custom_action(__('Download Template'), () => {
				window.open(`${base}.download_container_template`);
			});
			// Master Container carries the Cargo master on its second sheet, so the label
			// says so — the cargo names are what the Last Cargo column must be spelled from.
			d.add_custom_action(__('Download Master Container + Cargo'), () => {
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
		//
		// Gated on the CANCEL permission, not on read: Frappe hides its own Cancel that way
		// and a custom button that replaces it has to follow, or a read-only role (Finance,
		// Management) is shown a destructive action it has no right to. The server enforces
		// the same check in void_draft — this only keeps the screen honest.
		if (!frm.is_new() && frm.doc.docstatus === 0 && frappe.perm.has_perm(frm.doctype, 0, 'cancel')) {
			frm.add_custom_button(__('Cancel'), () => _confirm_void(frm)).addClass('btn-danger');
		}
	},
	branch(frm) {
		// Depot is scoped to the branch; drop a now-mismatched depot.
		if (frm.doc.depot) frm.set_value('depot', null);
		frm.trigger('_set_queries');
	},
	customer(frm) {
		// A new customer means a different rate card. Charges are cleared rather than
		// re-priced so one booking can never end up mixing two price lists — the operator
		// picks the services again from the new customer's list.
		const had = (frm.doc.charges || []).length;
		if (had) {
			frm.clear_table('charges');
			frm.refresh_field('charges');
			frappe.show_alert({
				message: __('Charges direset karena Customer diganti — pilih ulang service-nya.'),
				indicator: 'orange',
			});
		}
		frm.set_value('charges_total', 0);
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
	direction(frm) {
		// Direction decides which status gate the containers face, so the draft warning
		// changes with it.
		frm.trigger('_flag_open_conflicts');
	},
	_set_queries(frm) {
		frm.set_query('depot', () => ({ filters: { branch: frm.doc.branch || '' } }));
		// Retired tanks (Active off) are out of the fleet and never offered.
		frm.set_query('container', 'items', () => ({
			filters: { principal: frm.doc.principal || '', is_active: 1 },
		}));
		// Charge services: the "Booking" Depot Service Menu ∩ the customer's active price
		// list (both resolved server-side).
		frm.set_query('item', 'charges', () => ({
			query: 'container_depot.container_depot.doctype.container_booking.container_booking.charge_item_query',
			filters: { customer: frm.doc.customer },
		}));
	},
	_apply_payment_modes(frm) {
		// Payment Type is constrained to the customer's contract mode (Cash / TOP / Both).
		// No active contract -> no options; the operator must create a contract first.
		if (!frm.doc.customer) return;
		frappe.call({
			method: 'container_depot.container_depot.doctype.container_booking.container_booking.customer_payment_modes',
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
	// Charges total = Σ amount. Shown live so the operator sees it move as rows and
	// containers change, without waiting for a save.
	_recompute_charges(frm) {
		let total = 0;
		(frm.doc.charges || []).forEach((row) => {
			const amount = (row.qty || 0) * (row.rate || 0);
			if (amount !== row.amount) frappe.model.set_value(row.doctype, row.name, 'amount', amount);
			total += amount;
		});
		frm.set_value('charges_total', total);
	},
	// A charge line's qty defaults to the container count (the lift is billed per
	// container), so adding/removing containers keeps untouched rows in step. A row whose
	// qty the operator already set to something else is left alone.
	_sync_charge_qty(frm) {
		const count = (frm.doc.items || []).length;
		if (!count) return;
		(frm.doc.charges || []).forEach((row) => {
			if (!row._qty_touched) frappe.model.set_value(row.doctype, row.name, 'qty', count);
		});
	},
	// Grid row add / remove events fire on the PARENT form.
	items_add(frm, cdt, cdn) {
		// EMKL / Shipper defaults to the booking's Customer so the common case (one
		// transporter for the whole booking) costs no typing; the operator overrides the
		// row when a booking is split across several EMKL. Any row left blank is filled
		// server-side on save (see _default_row_shipper).
		if (frm.doc.customer) frappe.model.set_value(cdt, cdn, 'shipper', frm.doc.customer);
		frm.trigger('_sync_charge_qty');
	},
	items_remove(frm) {
		frm.trigger('_sync_charge_qty');
		// A removed row may have cleared the last conflict — re-check.
		frm.trigger('_flag_open_conflicts');
	},
	charges_add(frm, cdt, cdn) {
		// The picker is scoped to the customer's price list, so a charge without a customer
		// has nothing to choose from — say so instead of leaving an empty dropdown.
		if (!frm.doc.customer) {
			frappe.show_alert({
				message: __('Pilih Customer dulu — service difilter ke price list customer.'),
				indicator: 'orange',
			});
		}
		// New charge line starts at the container count — the dominant case is a per-container
		// lift charge. Overwrite it by hand for a one-off fee.
		const count = (frm.doc.items || []).length;
		if (count) frappe.model.set_value(cdt, cdn, 'qty', count);
	},
	charges_remove(frm) {
		frm.trigger('_recompute_charges');
	},
});

// Live pricing for a charge line: the rate seeds from the customer's active price list
// the moment a Service is picked, so the operator sees the money before saving. Seeded
// once — an edited rate is never re-applied (same rule the server enforces).
function _fetch_charge_rate(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!frm.doc.customer || !row.item) return;
	frappe.call({
		method: 'container_depot.container_depot.doctype.container_booking.container_booking.charge_pricing',
		args: { customer: frm.doc.customer, item: row.item },
		callback(r) {
			const d = r.message || {};
			// Currency first so the rate formats in the price-list currency (USD / IDR).
			if (d.currency) {
				frm.set_value('currency', d.currency);
				frappe.model.set_value(cdt, cdn, 'currency', d.currency);
			}
			frappe.model.set_value(cdt, cdn, 'item_name', d.item_name || row.item);
			frappe.model.set_value(cdt, cdn, 'rate', d.rate || 0);
		},
	});
}

frappe.ui.form.on('Container Booking Charge', {
	item(frm, cdt, cdn) {
		// A different service means a different price — pull the new one in rather than
		// keep the old, which would silently bill the previous service's rate. Whatever
		// lands here is editable afterwards, 0 included.
		_fetch_charge_rate(frm, cdt, cdn);
	},
	qty(frm, cdt, cdn) {
		// Mark the row as hand-set so adding containers stops overwriting its qty.
		locals[cdt][cdn]._qty_touched = true;
		frm.trigger('_recompute_charges');
	},
	rate(frm) {
		frm.trigger('_recompute_charges');
	},
});

// A container line's own field change fires on the child-doctype handler.
frappe.ui.form.on('Container Booking Item', {
	container(frm, cdt, cdn) {
		_reject_duplicate_container(frm, cdt, cdn, 'container');
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
				method: 'container_depot.container_depot.doctype.container_booking.container_booking.void_draft',
				args: { booking: frm.doc.name },
				freeze: true,
				freeze_message: __('Cancelling …'),
				callback: () => frm.reload_doc(),
			});
		}
	);
}

function _confirm_generate_invoice(frm) {
	frappe.confirm(
		__(
			'Buat Sales Invoice untuk booking ini sebesar {0}?<br><br>Setelah ini charges dan customer terkunci — gunakan Rollback ke Draft kalau masih perlu diubah.',
			[format_currency(frm.doc.charges_total, frm.doc.currency)]
		),
		() => {
			frappe.call({
				method: 'container_depot.container_depot.doctype.container_booking.container_booking.generate_invoice',
				args: { booking: frm.doc.name },
				freeze: true,
				freeze_message: __('Membuat invoice …'),
				callback(r) {
					frm.reload_doc();
					if (r.message) {
						frappe.show_alert({
							message: __('Draft invoice {0} dibuat.', [r.message.sales_invoice]),
							indicator: 'green',
						});
					}
				},
			});
		}
	);
}

function _confirm_rollback(frm) {
	frappe.confirm(
		__(
			'Kembalikan booking ini ke Draft? Sales Invoice draft-nya akan dibatalkan dan charges bisa diedit lagi.'
		),
		() => {
			frappe.call({
				method: 'container_depot.container_depot.doctype.container_booking.container_booking.rollback_to_draft',
				args: { booking: frm.doc.name },
				freeze: true,
				freeze_message: __('Mengembalikan ke Draft …'),
				callback() {
					frm.reload_doc();
					frappe.show_alert({ message: __('Booking kembali ke Draft.'), indicator: 'orange' });
				},
			});
		}
	);
}

function _confirm_regenerate(frm) {
	frappe.confirm(
		__('The linked Sales Invoice was cancelled. Create a fresh draft invoice for this booking and link it?'),
		() => {
			frappe.call({
				method: 'container_depot.container_depot.doctype.container_booking.container_booking.regenerate_invoice',
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
		__('Reopen this confirmed booking as a draft to edit it? The payment (Sales Invoice + Payment Entries) and issued Booking Codes are kept — Submit again to re-confirm. Refused once a bon has been raised from this booking.'),
		() => {
			frappe.call({
				method: 'container_depot.container_depot.doctype.container_booking.container_booking.revert_booking_to_draft',
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
// A Tank Out voucher inherits only the vehicle trio + R/O from the line. Condition, cargo
// and Tgl. Bongkar describe what was DROPPED OFF — they say nothing about a pick-up.
const MUAT_DETAIL_FIELDS = ['truck_plate', 'driver', 'driver_phone', 'ro', 'remarks'];

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

			// The server picks the bon type from the Booking Code's direction (Tank In →
			// Order Bongkar, Tank Out → Order Muat). This dialog used to ask Tank In's
			// questions either way: it announced "Order Bongkar" on an outbound booking and
			// sent drop-off keys (ex_vessel / tanggal_bongkar / `driver`), so the Order Muat
			// it produced came out with no angkutan, no destination, no Tgl. Muat and — since
			// Muat reads `driver_name` — no driver either. Each direction now asks for what
			// its own bon actually carries.
			const out = frm.doc.direction === 'Tank Out';
			const detail_fields = out ? MUAT_DETAIL_FIELDS : BONGKAR_DETAIL_FIELDS;

			const d = new frappe.ui.Dialog({
				title: out ? __('Generate Order Muat') : __('Generate Order Bongkar'),
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
								_fill_line_detail(d, by_value[first], detail_fields, out);
							}
						},
					},
					{ fieldtype: 'Section Break', label: __('Detail (auto-isi dari container pertama)') },
					// Required set mirrors the PWA gate form (GateEntry.vue vehicleFields):
					// truck/driver/phone identify the truck on the bon, so a voucher without
					// them is not usable at the gate. The two paths generate the same document
					// and must not disagree on what is mandatory.
					...(out
						? [
							{ fieldname: 'destination', fieldtype: 'Data', label: __('Destination') },
							{ fieldname: 'tanggal_muat', fieldtype: 'Date', label: __('Tgl. Muat'), default: frappe.datetime.get_today() },
						]
						: [
							{ fieldname: 'condition', fieldtype: 'Select', label: __('Condition'), options: 'EMPTY CLEAN\nEMPTY DIRTY\nLADEN', reqd: 1 },
							{ fieldname: 'cargo', fieldtype: 'Link', label: __('Cargo'), options: 'Cargo' },
							// Estimation carried from the booking line (auto-filled, written back to the row) — hidden here.
							{ fieldname: 'tanggal_bongkar', fieldtype: 'Date', label: __('Estimation Tanggal Bongkar'), hidden: 1 },
							// Actual unload date for the bon; defaults to the estimation above.
							{ fieldname: 'tanggal_bongkar_actual', fieldtype: 'Date', label: __('Tanggal Bongkar'), default: frappe.datetime.get_today() },
						]),
					{ fieldtype: 'Column Break' },
					{ fieldname: 'truck_plate', fieldtype: 'Data', label: __('Truck Number'), reqd: 1 },
					{ fieldname: 'driver', fieldtype: 'Data', label: __('Driver'), reqd: 1 },
					{ fieldname: 'driver_phone', fieldtype: 'Data', label: __('No. HP Driver'), reqd: 1 },
					{ fieldname: 'ro', fieldtype: 'Data', label: __('RO') },
					{ fieldtype: 'Section Break', label: __('Order') },
					// One party under three names — the hauler. Tank Out used to ask for it twice
					// (a free-text "Angkutan" beside this link), so the same company could land
					// in two places with nothing tying them together.
					{ fieldname: 'shipper', fieldtype: 'Link', label: __('Shipper / Angkutan / EMKL'), options: 'Customer', default: frm.doc.customer },
					...(out ? [] : [{ fieldname: 'ex_vessel', fieldtype: 'Data', label: __('Ex Vessel') }]),
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
					let vehicle_data;
					if (out) {
						vehicle_data = {
							shipper: values.shipper,
							destination: values.destination,
							tanggal_muat: values.tanggal_muat,
							truck_plate: values.truck_plate,
							// Order Muat's field is driver_name; the dialog asks it as `driver`
							// so the booking line's own `driver` can auto-fill it.
							driver_name: values.driver,
							driver_phone: values.driver_phone,
							ro: values.ro,
							// Muat stores a remark PER container row, keyed by booking code.
							remarks: values.remarks
								? Object.fromEntries(codes.map((c) => [c, values.remarks]))
								: null,
						};
					} else {
						vehicle_data = {
							shipper: values.shipper,
							ex_vessel: values.ex_vessel,
							tanggal_bongkar_actual: values.tanggal_bongkar_actual,
						};
						BONGKAR_DETAIL_FIELDS.forEach((f) => { vehicle_data[f] = values[f]; });
					}
					submit_generation(frm, d, codes, vehicle_data);
				},
			});
			d.show();
		},
	});
}

function _fill_line_detail(d, p, fields, out) {
	// Copy the booking line's detail into the voucher's shared fields.
	if (!p) return;
	fields.forEach((f) => {
		if (p[f] != null && p[f] !== '') d.set_value(f, p[f]);
	});
	// Tank In only: default the actual unload date from the line's estimation Tgl. Bongkar.
	// A pick-up has no such estimate on the line — Tgl. Muat defaults to today instead.
	if (!out && p.tanggal_bongkar) d.set_value('tanggal_bongkar_actual', p.tanggal_bongkar);
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

// --- Work per container ----------------------------------------------------
// Colour follows meaning, not doctype: a finished job is green wherever it came from, an
// open one amber, a dead one grey. The four work doctypes each spell "done" differently,
// so map the words rather than asking every caller to remember which is which.
const _WORK_DONE = ['Completed', 'Submitted', 'Approved', 'Passed', 'Closed'];
const _WORK_DEAD = ['Cancelled', 'Rejected', 'Void'];

function _work_indicator(status) {
	if (_WORK_DEAD.includes(status)) return 'gray';
	if (_WORK_DONE.includes(status)) return 'green';
	return 'orange';
}

function _work_html(groups) {
	if (!groups.length) {
		return `<div class="text-muted">${__('Booking ini belum punya baris container.')}</div>`;
	}
	return groups.map(_work_group_html).join('');
}

function _work_group_html(g) {
	const esc = frappe.utils.escape_html;
	const title = g.container
		? frappe.utils.get_form_link('Container', g.container, true, esc(g.container_no))
		: `${esc(g.container_no)} <span class="text-muted">${__('(belum ada master)')}</span>`;

	let body;
	if (g.orders.length) {
		body = `<div class="mt-2">${g.orders.map(_work_row_html).join('')}</div>`;
	} else {
		// Say nothing-happened out loud. A silently empty block reads as a broken panel.
		body = `<div class="text-muted mt-2">${__('Belum ada pekerjaan yang tercatat di booking ini.')}</div>`;
	}

	// Orders on this tank that belong to no booking at all. Counted, never listed as if
	// they were this booking's: attributing them is a human decision (booking_link.py),
	// and folding them in would be exactly the guess the design refuses to make.
	let hint = '';
	if (g.unlinked) {
		hint = `<div class="text-muted small mt-1">
			${__('{0} order lain pada tank ini belum ter-link ke booking mana pun.', [g.unlinked])}
		</div>`;
	}

	return `<div class="mb-4">
		<div><b>${title}</b></div>
		${body}
		${hint}
	</div>`;
}

function _work_row_html(o) {
	const esc = frappe.utils.escape_html;
	const link = frappe.utils.get_form_link(o.doctype, o.name, true, esc(o.name));
	const when = o.date ? frappe.datetime.str_to_user(o.date) : '';
	return `<div class="d-flex align-items-center" style="gap: .5rem; padding: 2px 0;">
		<span class="indicator-pill ${_work_indicator(o.status)}">${esc(o.status || '—')}</span>
		<span style="min-width: 9rem;">${link}</span>
		<span class="text-muted">${esc(__(o.label || o.doctype))}</span>
		<span class="text-muted small ml-auto">${esc(when)}</span>
	</div>`;
}
