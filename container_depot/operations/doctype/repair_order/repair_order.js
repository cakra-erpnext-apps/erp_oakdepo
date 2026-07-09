// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

// Owner-approval workflow transitions (Desk). All go through the same whitelisted ESS
// endpoints the PWA uses (operations/mr.py is the single source of truth).
function mr_line_decisions(frm) {
	return (frm.doc.used_items || []).map((r) => ({
		decision: r.decision || 'Pending',
		owner_remark: r.owner_remark || '',
	}));
}

function mr_call(frm, method, args, confirmMsg) {
	const go = () =>
		frappe.call({
			method,
			args: { repair_order: frm.doc.name, ...args },
			freeze: true,
			freeze_message: __('Memproses…'),
			callback: () => frm.reload_doc(),
		});
	const run = () => {
		if (frm.is_dirty()) frm.save().then(go);
		else go();
	};
	if (confirmMsg) frappe.confirm(confirmMsg, run);
	else run();
}

function mr_approve(frm) {
	mr_call(frm, 'container_depot.ess.repairs.mr_decision', {
		decision: 'Approved',
		line_decisions: JSON.stringify(mr_line_decisions(frm)),
	});
}

function mr_decision_with_note(frm, decision, title) {
	frappe.prompt(
		[{ fieldname: 'note', fieldtype: 'Small Text', label: __('Owner Note') }],
		(v) =>
			mr_call(frm, 'container_depot.ess.repairs.mr_decision', {
				decision,
				line_decisions: JSON.stringify(mr_line_decisions(frm)),
				note: v.note,
			}),
		__(title),
		__('Submit')
	);
}

frappe.ui.form.on('Repair Order', {
	setup(frm) {
		// Set queries or pre-filters if needed
	},
	refresh(frm) {
		// Status intro banner.
		const intros = {
			Draft: [__('Draft. Add the used items (estimate), then Submit for Approval.'), 'blue'],
			'Pending Approval': [__('Awaiting the owner\'s decision. Set each line\'s decision, then Approve / Reject / Request Revision.'), 'orange'],
			'Revision Requested': [__('Owner asked for a revision. Adjust the items and Submit for Approval again.'), 'orange'],
			Approved: [__('Approved by the owner. Ready to start repair work.'), 'green'],
			Rejected: [__('Rejected by the owner.'), 'red'],
			'In Progress': [__('Repair work is in progress in the workshop.'), 'yellow'],
			Completed: [__('Repair completed. Container is ready for service.'), 'green'],
			Cancelled: [__('This Repair Order has been cancelled.'), 'red'],
		};
		if (intros[frm.doc.status]) frm.set_intro(intros[frm.doc.status][0], intros[frm.doc.status][1]);

		frm.trigger('_mr_buttons');
		frm.trigger('_lock_estimate_grid');
	},
	_mr_buttons(frm) {
		if (frm.is_new()) return;
		const s = frm.doc.status;
		if (s === 'Draft' || s === 'Revision Requested') {
			frm.add_custom_button(__('Submit for Approval'), () =>
				mr_call(frm, 'container_depot.ess.repairs.mr_submit_approval', {})
			).addClass('btn-primary');
			// Admin-Ops bypass: approve directly without sending to the owner.
			if (frappe.user.has_role('Admin Ops') || frappe.user.has_role('System Manager')) {
				frm.add_custom_button(__('Approve Directly (Bypass Owner)'), () =>
					frappe.prompt(
						[{ fieldname: 'note', fieldtype: 'Small Text', label: __('Catatan (opsional)') }],
						(v) =>
							mr_call(
								frm,
								'container_depot.ess.repairs.mr_bypass_approval',
								{ note: v.note },
								__('Setujui langsung tanpa persetujuan owner?')
							),
						__('Bypass Owner'),
						__('Approve')
					)
				);
			}
		} else if (s === 'Pending Approval') {
			frm.add_custom_button(__('Approve'), () => mr_approve(frm)).addClass('btn-primary');
			frm.add_custom_button(__('Request Revision'), () =>
				mr_decision_with_note(frm, 'Revision Requested', 'Request Revision')
			);
			frm.add_custom_button(__('Reject'), () => mr_decision_with_note(frm, 'Rejected', 'Reject M&R'));
		} else if (s === 'Approved') {
			frm.add_custom_button(__('Start Repair'), () =>
				mr_call(frm, 'container_depot.ess.repairs.mr_start', {})
			).addClass('btn-primary');
		} else if (s === 'In Progress') {
			frm.add_custom_button(__('Complete'), () =>
				mr_call(frm, 'container_depot.ess.repairs.mr_order_save', { submit: 1 }, __('Selesaikan M&R dan keluarkan part yang disetujui dari stok?'))
			).addClass('btn-primary');
		}
		if (['Draft', 'Revision Requested', 'Pending Approval', 'Approved', 'In Progress'].includes(s)) {
			frm.add_custom_button(__('Cancel M&R'), () =>
				mr_call(frm, 'container_depot.ess.repairs.set_repair_status', { status: 'Cancelled' }, __('Batalkan M&R ini?'))
			);
		}
	},
	_lock_estimate_grid(frm) {
		const grid = frm.fields_dict.used_items && frm.fields_dict.used_items.grid;
		if (!grid) return;
		// Estimate editable only while Draft / Revision Requested. The per-line owner
		// decision + remark are editable only while Pending Approval.
		const editable = ['Draft', 'Revision Requested'].includes(frm.doc.status);
		const pending = frm.doc.status === 'Pending Approval';
		grid.cannot_add_rows = !editable;
		grid.cannot_delete_rows = !editable;
		// The adjustable cost inputs follow the estimate-build phase.
		['item', 'quantity', 'manhour', 'manhour_rate', 'material_cost'].forEach((f) =>
			grid.update_docfield_property(f, 'read_only', editable ? 0 : 1)
		);
		['decision', 'owner_remark'].forEach((f) => grid.update_docfield_property(f, 'read_only', pending ? 0 : 1));
		grid.refresh();
	},
	container(frm) {
		if (frm.doc.container) {
			// Fetch principal (owner) from Container record
			frappe.db.get_value('Container', frm.doc.container, 'principal', (r) => {
				if (r && r.principal) {
					frm.set_value('principal', r.principal);
				}
			});
		} else {
			frm.set_value('principal', '');
		}
	}
});

// Service & Parts Used — price each line as manhour × rate/manhour + material cost, keep it
// adjustable, and preview Rate / Amount / Total live (the server recomputes on save).
frappe.ui.form.on('Repair Used Item', {
	item(frm, cdt, cdn) {
		const row = frappe.get_doc(cdt, cdn);
		if (!row.item || frm.is_new()) return;
		// Default the cost inputs from the owner's Item Price for the picked item.
		frappe.call({
			method: 'container_depot.ess.repairs.mr_item_pricing',
			args: { repair_order: frm.doc.name, item: row.item },
			callback: (r) => {
				const b = r.message || {};
				// Currency follows the item's own Item Price (lines may differ).
				frappe.model.set_value(cdt, cdn, 'currency', b.currency || '');
				frappe.model.set_value(cdt, cdn, 'manhour', flt(b.manhour));
				frappe.model.set_value(cdt, cdn, 'manhour_rate', flt(b.manhour_rate));
				frappe.model.set_value(cdt, cdn, 'material_cost', flt(b.material_cost));
			},
		});
	},
	// Labour inputs -> derive Manhour Cost, then Rate, then Amount.
	manhour: price_from_labour,
	manhour_rate: price_from_labour,
	// Manhour Cost / Material Cost changed (incl. a manual Manhour Cost override) -> Rate, Amount.
	manhour_amount: price_from_components,
	material_cost: price_from_components,
	// Rate manually overridden, or qty changed -> Amount only (Rate is trusted as final).
	rate: price_amount_only,
	quantity: price_amount_only,
	decision: recompute_used_total,
	used_items_remove: recompute_used_total,
});

// Manhour Cost and Rate are adjustable: editing an upstream field recomputes downstream, but
// a direct edit of Manhour Cost or Rate is honoured (we never recompute a field from its own
// change). Amount is always qty × Rate. The server mirrors this on save.
function price_from_labour(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	const manhour_amount = flt(row.manhour) * flt(row.manhour_rate);
	const rate = manhour_amount + flt(row.material_cost);
	frappe.model.set_value(cdt, cdn, 'manhour_amount', manhour_amount);
	frappe.model.set_value(cdt, cdn, 'rate', rate);
	frappe.model.set_value(cdt, cdn, 'amount', flt(row.quantity) * rate);
	recompute_used_total(frm);
}

function price_from_components(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	const rate = flt(row.manhour_amount) + flt(row.material_cost);
	frappe.model.set_value(cdt, cdn, 'rate', rate);
	frappe.model.set_value(cdt, cdn, 'amount', flt(row.quantity) * rate);
	recompute_used_total(frm);
}

function price_amount_only(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	frappe.model.set_value(cdt, cdn, 'amount', flt(row.quantity) * flt(row.rate));
	recompute_used_total(frm);
}

function recompute_used_total(frm) {
	// Group by currency — a Repair Order can mix currencies (each Item Price carries its own).
	let numeric = 0;
	const by_currency = {};
	const default_currency = frappe.defaults.get_default('currency');
	(frm.doc.used_items || []).forEach((r) => {
		if ((r.decision || 'Pending') !== 'Rejected') {
			numeric += flt(r.amount);
			const cur = r.currency || default_currency;
			by_currency[cur] = (by_currency[cur] || 0) + flt(r.amount);
		}
	});
	frm.set_value('total_cost', numeric);
	frm.clear_table('totals');
	Object.keys(by_currency).sort().forEach((cur) => {
		const row = frm.add_child('totals');
		row.currency = cur;
		row.total = by_currency[cur];
	});
	frm.refresh_field('totals');
}

