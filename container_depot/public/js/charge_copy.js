// "Ambil Charges" / "Simpan sebagai Template" — Service & Parts lines copied from another
// order (M&R, Periodic Test, Cleaning) or a Charge Template instead of typed in one by one.
// The server does the mapping and the pricing (doctype/charge_template/charge_template.py);
// this only asks where from, then appends. Every copied line stays editable.
//
// Loaded per doctype via hooks.doctype_js, next to each form's own script.
frappe.provide('container_depot');

const CHARGE_METHOD = 'container_depot.container_depot.doctype.charge_template.charge_template.';
const CHARGE_TABLE = { 'Repair Order': 'used_items', 'Cleaning Order': 'cleaning_services' };

// Same windows the grids themselves are editable in (repair_order.js _lock_estimate_grid;
// Cleaning's Admin Ops step). A part short on stock may land here — the step after refuses.
function charges_editable(frm) {
	if (frm.doctype === 'Repair Order') return ['Draft', 'Revision Requested'].includes(frm.doc.status);
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

function own_kind(frm) {
	if (frm.doctype === 'Cleaning Order') return 'cleaning';
	return frm.doc.job_type === 'Periodic Test' ? 'periodic' : 'repair';
}

function copy_dialog(frm) {
	const table = CHARGE_TABLE[frm.doctype];
	const contract = frm.__oak_rate_card && frm.__oak_rate_card.contract;
	// `let` + guard: the dialog may fire onchange while setting defaults, before `d` exists.
	let d = null;
	d = new frappe.ui.Dialog({
		title: __('Ambil Charges'),
		fields: [
			{
				fieldname: 'source_kind', fieldtype: 'Select', label: __('Ambil dari'), reqd: 1,
				options: Object.keys(SOURCE_KINDS).map((k) => ({ value: k, label: __(SOURCE_KINDS[k].label) })),
				default: own_kind(frm),
				onchange: () => {
					if (!d) return;
					d.set_value('source_doctype', SOURCE_KINDS[d.get_value('source_kind')].doctype);
					d.set_value('source', '');
				},
			},
			{ fieldname: 'source_doctype', fieldtype: 'Data', hidden: 1, default: SOURCE_KINDS[own_kind(frm)].doctype },
			{
				fieldname: 'source', fieldtype: 'Dynamic Link', options: 'source_doctype', label: __('Order / Template'), reqd: 1,
				description: __('Cari nomor order, Reff Doc, no. tank, atau nama template.'),
				get_query: () => ({
					query: CHARGE_METHOD + 'charge_source_query',
					filters: { exclude: frm.doc.name || '', job_type: SOURCE_KINDS[d.get_value('source_kind')].job_type || '' },
				}),
			},
			{
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
			},
			{ fieldname: 'replace', fieldtype: 'Check', label: __('Ganti semua baris yang sudah ada') },
		],
		primary_action_label: __('Ambil'),
		primary_action(v) {
			frappe
				.call(CHARGE_METHOD + 'get_charges', {
					source_doctype: v.source_doctype,
					source_name: v.source,
					target_doctype: frm.doctype,
					container: frm.doc.container || '',
					price_source: v.price_source,
				})
				.then((r) => {
					if (v.replace) frm.clear_table(table);
					r.message.rows.forEach((row) => frm.add_child(table, row));
					frm.refresh_field(table);
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
							`<a href="/app/charge-template/${encodeURIComponent(r.message)}">${frappe.utils.escape_html(r.message)}</a>`,
						]),
						indicator: 'green',
					})
				),
		__('Simpan sebagai Charge Template'),
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
				!(!frm.is_new() && (frm.doc[table] || []).length && frappe.model.can_create('Charge Template'))
			);
			const can_copy = charges_editable(frm) && frappe.perm.has_perm(frm.doctype, 0, 'write');
			grid.add_custom_button(__('Ambil Charges'), () => copy_dialog(frm), 'top').toggleClass('hidden', !can_copy);
			// One-line hint under the buttons, made once per grid like the buttons themselves.
			let $hint = grid.grid_custom_buttons.next('.oak-charge-hint');
			if (!$hint.length) {
				$hint = $('<p class="text-muted small oak-charge-hint"></p>')
					.text(
						__('Ambil Charges: salin baris dari order M&R, Periodic Test, Cleaning, atau Charge Template — harga ikut sumber atau kontrak, semua tetap bisa diubah.')
					)
					.insertAfter(grid.grid_custom_buttons);
			}
			$hint.toggleClass('hidden', !can_copy);
		},
	})
);
