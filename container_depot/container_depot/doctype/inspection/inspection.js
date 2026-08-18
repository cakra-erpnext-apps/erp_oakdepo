// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

// Inspection (EIR) — Desk client script.
// House style mirrors container_booking.js (custom buttons, narrative comments).
// The damage-entry dialogs build Inspection Damage Entry rows whose mapping (component / area /
// default severity & description) matches the server builder in
// container_depot/container_depot/eir.py:create_eir — keep the two in sync.

frappe.ui.form.on('Inspection', {
	// The photo formatters MUST be installed here, not in refresh. form.js renders the
	// fields and only then fires the refresh trigger (frappe.run_serially in render_form:
	// refresh_fields() comes before script_manager.trigger("refresh")), so a formatter
	// installed in refresh arrives after the grid has already painted its columns as
	// plain URLs — and nothing re-renders it afterwards. setup runs once, before any of it.
	setup(frm) {
		// Retired tanks (Active off) are out of the fleet and never offered.
		frm.set_query('container', () => ({ filters: { is_active: 1 } }));
		install_photo_thumbnails(frm);
	},

	refresh(frm) {
		set_direction_banner(frm);
		set_signature_preview(frm);
		// Field operator submitted from the PWA → awaiting Admin Ops review. Prompt the
		// reviewer to check + Submit (the native Submit finalizes it).
		if (frm.doc.docstatus === 0 && frm.doc.status === 'Pending Review') {
			frm.dashboard.add_comment(
				__('Menunggu review Adm Ops — periksa lalu tekan Submit untuk finalisasi.'),
				'blue',
				true,
			);
		}
		// Surface a pending revision request (raised from the PWA) with its reason so
		// Admin Ops sees why the operator wants this EIR reopened.
		if (frm.doc.docstatus === 1 && frm.doc.revision_requested) {
			frm.dashboard.add_comment(
				__('Revisi diminta') + (frm.doc.revision_note ? ': ' + frm.doc.revision_note : ''),
				'orange',
				true,
			);
		}
		// "Cancel" (Desk-only): return a submitted EIR to Draft so it can be edited again
		// in the PWA / Inspection menu.
		// eir.revert_to_draft enforces doc.check_permission("cancel") — un-submitting is
		// cancelling, and §8.1 keeps that away from the field roles.
		if (frm.doc.docstatus === 1 && frappe.perm.has_perm(frm.doctype, 0, 'cancel')) {
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
		install_photo_thumbnails(frm);
		bind_photo_lightbox(frm);
	},

	// Switching type re-skins the form (banner + which sections apply).
	inspection_type(frm) {
		set_direction_banner(frm);
	},

	inspector_signature(frm) {
		set_signature_preview(frm);
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

// An EIR-In and an EIR-Out are two different jobs sharing one doctype, and until you read
// the Tipe field they look identical. Stamp the direction across the top of the form in
// the same colours the list and the gate PWA use — green In (masuk), orange Out (keluar) —
// and say what each is FOR, because that is what actually differs: In records what
// ARRIVED (condition + findings), Out records what LEAVES (photos + seals).
//
// This renders into its own HTML field rather than frm.dashboard.set_headline: the
// headline is a single shared slot (set_headline and add_comment both call
// layout.show_message), so it would silently erase the "Menunggu review" / "Revisi
// diminta" notices below.
function set_direction_banner(frm) {
	const field = frm.get_field('direction_banner');
	if (!field) return;
	const out = frm.doc.inspection_type === 'EIR-Out';
	const inn = frm.doc.inspection_type === 'EIR-In';
	if (!out && !inn) {
		field.$wrapper.empty();
		return;
	}
	const colour = out ? 'orange' : 'green';
	const title = out ? __('EIR OUT — Survey Keluar') : __('EIR IN — Survey Masuk');
	const blurb = out
		? __('Sebelum tank dimuat keluar: foto kondisi dan nomor seal yang terpasang. Tidak ada checklist kerusakan di sini.')
		: __('Saat tank tiba di depo: kondisi tank, checklist kerusakan, dan tindak lanjut (Cleaning / M&R).');
	field.$wrapper.html(
		`<div class="eir-direction-banner" style="display:flex;align-items:flex-start;gap:10px;padding:10px 12px;margin-bottom:8px;
			border-radius:var(--border-radius-md);background:var(--bg-${colour});border-left:4px solid var(--${colour}-500)">
			<div>
				<div><b>${title}</b></div>
				<div class="text-muted small" style="margin-top:2px">${blurb}</div>
			</div>
		</div>`,
	);
}

// Frappe's Attach Image control renders as a file LINK and only reveals the picture in a
// hover popover, so a signed EIR showed "/private/files/eir-signature….png" where the
// signature should be. A signature exists to be looked at — draw it inline, with who
// signed and when, because ink without a name attached says nothing.
function set_signature_preview(frm) {
	const field = frm.get_field('signature_preview');
	if (!field) return;
	const url = frm.doc.inspector_signature;
	if (!url) {
		field.$wrapper.html(
			`<div class="text-muted small">${__('Belum ditandatangani.')}</div>`,
		);
		return;
	}
	const who = frm.doc.inspector || '';
	const when = frm.doc.work_ended_on || frm.doc.eir_date || '';
	const caption = [who, when ? frappe.datetime.str_to_user(when) : '']
		.filter(Boolean)
		.map((t) => frappe.utils.escape_html(String(t)))
		.join(' · ');
	field.$wrapper.html(
		`<div style="padding:8px 10px;border:1px solid var(--border-color);border-radius:var(--border-radius-md);background:#fff">
			<img src="${encodeURI(url)}" alt="${__('Tanda tangan')}"
				style="display:block;max-height:120px;max-width:100%;object-fit:contain"
				onerror="this.style.display='none';this.nextElementSibling.style.display='block'">
			<div class="text-muted small" style="display:none">${__('Berkas tanda tangan tidak bisa dibuka.')}</div>
			${caption ? `<div class="text-muted small" style="margin-top:6px">${caption}</div>` : ''}
		</div>`,
	);
}

// "Kembalikan ke Draft" — revert a submitted EIR to an editable draft. The server guards
// that no other draft exists for the same container before flipping docstatus back to 0
// and undoing the container status/cargo this EIR applied.
function revert_to_draft(frm) {
	frappe.confirm(
		__('Kembalikan EIR ini ke Draft agar bisa diedit lagi? Semua EIR draft untuk container ini harus sudah disubmit.'),
		() => {
			frappe.call({
				method: 'container_depot.container_depot.eir.revert_to_draft',
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

// --- Photo thumbnails in the EIR grids ---
// Frappe renders an Attach Image column as its bare URL inside an <a> (formatters.js:
// AttachImage -> format_attachment_url), so a table of photos reads as a wall of
// /files/... paths and the only way to SEE one is to hover the link for its popover.
// Reviewing an EIR is a scanning job — twenty photos, is this the right tank, is the
// damage really there — so the picture belongs in the row itself.
//
// frappe.format prefers df.formatter over the fieldtype's default, so a formatter on the
// docfield is the hook. Two details decide WHERE it has to go:
//
//   * The Attach Image formatter never calls _apply_custom_formatter, so the
//     frappe.meta.docfield_map route documented in formatters.js does nothing on its own.
//   * Grid rows read their docfields from a PER-DOCNAME copy (grid.js:
//     frappe.meta.get_docfields(child_doctype, frm.docname)), built by copy_dict — which
//     is a shallow copy, so a function set on the standard docfield survives into it.
//
// So: write the standard docfield (every copy made later inherits it) AND the copy this
// form may already hold. Called from setup, before the first render.
//
// (table fieldname on Inspection, child doctype, image fieldname)
const PHOTO_TABLES = [
	['exterior_photos', 'Inspection Photo', 'photo_url'],
	['item_photos', 'Inspection Item Photo', 'photo'],
];

function photo_thumbnail(value) {
	if (!value) return '';
	const src = frappe.utils.escape_html(value);
	// data-oak-photo carries the URL for the lightbox below; the <img> src is the same
	// file, so no second request and no extra thumbnail to generate.
	return `<img class="oak-grid-photo" src="${src}" data-oak-photo="${src}" loading="lazy" alt="">`;
}

function install_photo_thumbnails(frm) {
	PHOTO_TABLES.forEach(([, doctype, fieldname]) => {
		const std = (frappe.meta.docfield_map[doctype] || {})[fieldname];
		if (std) std.formatter = photo_thumbnail;
		if (!frm.docname) return;
		const df = frappe.meta.get_docfield(doctype, fieldname, frm.docname);
		if (df) df.formatter = photo_thumbnail;
	});
}

// Click a filled photo cell -> view it full size. Never edit it.
//
// This has to run in the CAPTURE phase. Frappe binds click-to-edit directly on the cell
// (grid_row.js: $col.on("click", ... toggle_editable_row())), and a delegated jQuery
// handler on the form wrapper is an ANCESTOR — so it fires after the cell's own handler,
// by which point the row is already in edit mode, the thumbnail is hidden and an Attach
// control with the raw URL has taken its place. That is the "photo disappears after I
// click it" bug: nothing was lost, the cell had simply swapped itself for an editor.
// Capturing on the grid wrapper gets there first, and stopPropagation there keeps the
// event from ever reaching the cell.
//
// Only a cell that ALREADY has a photo is intercepted. An empty one still opens the
// normal upload control, so adding a photo works exactly as before — it is only the
// permanent, already-uploaded image that is view-only.
function bind_photo_lightbox(frm) {
	PHOTO_TABLES.forEach(([table_fieldname]) => {
		const grid = frm.fields_dict[table_fieldname] && frm.fields_dict[table_fieldname].grid;
		const el = grid && grid.wrapper && grid.wrapper.get(0);
		// The wrapper is built once and rows re-render inside it, so one listener holds for
		// the life of the grid. The flag stops refreshes from stacking duplicates, which
		// would open one dialog per refresh.
		if (!el || el._oakPhotoBound) return;
		el._oakPhotoBound = true;
		el.addEventListener(
			'click',
			(e) => {
				if (!e.target.closest) return;
				// The large preview inside an opened row: nothing to protect it from, it
				// just zooms.
				const large = e.target.closest('.oak-photo-large img');
				if (large) {
					e.preventDefault();
					show_photo(large.getAttribute('data-oak-photo'));
					return;
				}
				const cell = e.target.closest('.grid-static-col');
				if (!cell) return;
				const img = cell.querySelector('img.oak-grid-photo');
				if (!img) return; // empty cell — let Frappe open the upload control
				e.stopPropagation();
				e.preventDefault();
				show_photo(img.getAttribute('data-oak-photo'));
			},
			true,
		);
	});
}

// The photo, full width, inside the opened row panel.
//
// The Attach control alone gives you a filename and a hover popover — fine for an
// attachment, useless for an inspection record where the picture IS the evidence. The
// grid thumbnail answers "which tank"; this answers "is that dent actually there".
//
// Rendered into a plain HTML docfield rather than injected next to the control, so it
// survives whatever the Attach control does to its own markup between framework versions.
function render_photo_preview(frm, cdt, cdn) {
	const spec = PHOTO_TABLES.find(([, doctype]) => doctype === cdt);
	if (!spec) return;
	const [table_fieldname, , photo_fieldname] = spec;

	const grid = frm.fields_dict[table_fieldname] && frm.fields_dict[table_fieldname].grid;
	const grid_row = grid && grid.grid_rows_by_docname && grid.grid_rows_by_docname[cdn];
	const grid_form = grid_row && grid_row.grid_form;
	const field = grid_form && grid_form.fields_dict.photo_preview;
	if (!field) return;

	// Kill ControlAttachImage's hover popover. The CSS hides its anchor, so it can no
	// longer be triggered, but an instance created before that (or one left open by the
	// mispositioned-anchor bug) has to be disposed or it hangs around over the form.
	const control = grid_form.fields_dict[photo_fieldname];
	const $link = control && control.$value && control.$value.find('.attached-file-link');
	if ($link && $link.length && $link.popover) {
		try {
			$link.popover('dispose');
		} catch (e) {
			// Older bootstrap builds name it 'destroy'; either way a failure here is
			// cosmetic and must not stop the preview below from rendering.
			try {
				$link.popover('destroy');
			} catch (e2) {
				/* no popover attached — nothing to do */
			}
		}
	}

	const url = ((locals[cdt] || {})[cdn] || {})[photo_fieldname];
	if (!url) {
		// A row with no photo yet — say so, rather than leaving a silent gap where a
		// picture should be.
		field.$wrapper.html(`<div class="oak-photo-none">${__('Belum ada foto')}</div>`);
		return;
	}
	const src = frappe.utils.escape_html(url);
	field.$wrapper.html(
		`<div class="oak-photo-large"><img src="${src}" data-oak-photo="${src}" alt=""></div>`,
	);
}

function show_photo(src) {
	if (!src) return;
	const d = new frappe.ui.Dialog({ title: __('Foto'), size: 'large' });
	d.$body.html(
		`<div class="oak-photo-full"><img src="${frappe.utils.escape_html(src)}" alt=""></div>`,
	);
	d.set_secondary_action_label(__('Buka di tab baru'));
	d.set_secondary_action(() => window.open(src, '_blank'));
	d.show();
}

// --- A photo row without a photo is not a row ---
// Both image fields are reqd, so an emptied row could never be saved anyway — Frappe would
// just refuse the save with "Photo is required" and leave the user to work out which of
// forty rows it meant. The record only exists to carry the image, so removing the image
// removes the row. The server enforces the same rule in Inspection.validate for every
// other path in (PWA, API, data import).
function drop_row_without_photo(frm, table_fieldname, photo_fieldname, cdt, cdn) {
	const row = (locals[cdt] || {})[cdn];
	if (!row || row[photo_fieldname]) return; // still has its photo — nothing to do
	const grid = frm.fields_dict[table_fieldname] && frm.fields_dict[table_fieldname].grid;
	const grid_row = grid && grid.grid_rows_by_docname && grid.grid_rows_by_docname[cdn];
	if (!grid_row) return;
	grid_row.remove();
	frappe.show_alert({
		message: __('Baris foto dihapus — foto tidak bisa dikosongkan.'),
		indicator: 'orange',
	});
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
// `form_render` belongs on the CHILD doctype, not on Inspection. grid_row.show_form calls
// script_manager.trigger("form_render", child_doctype, row_name), and get_handlers looks
// the event up under THAT doctype (frappe.ui.form.handlers[doctype][event_name]) — a
// handler registered on the parent is never reached.
frappe.ui.form.on('Inspection Photo', {
	form_render(frm, cdt, cdn) {
		render_photo_preview(frm, cdt, cdn);
	},

	photo_url(frm, cdt, cdn) {
		drop_row_without_photo(frm, 'exterior_photos', 'photo_url', cdt, cdn);
	},
});

frappe.ui.form.on('Inspection Item Photo', {
	form_render(frm, cdt, cdn) {
		render_photo_preview(frm, cdt, cdn);
	},

	photo(frm, cdt, cdn) {
		drop_row_without_photo(frm, 'item_photos', 'photo', cdt, cdn);
	},

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
// (container_depot.ess.inspections.eir_prefill -> container_depot.eir.prefill). There is
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
