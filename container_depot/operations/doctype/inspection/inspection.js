// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

// Inspection (EIR) — Desk client script.
// House style mirrors container_booking.js (custom buttons, narrative comments).
// The damage-entry dialogs build Inspection Damage Entry rows whose mapping (component / area /
// default severity & description) matches the server builder in
// container_depot/operations/eir.py:create_eir — keep the two in sync.

frappe.ui.form.on('Inspection', {
	refresh(frm) {
		// "Cancel" (Desk-only): return a submitted EIR to Draft so it can be edited again
		// in the PWA / Inspection menu.
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__('Kembalikan ke Draft'), () => revert_to_draft(frm));
		}
		// Surface an inconsistency without blocking: damage flagged but no rows.
		if (!frm.is_new() && frm.doc.has_damage && (frm.doc.damage_log || []).length === 0) {
			frappe.warn(
				__('No Damage Log'),
				__('Has Damage is checked but no damage entries recorded.'),
				() => {},
				__('Continue'),
			);
		}
		// "Search by section" for sorting bulk ("foto cepat") photos: quick-filter the
		// item_photos grid by Area — including a "Belum disortir" bucket for the photos the
		// operator dumped without a section. Works on submitted EIRs (item_photos is
		// allow_on_submit) so the admin can sort after the fact.
		if (!frm.is_new() && (frm.doc.item_photos || []).length) {
			frm.add_custom_button(__('Filter Foto per Section'), () => filter_photos_by_section(frm));
		}
	},

	// Ticking "Has Damage" opens a single-row entry dialog with VALID Link fields.
	// Legacy bug (fixed here): this used a Select of component names (Gasket/Valve/…)
	// written straight into `damage_type`, which is now a Link -> Inspection Damage Code — so
	// every value it produced was an invalid link. The dialog below uses the real
	// taxonomy and defaults the reqd Inspection Damage Entry fields the same way the server does.
	has_damage(frm) {
		if (frm.doc.has_damage) add_damage_entry(frm);
	},

	// The EIR inspects a physical container, so picking the Container prefills the
	// header from the SAME whitelisted function the PWA uses (see
	// prefill_from_container) — one prefill implementation, keyed on the container.
	container(frm) {
		if (frm.doc.container) prefill_from_container(frm);
	},
});

// "Kembalikan ke Draft" — revert a submitted EIR to an editable draft. The server guards
// that no other draft exists for the same container before flipping docstatus back to 0
// and undoing the container status/cargo this EIR applied.
function revert_to_draft(frm) {
	frappe.confirm(
		__('Kembalikan EIR ini ke Draft agar bisa diedit lagi? Semua EIR draft untuk container ini harus sudah disubmit.'),
		() => {
			frappe.call({
				method: 'container_depot.operations.eir.revert_to_draft',
				args: { name: frm.doc.name },
				freeze: true,
				freeze_message: __('Mengembalikan ke draft…'),
				callback() {
					frappe.show_alert({ message: __('EIR dikembalikan ke draft'), indicator: 'green' });
					frm.reload_doc();
				},
			});
		},
	);
}

// --- Bulk photo sorting (Desk) ---
// Prompt for a section and show only the matching item_photos rows. "(Belum disortir)"
// isolates the bulk "foto cepat" that still need a checklist_item assigned; "(Semua)"
// clears the filter.
function filter_photos_by_section(frm) {
	const areas = [...new Set((frm.doc.item_photos || []).map((r) => r.area).filter(Boolean))].sort();
	const options = [__('(Semua)'), __('(Belum disortir)'), ...areas].join('\n');
	frappe.prompt(
		[{ fieldname: 'area', fieldtype: 'Select', label: __('Section / Area'), options, reqd: 1 }],
		(v) => apply_photo_filter(frm, v.area),
		__('Filter Foto per Section'),
		__('Terapkan'),
	);
}

function apply_photo_filter(frm, area) {
	const grid = frm.fields_dict.item_photos && frm.fields_dict.item_photos.grid;
	if (!grid) return;
	const all = area === __('(Semua)');
	const unsorted = area === __('(Belum disortir)');
	(grid.grid_rows || []).forEach((gr) => {
		const a = (gr.doc || {}).area;
		const match = all || (unsorted ? !a : a === area);
		if (gr.wrapper) $(gr.wrapper).toggle(!!match);
	});
}

// When the admin assigns a section to a bulk photo in the grid, fill Area/Item at once
// (fetch_from also does this, but set it explicitly so the filter above sees it live).
frappe.ui.form.on('Inspection Item Photo', {
	checklist_item(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.checklist_item) return;
		frappe.db
			.get_value('Inspection Checklist Item', row.checklist_item, ['item_name', 'area'])
			.then((r) => {
				const ci = r.message || {};
				frappe.model.set_value(cdt, cdn, 'area', ci.area);
				frappe.model.set_value(cdt, cdn, 'item_name', ci.item_name);
			});
	},
});

// --- B-D2: Inspection Damage Entry grid fetch triggers (manual in-grid editing) ---
// Mirror create_eir's mapping so a row built by hand matches one built by the
// checklist dialog / PWA: checklist item -> component + area, repair code ->
// estimated hours, damage code -> description + default severity.
frappe.ui.form.on('Inspection Damage Entry', {
	checklist_item(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.checklist_item) return;
		frappe.db
			.get_value('Inspection Checklist Item', row.checklist_item, ['printed_no', 'item_name', 'area'])
			.then((r) => {
				const ci = r.message || {};
				frappe.model.set_value(cdt, cdn, 'component', `${ci.printed_no}. ${ci.item_name}`);
				frappe.model.set_value(cdt, cdn, 'area', ci.area);
			});
	},

	repair_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.repair_code || row.estimated_repair_hours) return;
		frappe.db.get_value('Inspection Repair Code', row.repair_code, 'standard_hours').then((r) => {
			const hours = (r.message || {}).standard_hours;
			if (hours) frappe.model.set_value(cdt, cdn, 'estimated_repair_hours', hours);
		});
	},

	damage_type(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.damage_type) return;
		if (!row.severity) frappe.model.set_value(cdt, cdn, 'severity', 'Minor');
		if (!row.damage_description) {
			frappe.db.get_value('Inspection Damage Code', row.damage_type, 'description').then((r) => {
				const desc = (r.message || {}).description;
				const fresh = locals[cdt][cdn];
				if (desc && fresh && !fresh.damage_description) {
					frappe.model.set_value(cdt, cdn, 'damage_description', desc);
				}
			});
		}
	},
});

function add_damage_entry(frm) {
	const d = new frappe.ui.Dialog({
		title: __('Tambah Kerusakan'),
		fields: [
			{ fieldname: 'checklist_item', fieldtype: 'Link', label: __('Checklist Item'), options: 'Inspection Checklist Item' },
			{ fieldname: 'damage_type', fieldtype: 'Link', label: __('Damage Code'), options: 'Inspection Damage Code' },
			{ fieldname: 'repair_code', fieldtype: 'Link', label: __('Repair Code'), options: 'Inspection Repair Code' },
			{ fieldname: 'severity', fieldtype: 'Select', label: __('Severity'), options: 'Minor\nModerate\nMajor\nCritical', default: 'Minor' },
			{ fieldname: 'damage_description', fieldtype: 'Small Text', label: __('Description'), description: __('Optional — defaults to the damage code description or the item name.') },
		],
		primary_action_label: __('Add'),
		primary_action(values) {
			append_damage_row(frm, values).then(() => d.hide());
		},
	});
	d.show();
}

// Resolve a checklist item's printed_no / item_name / area (used to fill component+area).
function resolve_checklist(item_code) {
	if (!item_code) return Promise.resolve(null);
	return frappe.db
		.get_value('Inspection Checklist Item', item_code, ['printed_no', 'item_name', 'area'])
		.then((r) => r.message || null);
}

// Append one Inspection Damage Entry, mirroring create_eir's mapping: component =
// "{printed_no}. {item_name}", area from the checklist item, severity defaults Minor,
// and a non-empty description (input -> damage code desc -> item name) so the reqd
// fields never trip validation.
function append_damage_row(frm, values) {
	return resolve_checklist(values.checklist_item).then((ci) => {
		const finish = (desc) => {
			frm.add_child('damage_log', {
				checklist_item: values.checklist_item || undefined,
				area: ci ? ci.area : undefined,
				component: ci ? `${ci.printed_no}. ${ci.item_name}` : undefined,
				damage_type: values.damage_type || undefined,
				repair_code: values.repair_code || undefined,
				damage_description: desc || (ci ? ci.item_name : __('Damage')),
				severity: values.severity || 'Minor',
				repair_status: 'Pending',
			});
			frm.refresh_field('damage_log');
		};
		const typed = (values.damage_description || '').trim();
		if (typed) return finish(typed);
		if (values.damage_type) {
			return frappe.db
				.get_value('Inspection Damage Code', values.damage_type, 'description')
				.then((r) => finish((r.message || {}).description));
		}
		return finish('');
	});
}

// --- B-D4: prefill the EIR header from the Container ---
// Calls the SAME whitelisted function the PWA uses
// (container_depot.ess.inspections.eir_prefill -> operations.eir.prefill). There is
// exactly one prefill implementation; Desk is just another caller of it, keyed on the
// container number. Native fetch_from already fills serial/capacity/etc. from the
// container; this adds depot, tank owner and the display-only ISO 6346 derive. Only
// blank fields are filled, so manual input is never clobbered.
function prefill_from_container(frm) {
	frappe.call({
		method: 'container_depot.ess.inspections.eir_prefill',
		args: { container: frm.doc.container },
		callback(r) {
			const d = r.message;
			if (!d) return;
			const fills = {
				depot: d.depot,
				vessel: d.ex_vessel,
				serial_no: d.serial_no,
				manufacture_date: d.manufacture_date,
				capacity: d.capacity,
				tare_weight: d.tare_weight,
				max_gross_weight: d.max_gross_weight,
				last_test_date: d.last_test_date,
				last_cargo: d.last_cargo,
			};
			Object.keys(fills).forEach((f) => {
				if (fills[f] != null && fills[f] !== '' && !frm.doc[f]) frm.set_value(f, fills[f]);
			});
			if (d.prefix || d.number || d.cd) {
				frm.dashboard.clear_comment();
				frm.dashboard.add_comment(
					__('ISO 6346 — Prefix: {0} · Number: {1} · Cd: {2}', [
						d.prefix || '—',
						d.number || '—',
						d.cd || '—',
					]),
					'blue',
					true,
				);
			}
		},
	});
}
