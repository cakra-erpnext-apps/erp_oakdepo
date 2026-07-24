// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

// The "Metode Cleaning (Service)" table picks one OR MORE cleaning services the container
// Owner (Principal) is priced for: members of the Depot Service Menu "Cleaning" that have a
// selling Item Price in the owner's active Price List (resolved server-side from the
// container).
//
// Each row carries the two things the contract states about a service, side by side: its
// Tarif (money) and its Manhour (hours). Both are SEEDED from the active Depot Contract of
// the container's owner the moment a Service is picked, and both stay EDITABLE — a seeded
// value is never re-applied, so a negotiated one-off figure survives every later save.
// They roll up into Total Tarif Service and Total Manhour (jam), which are deliberately NOT
// added together: billing totals the manhours of everything on the invoice and charges them
// once, on their own line. Costing them here too would bill labour twice.
frappe.ui.form.on('Cleaning Order', {
	onload(frm) {
		frm.trigger('_set_queries');
	},
	refresh(frm) {
		frm.trigger('_set_queries');
		frm.trigger('_forward_button');
	},
	container(frm) {
		// New container → its owner may price a different cleaning catalogue; drop the picks.
		if ((frm.doc.cleaning_services || []).length) frm.clear_table('cleaning_services');
		frm.refresh_field('cleaning_services');
		_recalc(frm);
		frm.trigger('_set_queries');
	},
	_set_queries(frm) {
		frm.set_query('cleaning_item', 'cleaning_services', () => ({
			query: 'container_depot.operations.doctype.cleaning_order.cleaning_order.cleaning_item_query',
			filters: { container: frm.doc.container || '' },
		}));
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
});

frappe.ui.form.on('Cleaning Order Service', {
	cleaning_item(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.cleaning_item) {
			frappe.model.set_value(cdt, cdn, { rate: 0 });
			_recalc(frm);
			return;
		}
		if (!frm.doc.container) {
			frappe.msgprint(__('Pilih Container dulu — base price diambil dari kontrak pemilik tank.'));
			return;
		}
		// Seed from the owner's contract immediately. A different Service means a different
		// base price, so the tariff is re-seeded here even if it already carried a value.
		frappe.call({
			method: 'container_depot.operations.doctype.cleaning_order.cleaning_order.service_pricing',
			args: { container: frm.doc.container, item_code: row.cleaning_item },
			callback(r) {
				const d = (r && r.message) || {};
				const patch = { rate: d.rate || 0, currency: d.currency, item_name: d.item_name };
				// The labour rate is per depot, not per service — seed it once only.
				if (!flt(row.manhour_rate) && d.manhour_rate) patch.manhour_rate = d.manhour_rate;
				frappe.model.set_value(cdt, cdn, patch).then(() => _recalc(frm));
				if (!d.price_list) {
					frappe.show_alert({
						message: __('Owner container ini belum punya kontrak aktif — isi tarif manual.'),
						indicator: 'orange',
					});
				}
			},
		});
	},
	rate(frm) {
		_recalc(frm);
	},
	manhour_rate(frm) {
		_recalc(frm);
	},
	cleaning_services_remove(frm) {
		_recalc(frm);
	},
});

// Money and hours are totalled apart — never into one figure.
function _recalc(frm) {
	let service = 0;
	let manhour = 0;
	for (const row of frm.doc.cleaning_services || []) {
		service += flt(row.rate);
		manhour += flt(row.manhour_rate);
	}
	frm.set_value('cleaning_total', service);
	frm.set_value('manhour_total', manhour);
}
