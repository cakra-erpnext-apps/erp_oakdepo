// "Ambil Charges" / "Simpan sebagai Template" — Service & Parts lines copied from another
// order (M&R, Periodic Test, Cleaning) or a Charge Template instead of typed in one by one.
// The server does the mapping and the pricing (doctype/charge_template/charge_template.py);
// this only asks where from, then appends. Every copied line stays editable.
//
// Container Booking's Charges get the same two buttons as a separate family: sources are
// other bookings and Booking Charge Templates of the same direction (the picker starts on the
// booking's own Customer (Bill To), another customer's may be picked), never M&R / Cleaning
// lines. Only the services are copied; every rate comes from the Bill To's contract.
//
// Loaded per doctype via hooks.doctype_js, next to each form's own script.
frappe.provide('container_depot');

const CHARGE_METHOD = 'container_depot.container_depot.doctype.charge_template.charge_template.';
const CHARGE_TABLE = { 'Repair Order': 'used_items', 'Cleaning Order': 'cleaning_services', 'Container Booking': 'charges' };
const is_booking = (frm) => frm.doctype === 'Container Booking';
const template_doctype = (frm) => (is_booking(frm) ? 'Booking Charge Template' : 'Charge Template');

// Same windows the grids themselves are editable in (repair_order.js _lock_estimate_grid;
// Cleaning's Admin Ops step; a booking's charges until an invoice carries them, Confirmed
// included — container_booking.js _charges_open). A part short on stock may land here — the
// step after refuses.
function charges_editable(frm) {
	if (frm.doctype === 'Repair Order') return ['Draft', 'Revision Requested'].includes(frm.doc.status);
	if (is_booking(frm)) {
		if (frm.doc.docstatus === 2 || frm.doc.booking_status === 'Cancelled') return false;
		return frappe.boot.depot_finance_enabled === 0 || !frm.doc.sales_invoice;
	}
	return frm.doc.docstatus === 0 && frm.doc.status === 'Service Setup';
}

// M&R and Periodic Test share the Repair Order doctype but are two menus to the user, so
// they are two choices here too, told apart by job_type.
const SOURCE_KINDS = {
	repair: { label: 'M&R', doctype: 'Repair Order', job_type: 'Repair' },
	periodic: { label: 'Periodic Test', doctype: 'Repair Order', job_type: 'Periodic Test' },
	cleaning: { label: 'Cleaning Order', doctype: 'Cleaning Order' },
	template: { label: 'Charge Template', doctype: 'Charge Template' },
};
const BOOKING_KINDS = {
	booking_template: { label: 'Booking Charge Template', doctype: 'Booking Charge Template' },
	booking: { label: 'Container Booking', doctype: 'Container Booking' },
};

function own_kind(frm) {
	if (is_booking(frm)) return 'booking_template';
	if (frm.doctype === 'Cleaning Order') return 'cleaning';
	return frm.doc.job_type === 'Periodic Test' ? 'periodic' : 'repair';
}

function copy_dialog(frm) {
	const table = CHARGE_TABLE[frm.doctype];
	const booking = is_booking(frm);
	// The rates come from this customer's contract, and changing the customer afterwards
	// empties the charges anyway (_reset_charges_on_customer_change).
	if (booking && !frm.doc.customer) {
		frappe.msgprint(__('Isi Customer (Bill To) dulu — tarif charges diambil dari kontraknya.'));
		return;
	}
	const KINDS = booking ? BOOKING_KINDS : SOURCE_KINDS;
	const contract = frm.__oak_rate_card && frm.__oak_rate_card.contract;
	// `let` + guard: the dialog may fire onchange while setting defaults, before `d` exists.
	let d = null;
	const price_field = booking
		? {
				fieldname: 'price_note', fieldtype: 'HTML',
				options: `<p class="text-muted small">${__(
					'Tarif diambil dari kontrak Customer (Bill To) {0}. Service yang tidak ada di kontraknya masuk dengan tarif 0.',
					[`<b>${frappe.utils.escape_html(frm.doc.customer)}</b>`]
				)}</p>`,
			}
		: {
				fieldname: 'price_source', fieldtype: 'Select', label: __('Harga'), reqd: 1,
				options: [
					{ value: 'source', label: __('Ikut order / template sumber') },
					{ value: 'contract', label: __('Dari kontrak pemilik tank') },
				],
				default: 'source',
				// rate_card_notice only asks once the order is saved; a new form does not know yet.
				description: contract
					? __('Kontrak aktif: {0}. Item yang tidak ada di kontrak tetap pakai harga sumber.', [contract])
					: frm.__oak_rate_card
						? __('Pemilik tank ini belum punya kontrak aktif — harga ikut sumber.')
						: __('Item yang tidak ada di kontrak pemilik tank (atau tanpa kontrak) tetap pakai harga sumber.'),
			};
	d = new frappe.ui.Dialog({
		title: __('Ambil Charges'),
		fields: [
			{
				fieldname: 'source_kind', fieldtype: 'Select', label: __('Ambil dari'), reqd: 1,
				options: Object.keys(KINDS).map((k) => ({ value: k, label: __(KINDS[k].label) })),
				default: own_kind(frm),
				onchange: () => {
					if (!d) return;
					d.set_value('source_doctype', KINDS[d.get_value('source_kind')].doctype);
					d.set_value('source', '');
				},
			},
			{ fieldname: 'source_doctype', fieldtype: 'Data', hidden: 1, default: KINDS[own_kind(frm)].doctype },
			booking && {
				fieldname: 'customer', fieldtype: 'Link', options: 'Customer', label: __('Milik Customer'),
				default: frm.doc.customer,
				description: __('Default = Customer (Bill To) booking ini. Ganti untuk memakai template / booking customer lain; kosongkan untuk semua.'),
				onchange: () => d && d.set_value('source', ''),
			},
			{
				fieldname: 'source', fieldtype: 'Dynamic Link', options: 'source_doctype', label: __('Order / Template'), reqd: 1,
				description: booking
					? __('Cari nomor booking, Reff Doc, atau nama template. Hanya arah {0}.', [__(frm.doc.direction || '')])
					: __('Cari nomor order, Reff Doc, no. tank, atau nama template.'),
				get_query: () => ({
					query: CHARGE_METHOD + 'charge_source_query',
					filters: {
						exclude: frm.doc.name || '',
						job_type: KINDS[d.get_value('source_kind')].job_type || '',
						direction: booking ? frm.doc.direction || '' : '',
						customer: booking ? d.get_value('customer') || '' : '',
					},
				}),
			},
			price_field,
			{ fieldname: 'replace', fieldtype: 'Check', label: __('Ganti semua baris yang sudah ada') },
		].filter(Boolean),
		primary_action_label: __('Ambil'),
		primary_action(v) {
			frappe
				.call(CHARGE_METHOD + 'get_charges', {
					source_doctype: v.source_doctype,
					source_name: v.source,
					target_doctype: frm.doctype,
					container: frm.doc.container || '',
					customer: booking ? frm.doc.customer || '' : '',
					direction: booking ? frm.doc.direction || '' : '',
					price_source: v.price_source || 'source',
				})
				.then((r) => {
					if (v.replace) frm.clear_table(table);
					// A booking's qty is the container count, never the source's; left untouched
					// (no _qty_touched) so it keeps following the containers.
					const qty = booking ? { qty: (frm.doc.items || []).length || 1 } : {};
					r.message.rows.forEach((row) => frm.add_child(table, { ...row, ...qty }));
					frm.refresh_field(table);
					if (booking) frm.trigger('_recompute_charges');
					frm.dirty();
					d.hide();
					frappe.show_alert({
						message: __('{0} baris ditambahkan. Cek lalu Save.', [r.message.rows.length]),
						indicator: 'green',
					});
				});
		},
	});
	d.show();
}

function save_template_prompt(frm) {
	frappe.prompt(
		[{ fieldname: 'template_name', fieldtype: 'Data', label: __('Nama Template'), reqd: 1 }],
		(v) =>
			frappe
				.call(CHARGE_METHOD + 'save_as_template', {
					source_doctype: frm.doctype,
					source_name: frm.doc.name,
					template_name: v.template_name,
				})
				.then((r) =>
					frappe.show_alert({
						message: __('Template {0} tersimpan.', [
							`<a href="/app/${frappe.router.slug(template_doctype(frm))}/${encodeURIComponent(r.message)}">${frappe.utils.escape_html(r.message)}</a>`,
						]),
						indicator: 'green',
					})
				),
		__('Simpan sebagai {0}', [__(template_doctype(frm))]),
		__('Simpan')
	);
}

// Right under the table's own heading (the grid's "top" button slot), not the form toolbar.
// The grid outlives the document it shows, so each button is created once and then only
// shown or hidden; the handlers read frm.doc at click time.
Object.keys(CHARGE_TABLE).forEach((doctype) =>
	frappe.ui.form.on(doctype, {
		refresh(frm) {
			const table = CHARGE_TABLE[doctype];
			const grid = frm.fields_dict[table] && frm.fields_dict[table].grid;
			if (!grid) return;
			// Prepended, so added in reverse: "Ambil Charges" ends up first.
			grid.add_custom_button(__('Simpan sebagai Template'), () => save_template_prompt(frm), 'top').toggleClass(
				'hidden',
				!(!frm.is_new() && (frm.doc[table] || []).length && frappe.model.can_create(template_doctype(frm)))
			);
			// Template read too: a Customer Desk account may edit its own draft booking but has
			// no business browsing OAK's templates.
			const can_copy =
				charges_editable(frm) && frappe.perm.has_perm(frm.doctype, 0, 'write') && frappe.model.can_read(template_doctype(frm));
			grid.add_custom_button(__('Ambil Charges'), () => copy_dialog(frm), 'top').toggleClass('hidden', !can_copy);
			// One-line hint under the buttons, made once per grid like the buttons themselves.
			let $hint = grid.grid_custom_buttons.next('.oak-charge-hint');
			if (!$hint.length) {
				$hint = $('<p class="text-muted small oak-charge-hint"></p>')
					.text(
						is_booking(frm)
							? __('Ambil Charges: salin service dari Booking Charge Template atau booking lain dengan arah yang sama — tarif dari kontrak Customer (Bill To), qty ikut jumlah container.')
							: __('Ambil Charges: salin baris dari order M&R, Periodic Test, Cleaning, atau Charge Template — harga ikut sumber atau kontrak, semua tetap bisa diubah.')
					)
					.insertAfter(grid.grid_custom_buttons);
			}
			$hint.toggleClass('hidden', !can_copy);
		},
	})
);
