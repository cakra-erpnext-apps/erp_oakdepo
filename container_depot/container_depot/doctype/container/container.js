// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

frappe.ui.form.on('Container', {
	refresh(frm) {
		render_seal_history(frm);
		if (!frm.is_new()) {
			// Add custom buttons for common actions
			frm.add_custom_button(__('Gate-In'), () => {
				frappe.call({
					method: 'container_depot.container_depot.doctype.container.container.create_gate_entry',
					args: {
						container_no: frm.doc.container_no
					},
					callback: (r) => {
						if (!r.exc) {
							frappe.msgprint('Gate Entry created');
						}
					}
				});
			});

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
