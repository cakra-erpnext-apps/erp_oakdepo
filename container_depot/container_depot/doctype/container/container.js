// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Container', {
	refresh(frm) {
		render_seal_history(frm);
		link_last_orders(frm);
		// A "Gate-In" button used to sit here calling
		// `container.create_gate_entry`. That method has never existed anywhere in the
		// app — the only whitelist in container.py is `seal_history` — so the button
		// failed for everyone who pressed it, whatever their role. Removed rather than
		// written: a gate-in is raised from the Gate PWA against a Booking Code, which is
		// what supplies the code, the truck and the driver. Conjuring one from a Container
		// form would have none of that.
		// can_create, not perm.has_perm: has_perm on a doctype whose meta the client has not
		// loaded answers a silent `false` for every right but read. See container_booking.js.
		if (!frm.is_new() && frappe.model.can_create('Inspection')) {
			frm.add_custom_button(__('Inspection'), () => {
				frappe.new_doc('Inspection', {
					container: frm.doc.name
				});
			});
		}
	}
});

// --- Seals -----------------------------------------------------------------------
// The master used to hold five seal Data fields that nothing ever filled in. Seals are
// fitted at release and written on the EIR-Out, and a tank is sealed once per release — so
// the master shows the whole history read live from those EIR-Outs instead of one set of
// numbers that would still read as current after the tank came back and was unsealed.
function render_seal_history(frm) {
	const field = frm.get_field('seal_history_html');
	if (!field) return;
	// Nothing to report on a tank that has not been saved yet.
	frm.toggle_display('seals_section', !frm.is_new());
	if (frm.is_new()) {
		field.$wrapper.empty();
		return;
	}
	// An empty box would read as "no seals", which is a different answer from "not loaded".
	field.$wrapper.html(`<div class="text-muted">${__('Memuat…')}</div>`);
	const shown_for = frm.doc.name;
	frappe.call({
		method: 'container_depot.container_depot.doctype.container.container.seal_history',
		args: { container: frm.doc.name },
	}).then((r) => {
		if (frm.doc.name !== shown_for) return; // reply landed after the form moved on
		field.$wrapper.html(seal_history_html(r.message || []));
	});
}

function seal_history_html(releases) {
	const esc = frappe.utils.escape_html;
	if (!releases.length) {
		return `<div class="text-muted">${__('Belum ada nomor seal. Seal dicatat di EIR-Out saat tank keluar depo.')}</div>`;
	}
	return releases
		.map((rel) => {
			const head = [
				frappe.utils.get_form_link('Inspection', rel.eir, true, esc(rel.eir)),
				rel.eir_date ? esc(frappe.datetime.str_to_user(rel.eir_date)) : null,
				rel.outcome ? esc(rel.outcome) : null,
			]
				.filter(Boolean)
				.join(' · ');
			const seals = rel.seals
				.map((s) => {
					const note = s.remarks ? ` <span class="text-muted">(${esc(s.remarks)})</span>` : '';
					return `<span class="indicator-pill blue no-indicator-dot mr-2 mb-1">${esc(s.seal_no || '-')}${note}</span>`;
				})
				.join('');
			return `
				<div class="mb-3">
					<div class="text-muted small mb-1">${head}</div>
					<div>${seals}</div>
				</div>`;
		})
		.join('');
}

// --- "order terakhir" cache ------------------------------------------------------
// These are Data, not Link, on purpose: Frappe validates a Link's target before any hook
// of ours can run, so a pointer left dangling by a raw delete would block this Container
// from ever saving again (see last_orders.py). Being Data costs the click-through, which
// this puts back — the value is a document name, so it renders as the link it names.
const LAST_ORDER_DOCTYPES = {
	last_booking: 'Container Booking',
	last_order_bongkar: 'Order Bongkar',
	last_order_muat: 'Order Muat',
	last_cleaning_order: 'Cleaning Order',
	last_repair_order: 'Repair Order',
	last_eir_in: 'Inspection',
	last_eir_out: 'Inspection'
};

function link_last_orders(frm) {
	Object.entries(LAST_ORDER_DOCTYPES).forEach(([fieldname, doctype]) => {
		const df = frm.fields_dict[fieldname] && frm.fields_dict[fieldname].df;
		if (!df || df.formatter) return;
		// get_form_link emits this desk's own route, so the link holds wherever it is mounted.
		df.formatter = (value) =>
			value ? frappe.utils.get_form_link(doctype, value, true, frappe.utils.escape_html(value)) : '';
	});
	frm.refresh_fields(Object.keys(LAST_ORDER_DOCTYPES));
}
