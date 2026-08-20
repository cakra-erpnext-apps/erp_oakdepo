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
		install_damage_thumbnails(frm);
	},

	refresh(frm) {
		set_signature_preview(frm);
		render_system_facts(frm);
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
		// "Search by section" for sorting bulk ("foto cepat") photos: quick-filter the
		// item_photos grid by Area — including a "Belum disortir" bucket for the photos the
		// operator dumped without a section. Works on submitted EIRs (item_photos is
		// allow_on_submit) so the admin can sort after the fact.
		if (!frm.is_new() && (frm.doc.item_photos || []).length) {
			frm.add_custom_button(__('Filter Foto per Section'), () => filter_photos_by_section(frm));
		}
		// Clicking a row opens the same modal at that photo, but only once you know that —
		// and a reviewer arriving at a submitted EIR is here to page through the photos,
		// not to hunt for the way in.
		if (!frm.is_new() && photo_slides(frm).length) {
			frm.add_custom_button(__('Lihat Semua Foto'), () => open_photo_carousel(frm, photo_slides(frm), 0));
		}
		install_photo_thumbnails(frm);
		bind_photo_grid_clicks(frm);
		bind_damage_grid_clicks(frm);
		hide_sidebar_attachments(frm);
		sync_followup_flags(frm, false);
	},

	// Frappe checks reqd fields in the BROWSER before the request ever leaves (form.js
	// save() -> validate/before_save -> frappe.ui.form.check_mandatory), so
	// Inspection.drop_empty_photo_rows on the server never gets a chance at a photo row
	// somebody added in the grid and never filled: the save bounces with "Mandatory fields
	// required in table Foto per Item, Row 1 - Photo" — pointing at a table the user may
	// not even have been working in (typically they were filling Checklist Kerusakan).
	// Adding an empty row and uploading into it from the modal is a supported flow, so the
	// row must be allowed to exist; it just must not survive the save.
	validate(frm) {
		drop_empty_photo_rows(frm);
	},

	inspector_signature(frm) {
		set_signature_preview(frm);
	},

	// The EIR inspects a physical container, so picking the Container prefills the
	// header from the SAME whitelisted function the PWA uses (see
	// prefill_from_container) — one prefill implementation, keyed on the container.
	container(frm) {
		if (frm.doc.container) prefill_from_container(frm);
	},

	// The "Tindak Lanjut" boxes follow the evidence — see sync_followup_flags.
	inspection_type(frm) {
		sync_followup_flags(frm, true);
	},

	tank_status(frm) {
		sync_followup_flags(frm, true);
	},

	damage_log_add(frm) {
		sync_followup_flags(frm, true);
	},

	damage_log_remove(frm) {
		sync_followup_flags(frm, true);
	},
});

// --- Tindak Lanjut: the boxes may only promise work that submit will really file --------
// Both checkboxes are opt-OUTs — on_submit skips the follow-up when unticked — and both
// creations no-op when their condition is not met. Left ticked by default (they used to be)
// they announced a Cleaning Order for a clean tank and an M&R for an undamaged one, and the
// user went off waiting for a job nobody would ever see. So the box now tracks the tank in
// front of the surveyor: ticked the moment the status turns Empty Dirty or a finding lands
// on the Checklist Kerusakan, cleared and locked (with the reason written on the field)
// while the follow-up is not due.
//
// Ticking happens only on the TRANSITION into "due", never on a plain refresh: an operator
// who unticks a box that is legitimately due means it, and re-rendering the form must not
// argue with them. Inspection.sync_followup_flags applies the SAME rule on every save —
// that copy is what covers the PWA and the API, this one is so the person filling the form
// watches the box follow the tank instead of finding out at submit. Keep the two in sync,
// along with eir_followups.damage_row_needs_mr, the M&R test in Python.
const EMPTY_DIRTY = 'Empty Dirty';
const ACCEPTABLE_DAMAGE_CODE = 'v';
const NO_ACTION_REPAIR_CODE = 'X';

function damage_row_needs_mr(row) {
	const real_damage = row.damage_type && row.damage_type !== ACCEPTABLE_DAMAGE_CODE;
	const real_repair = row.repair_code && row.repair_code !== NO_ACTION_REPAIR_CODE;
	const noted = !!(row.damage_description || '').trim();
	const uncoded = !row.damage_type && !row.repair_code;
	return !!(real_damage || real_repair || noted || uncoded);
}

function sync_followup_flags(frm, on_change) {
	const eir_in = frm.doc.inspection_type === 'EIR-In';
	apply_followup_flag(frm, 'create_cleaning_order', eir_in && frm.doc.tank_status === EMPTY_DIRTY, on_change, {
		due: __('Tank Empty Dirty — Cleaning Order dibuat saat submit. Hilangkan centang untuk melewati.'),
		not_due: __('Tidak berlaku: Cleaning Order hanya dibuat untuk tank Empty Dirty.'),
	});
	apply_followup_flag(
		frm,
		'create_repair_order',
		eir_in && (frm.doc.damage_log || []).some(damage_row_needs_mr),
		on_change,
		{
			due: __('Ada temuan kerusakan — draft M&R dibuat saat submit. Hilangkan centang untuk melewati.'),
			not_due: __('Tidak berlaku: belum ada temuan di Checklist Kerusakan.'),
		},
	);
}

function apply_followup_flag(frm, fieldname, due, on_change, hints) {
	// The reason reads on a submitted EIR too — that is where somebody comes looking for the
	// Cleaning Order / M&R that never appeared.
	frm.set_df_property(fieldname, 'description', due ? hints.due : hints.not_due);
	frm.set_df_property(fieldname, 'read_only', due ? 0 : 1);
	const was = (frm.__followup_due || {})[fieldname];
	frm.__followup_due = Object.assign({}, frm.__followup_due, { [fieldname]: due });
	if (frm.doc.docstatus !== 0) return; // submitted: what happened, happened
	if (!due) {
		if (frm.doc[fieldname]) frm.set_value(fieldname, 0);
		return;
	}
	// `was === false` — the follow-up just BECAME due. `undefined` is the first render of a
	// form that was already due, where the stored answer is the operator's and stands.
	if (on_change && was === false) frm.set_value(fieldname, 1);
}

// Frappe's Attach Image control renders as a file LINK and only reveals the picture in a
// hover popover, so a signed EIR showed "/private/files/eir-signature….png" where the
// signature should be. A signature exists to be looked at — draw it inline, with who
// signed and when, because ink without a name attached says nothing.
// Semua yang diisi sistem sendiri — kode EIR, status, dokumen asalnya, spesifikasi tank
// yang disalin dari master Container — tinggal di SIDEBAR, di atas Last Edited By, bukan
// di tab "Sistem" berisi puluhan field read-only yang terbaca seperti pekerjaan yang belum
// dikerjakan. Blok yang sama dipakai Container Booking / Order Bongkar / Order Muat
// (container_depot/public/js/system_facts.js), jadi ketiga form tampil identik.
//
// Field-nya tetap ada di doctype (hidden): list view, filter, print format dan server masih
// membacanya — ini cuma soal di mana manusia melihatnya.
function render_system_facts(frm) {
	const link = container_depot.doc_link;
	const esc = frappe.utils.escape_html;
	const doc = frm.doc;
	const join = (parts) => parts.filter(Boolean).join(' \u00b7 ');
	// Tiga fakta truk jadi satu baris; sendiri-sendiri mereka memenuhi sidebar tanpa isi.
	const truck = join([doc.truck_no, doc.driver, doc.driver_phone].filter(Boolean).map(esc));
	const spec = join([
		doc.capacity && __('{0} L', [format_number(doc.capacity)]),
		doc.tare_weight && __('Tare {0} kg', [format_number(doc.tare_weight)]),
		doc.max_gross_weight && __('MGW {0} kg', [format_number(doc.max_gross_weight)]),
	]);
	const tank_dates = join([
		doc.manufacture_date && __('Dibuat {0}', [frappe.datetime.str_to_user(doc.manufacture_date)]),
		doc.last_test_date && __('Tes {0}', [frappe.datetime.str_to_user(doc.last_test_date)]),
	]);
	const work = join([
		doc.work_started_on && frappe.datetime.str_to_user(doc.work_started_on),
		doc.work_ended_on && frappe.datetime.str_to_user(doc.work_ended_on),
	]);
	container_depot.render_system_facts(frm, [
		[__('Kode EIR'), doc.inspection_id && esc(doc.inspection_id)],
		[__('Status'), doc.status && esc(doc.status)],
		[__('EIR-Out Outcome'), doc.out_outcome && esc(doc.out_outcome)],
		// Cermin nomor container: hanya berarti kalau beda dari link Container (data lama).
		[__('Container Number'), doc.container_no !== doc.container && esc(doc.container_no || '')],
		[__('Owner (Principal)'), link('Customer', doc.container_principal)],
		[__('Container Booking'), link('Container Booking', doc.container_booking)],
		[__('Bon'), doc.order_doctype && link(doc.order_doctype, doc.order_ref)],
		[__('Reference EIR-In'), link('Inspection', doc.reference_eir_in)],
		[__('Shipper / EMKL'), link('Customer', doc.shipper)],
		[__('Truk / Supir'), truck],
		[__('Ex Vessel'), doc.ex_vessel && esc(doc.ex_vessel)],
		[__('Last Cargo'), link('Cargo', doc.last_cargo)],
		[__('Serial No'), doc.serial_no && esc(doc.serial_no)],
		[__('Spesifikasi Tank'), spec],
		[__('Tanggal Tank'), tank_dates],
		[__('Waktu Pengerjaan'), work],
		[__('Durasi Pengerjaan'), doc.work_duration && frappe.format(doc.work_duration, { fieldtype: 'Duration' })],
		[__('Foto Belum Disortir'), doc.has_unsorted_photos ? __('Ada') : null],
	]);
}

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
	// Evidence for a damage finding, kept out of the inspection album. No row editor: these
	// rows are never "belum disortir" — the finding they belong to is the whole point — so a
	// filled cell just opens the picture, same as the legacy exterior table.
	['damage_photos', 'Inspection Damage Photo', 'photo'],
];

// The sidebar's Attachments list is dropped from this form. Every EIR photo is already an
// attachment, so the list is a second, unsorted copy of the grids above — dozens of rows
// deep on a real inspection — and its "+" files a picture into the document without ever
// saying which part it documents, which is the one thing an EIR photo has to say. Photos go
// in through Foto per Item or a finding's own strip.
//
// Hidden by CSS class, not by hiding the element: frappe.ui.form.Attachments.refresh() calls
// parent.toggle(true) on every form refresh, and an inline display would win back.
function hide_sidebar_attachments(frm) {
	const parent = frm.attachments && frm.attachments.parent;
	if (parent && parent.length) parent.addClass('oak-no-attachments');
}

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

// Click a row -> open it in the modal editor. Click a photo cell -> the same modal, at
// that photo.
//
// The grid is a list to SCAN, not a form to fill in: an item photo carries one editable
// field (which checklist item it documents) and a picture you cannot judge at thumbnail
// size, so editing in place meant opening a row, squinting, closing it, opening the next.
// The modal shows the picture at working size with the field beside it and steps to the
// next row without closing — the "sort forty bulk photos" job in one pass.
//
// This has to run in the CAPTURE phase. Frappe binds click-to-edit directly on the cell
// (grid_row.js: $col.on("click", ... toggle_editable_row())) and on .row-index /
// .btn-open-row (toggle_view -> the inline row form), and a delegated jQuery handler on
// the form wrapper is an ANCESTOR — so it fires after those, by which point the inline
// form is already open underneath our dialog. Capturing on the grid wrapper gets there
// first, and stopPropagation keeps the event from ever reaching the row.
//
// exterior_photos is the retired legacy table (hidden on the form, still fed by the
// upload API): it has no editable field worth a modal, so a filled cell there just opens
// the read-only viewer, exactly as before.
function bind_photo_grid_clicks(frm) {
	PHOTO_TABLES.forEach(([table_fieldname, doctype]) => {
		const grid = frm.fields_dict[table_fieldname] && frm.fields_dict[table_fieldname].grid;
		const el = grid && grid.wrapper && grid.wrapper.get(0);
		// The wrapper is built once and rows re-render inside it, so one listener holds for
		// the life of the grid. The flag stops refreshes from stacking duplicates, which
		// would open one dialog per refresh.
		if (!el || el._oakPhotoBound) return;
		el._oakPhotoBound = true;
		const rows_open_editor = doctype === 'Inspection Item Photo';
		el.addEventListener(
			'click',
			(e) => {
				if (!e.target.closest) return;
				// The large preview inside an opened row: nothing to protect it from, it
				// just zooms.
				const large = e.target.closest('.oak-photo-large img');
				if (large) {
					e.preventDefault();
					show_photo(large.getAttribute('data-oak-photo'), frm);
					return;
				}
				if (rows_open_editor) {
					// Only a real data row. The heading and search rows are .grid-row too,
					// but carry no data-name; the checkbox and the sort handle keep their
					// own jobs.
					const row = e.target.closest('.grid-row[data-name]');
					if (!row || e.target.closest('.grid-row-check')) return;
					if (!e.target.closest('.grid-static-col, .btn-open-row')) return;
					e.stopPropagation();
					e.preventDefault();
					open_item_photo_editor(frm, row.getAttribute('data-name'));
					return;
				}
				const cell = e.target.closest('.grid-static-col');
				if (!cell) return;
				const img = cell.querySelector('img.oak-grid-photo');
				if (!img) return; // empty cell — let Frappe open the upload control
				e.stopPropagation();
				e.preventDefault();
				show_photo(img.getAttribute('data-oak-photo'), frm);
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

// Photos of ONE finding, rendered into the row's `photos_html` field: a strip of
// thumbnails, each removable, plus an add button. Click a thumbnail for the big view.
//
// Editable only while the EIR is a draft the user may write to: the rows live in
// `damage_photos`, whose field is not allow_on_submit, so a submitted EIR shows the strip
// read-only rather than offering buttons that would bounce on save.
function damage_photo_rows(frm, item_code) {
	return (frm.doc.damage_photos || []).filter((p) => p.checklist_item === item_code);
}

function render_damage_photos(frm, cdt, cdn) {
	const grid = frm.fields_dict.damage_log && frm.fields_dict.damage_log.grid;
	const grid_row = grid && grid.grid_rows_by_docname && grid.grid_rows_by_docname[cdn];
	const field = grid_row && grid_row.grid_form && grid_row.grid_form.fields_dict.photos_html;
	if (!field) return;

	const row = (locals[cdt] || {})[cdn] || {};
	const item_code = row.checklist_item;
	const may_edit = frm.doc.docstatus === 0 && frappe.perm.has_perm(frm.doctype, 0, 'write');

	if (!item_code) {
		field.$wrapper.html(`<div class="oak-photo-none">${__('Pilih Checklist Item dulu.')}</div>`);
		return;
	}

	const photos = damage_photo_rows(frm, item_code);
	const thumbs = photos
		.map((p) => {
			const src = frappe.utils.escape_html(p.photo || '');
			if (!src) return '';
			return `<div class="oak-damage-photo">
				<img src="${src}" data-oak-photo="${src}" alt="">
				${may_edit ? `<button type="button" class="oak-damage-photo-x" data-oak-drop="${frappe.utils.escape_html(p.name)}">&times;</button>` : ''}
			</div>`;
		})
		.join('');

	field.$wrapper.html(
		`<div class="oak-damage-photos">
			${thumbs || `<div class="oak-photo-none">${__('Belum ada foto')}</div>`}
			${may_edit ? `<button type="button" class="btn btn-xs btn-default oak-damage-photo-add">${__('Tambah Foto')}</button>` : ''}
		</div>`,
	);

	field.$wrapper.find('img[data-oak-photo]').on('click', (e) => {
		show_photo(e.currentTarget.getAttribute('data-oak-photo'), frm);
	});
	field.$wrapper.find('[data-oak-drop]').on('click', (e) => {
		const name = e.currentTarget.getAttribute('data-oak-drop');
		frm.doc.damage_photos = (frm.doc.damage_photos || []).filter((p) => p.name !== name);
		frm.refresh_field('damage_photos');
		frm.dirty();
		render_damage_photos(frm, cdt, cdn);
	});
	field.$wrapper.find('.oak-damage-photo-add').on('click', () => {
		add_damage_photo(frm, row, () => render_damage_photos(frm, cdt, cdn));
	});
}

// --- Checklist Kerusakan, built like Foto per Item ---------------------------------
//
// Same bargain as the photo grid: the grid is a list to SCAN — part, codes, a thumbnail —
// and the work happens in a modal that shows the picture at working size with the fields
// beside it and steps to the next FINDING without closing. Filling a finding in place meant
// squinting at a Small Text column and never seeing the photo it is about.

// The Photo column of the damage grid. The pictures live in the Inspection's damage_photos
// table (a child doctype cannot own a child table), so the value of this column is nothing
// and the formatter renders from the open form instead — `cur_frm`, because a grid formatter
// is handed the child row and never the parent.
function damage_thumbnail(value, df, options, doc) {
	const frm = cur_frm;
	if (!frm || !doc || !doc.checklist_item) return '';
	const photos = damage_photo_rows(frm, doc.checklist_item).filter((p) => p.photo);
	if (!photos.length) return '';
	const src = frappe.utils.escape_html(photos[0].photo);
	const more = photos.length > 1 ? `<span class="oak-damage-more">+${photos.length - 1}</span>` : '';
	return `<span class="oak-damage-thumb"><img class="oak-grid-photo" src="${src}" data-oak-photo="${src}" loading="lazy" alt="">${more}</span>`;
}

function install_damage_thumbnails(frm) {
	const std = (frappe.meta.docfield_map['Inspection Damage Entry'] || {}).photos_preview;
	if (std) std.formatter = damage_thumbnail;
	if (!frm.docname) return;
	const df = frappe.meta.get_docfield('Inspection Damage Entry', 'photos_preview', frm.docname);
	if (df) df.formatter = damage_thumbnail;
}

// Capture phase, same reason as bind_photo_grid_clicks: Frappe's own cell handler opens the
// inline row form underneath the dialog otherwise.
function bind_damage_grid_clicks(frm) {
	const grid = frm.fields_dict.damage_log && frm.fields_dict.damage_log.grid;
	const el = grid && grid.wrapper && grid.wrapper.get(0);
	if (!el || el._oakDamageBound) return;
	el._oakDamageBound = true;
	el.addEventListener(
		'click',
		(e) => {
			if (!e.target.closest) return;
			const row = e.target.closest('.grid-row[data-name]');
			if (!row || e.target.closest('.grid-row-check')) return;
			if (!e.target.closest('.grid-static-col, .btn-open-row')) return;
			e.stopPropagation();
			e.preventDefault();
			open_damage_editor(frm, row.getAttribute('data-name'));
		},
		true,
	);
}

function damage_findings(frm) {
	const grid = frm.fields_dict.damage_log && frm.fields_dict.damage_log.grid;
	const by_docname = (grid && grid.grid_rows_by_docname) || {};
	return (frm.doc.damage_log || [])
		.filter((r) => {
			const gr = by_docname[r.name];
			return !gr || !gr.wrapper || !gr.wrapper.hasClass('hidden');
		})
		.map((r) => r.name);
}

// One finding at a time: its photos on the stage, its fields beneath, and ‹ / › walking the
// EIR's evidence photo by photo — into the next finding once the current one runs out.
// Editing is a draft-only affair — damage_log is not allow_on_submit — so a submitted EIR
// opens the same modal read-only.
function open_damage_editor(frm, cdn) {
	const rows = damage_findings(frm);
	if (!rows.length) return;
	const editable = frm.doc.docstatus === 0 && frappe.perm.has_perm(frm.doctype, 0, 'write');
	let syncing = false;

	// One slide per PHOTO, walked in finding order — the arrows are the only way through the
	// EIR's evidence, so they must never sit dead on a finding that happens to carry three
	// pictures. A finding with no photo yet still gets one slide: it is a row that needs
	// filling, and skipping it would hide it. The strip below the stage jumps within the
	// current finding; the arrows just keep going and cross into the next one.
	function build_slides() {
		const out = [];
		rows.forEach((name) => {
			const row = (locals['Inspection Damage Entry'] || {})[name] || {};
			const photos = damage_photo_rows(frm, row.checklist_item).filter((p) => p.photo);
			if (!photos.length) {
				out.push({ cdn: name, src: '', photo: '', pos: 0, count: 0 });
				return;
			}
			photos.forEach((p, i) =>
				out.push({ cdn: name, src: p.photo, photo: p.name, pos: i, count: photos.length }),
			);
		});
		return out;
	}

	let slides = build_slides();
	let idx = Math.max(0, slides.findIndex((s) => s.cdn === cdn));

	// Photos come and go while the dialog is open. Rebuild the walk and stay on the same
	// picture — or, when that picture was just deleted, on its finding.
	function resync(prefer) {
		const want = prefer || slides[idx] || {};
		slides = build_slides();
		if (!slides.length) return;
		let at = slides.findIndex((s) => s.photo && s.photo === want.photo);
		if (at < 0) at = slides.findIndex((s) => s.cdn === want.cdn);
		idx = Math.max(0, at);
	}

	const row_of = () => (locals['Inspection Damage Entry'] || {})[(slides[idx] || {}).cdn] || {};

	const field = (fieldname, fieldtype, label, extra) =>
		Object.assign(
			{
				fieldname,
				fieldtype,
				label: __(label),
				read_only: editable ? 0 : 1,
				onchange() {
					if (syncing) return;
					const row = row_of();
					const value = d.get_value(fieldname);
					if (!row.name || (value || '') === (row[fieldname] || '')) return;
					const was = row.checklist_item;
					frappe.model.set_value('Inspection Damage Entry', row.name, fieldname, value);
					if (fieldname === 'checklist_item') {
						// The photos are keyed by checklist item, so re-pointing the finding
						// has to take them along — otherwise they belong to a part this EIR
						// no longer reports on and vanish from the form.
						(frm.doc.damage_photos || []).forEach((p) => {
							if (p.checklist_item === was) p.checklist_item = value;
						});
						fill_damage_from_checklist_item(row.name).then(() => {
							frm.refresh_field('damage_log');
							resync();
							render();
						});
					} else {
						frm.refresh_field('damage_log');
					}
				},
			},
			extra || {},
		);

	// The picture gets the full width at the top — it is what the reviewer came to look
	// at — and the fields sit underneath in two columns. Severity is not asked: nobody
	// fills it in the yard, and the server defaults it to Minor.
	const d = new frappe.ui.Dialog({
		title: __('Checklist Kerusakan'),
		size: 'large',
		fields: [
			{ fieldname: 'viewer', fieldtype: 'HTML' },
			{ fieldname: 'sec_fields', fieldtype: 'Section Break' },
			field('checklist_item', 'Link', 'Checklist Item', {
				options: 'Inspection Checklist Item',
				get_query: () => ({ filters: { is_active: 1 } }),
			}),
			field('damage_type', 'Link', 'Damage Code', { options: 'Inspection Damage Code' }),
			{ fieldname: 'col', fieldtype: 'Column Break' },
			field('repair_code', 'Link', 'Repair Code', { options: 'Inspection Repair Code' }),
			field('damage_description', 'Small Text', 'Description'),
		],
	});

	if (editable) {
		d.set_primary_action(__('Simpan'), () => {
			d.hide();
			drop_empty_photo_rows(frm);
			if (frm.is_dirty()) frm.save();
		});
	}

	function render() {
		const slide = slides[idx] || {};
		const row = row_of();
		const photos = damage_photo_rows(frm, row.checklist_item).filter((p) => p.photo);
		const src = slide.src ? frappe.utils.escape_html(slide.src) : '';
		const stage = src
			? `<div class="oak-carousel-stage"><img src="${src}" alt=""></div>`
			: `<div class="oak-carousel-stage oak-carousel-empty">
					<div class="oak-photo-none">${__('Belum ada foto')}</div>
				</div>`;
		const strip = photos
			.map((p) => {
				const psrc = frappe.utils.escape_html(p.photo);
				const on = p.name === slide.photo ? 'is-on' : '';
				return `<div class="oak-damage-photo ${on}">
					<img src="${psrc}" data-oak-pick="${frappe.utils.escape_html(p.name)}" alt="">
					${editable ? `<button type="button" class="oak-damage-photo-x" data-oak-drop="${frappe.utils.escape_html(p.name)}">&times;</button>` : ''}
				</div>`;
			})
			.join('');

		d.fields_dict.viewer.$wrapper.html(`
			<div class="oak-carousel">
				<button class="btn btn-default oak-carousel-nav" data-oak-step="-1"
					title="${__('Sebelumnya')}" ${idx === 0 ? 'disabled' : ''}>&lsaquo;</button>
				${stage}
				<button class="btn btn-default oak-carousel-nav" data-oak-step="1"
					title="${__('Berikutnya')}" ${idx === slides.length - 1 ? 'disabled' : ''}>&rsaquo;</button>
			</div>
			<div class="oak-carousel-caption">
				<span class="oak-carousel-count">${idx + 1} / ${slides.length}</span>
				${row.area ? `<span class="oak-carousel-area">${frappe.utils.escape_html(row.area)}</span>` : ''}
				<span>${frappe.utils.escape_html(row.component || row.checklist_item || '')}</span>
				${slide.count > 1 ? `<span class="text-muted">${__('foto')} ${slide.pos + 1}/${slide.count}</span>` : ''}
			</div>
			<div class="oak-damage-photos">
				${strip}
				${editable ? `<button type="button" class="btn btn-xs btn-default oak-damage-photo-add">${__('Tambah Foto')}</button>` : ''}
			</div>
		`);

		d.$wrapper.find('.oak-carousel-nav').on('click', (e) => go(cint($(e.currentTarget).attr('data-oak-step'))));
		d.$wrapper.find('[data-oak-pick]').on('click', (e) => {
			const name = e.currentTarget.getAttribute('data-oak-pick');
			const at = slides.findIndex((s) => s.photo === name);
			if (at >= 0) idx = at;
			render();
		});
		d.$wrapper.find('[data-oak-drop]').on('click', (e) => {
			const name = e.currentTarget.getAttribute('data-oak-drop');
			frm.doc.damage_photos = (frm.doc.damage_photos || []).filter((p) => p.name !== name);
			frm.refresh_field('damage_log');
			frm.dirty();
			resync({ cdn: slide.cdn });
			render();
		});
		d.$wrapper.find('.oak-damage-photo-add').on('click', () =>
			add_damage_photo(frm, row, (added) => {
				resync({ cdn: slide.cdn, photo: added && added.name });
				render();
			}),
		);

		syncing = true;
		['checklist_item', 'damage_type', 'repair_code', 'damage_description'].forEach((f) =>
			d.set_value(f, row[f] || ''),
		);
		syncing = false;

		const $open_tab = d.get_secondary_btn();
		d.set_secondary_action_label(__('Detail Foto'));
		d.set_secondary_action(() => slide.src && window.open(slide.src, '_blank'));
		$open_tab.toggleClass('hide', !slide.src);
	}

	function go(step) {
		const next = idx + step;
		if (next < 0 || next >= slides.length) return;
		idx = next;
		render();
	}

	d.$wrapper.on('keydown', (e) => {
		if ($(e.target).is('input, textarea, select')) return;
		if (e.key === 'ArrowLeft') go(-1);
		else if (e.key === 'ArrowRight') go(1);
	});

	render();
	d.show();
}


// Component / Area come off the chosen checklist item — the same fill the grid trigger does,
// so a finding edited in the modal can never read differently from one edited in the grid.
function fill_damage_from_checklist_item(cdn) {
	const row = (locals['Inspection Damage Entry'] || {})[cdn];
	if (!row || !row.checklist_item) return Promise.resolve();
	return frappe.db
		.get_value('Inspection Checklist Item', row.checklist_item, ['printed_no', 'item_name', 'area'])
		.then((r) => {
			const ci = r.message || {};
			frappe.model.set_value('Inspection Damage Entry', cdn, 'component', `${ci.printed_no}. ${ci.item_name}`);
			frappe.model.set_value('Inspection Damage Entry', cdn, 'area', ci.area);
		});
}

// Upload one or more photos onto a finding. `doctype`/`docname` keep the File attached to
// this EIR: a private file with no owner document is readable only by whoever uploaded it,
// and the next reviewer would get a broken image.
function add_damage_photo(frm, row, done) {
	if (!row || !row.checklist_item) {
		frappe.msgprint(__('Pilih Checklist Item dulu.'));
		return;
	}
	new frappe.ui.FileUploader({
		doctype: frm.doctype,
		docname: frm.docname,
		allow_multiple: true,
		restrictions: { allowed_file_types: ['image/*'] },
		on_success(file_doc) {
			const added = frm.add_child('damage_photos', {
				checklist_item: row.checklist_item,
				photo: file_doc.file_url,
			});
			added.area = row.area;
			frm.refresh_field('damage_log');
			frm.dirty();
			if (done) done(added);
		},
	});
}

// --- The carousel ---
//
// Reviewing an EIR means looking at every photo in turn — twenty shots of one tank, is the
// damage there, is anything missing. Opening a dialog per photo made that twenty
// open-look-close cycles, so the viewer holds the whole set and moves between them.
//
// It also carries the ONE edit a reviewer makes while looking: which checklist item a
// photo belongs to. The PWA lets a surveyor dump "foto cepat" without picking a section,
// and somebody has to sort them afterwards — a job that is only possible while you can see
// the photo. Doing it in the grid meant opening a row, reading a filename, guessing. Here
// the picture and the picker are on screen together.
//
// Both photo tables feed one list, in form order: a reviewer wants the exterior shots and
// the item shots as one pass, not two. Only item rows carry a checklist item, so the picker
// hides itself on an exterior slide rather than offering an edit that would go nowhere.

function photo_slides(frm) {
	const out = [];
	(frm.doc.exterior_photos || []).forEach((row) => {
		if (row.photo_url) {
			out.push({
				src: row.photo_url,
				cdt: 'Inspection Photo',
				cdn: row.name,
				kind: 'exterior',
				label: row.photo_view || __('Foto luar'),
			});
		}
	});
	(frm.doc.item_photos || []).forEach((row) => {
		if (row.photo) {
			out.push({
				src: row.photo,
				cdt: 'Inspection Item Photo',
				cdn: row.name,
				kind: 'item',
				label: row.item_name || __('(Belum disortir)'),
			});
		}
	});
	(frm.doc.damage_photos || []).forEach((row) => {
		if (row.photo) {
			out.push({
				src: row.photo,
				cdt: 'Inspection Damage Photo',
				cdn: row.name,
				kind: 'damage',
				label: `${__('Kerusakan')}: ${row.item_name || row.checklist_item || ''}`,
			});
		}
	});
	return out;
}

// Row-click entry point: EVERY item_photos row, in the order the grid is showing them —
// including the rows whose photo is still missing, because those are exactly the ones that
// need filling. photo_slides above answers "show me the pictures"; this one answers "walk
// me through the rows".
function item_photo_slides(frm) {
	const grid = frm.fields_dict.item_photos && frm.fields_dict.item_photos.grid;
	const by_docname = (grid && grid.grid_rows_by_docname) || {};
	return (frm.doc.item_photos || [])
		// Rows hidden by "Filter Foto per Section" drop out, so next/prev walks the
		// filtered set the admin is actually working through. The filter hides with an
		// inline display:none, which is why the test reads the inline style: a row sitting
		// on another page of the grid is simply not rendered and must stay in the list.
		.filter((row) => {
			const gr = by_docname[row.name];
			const el = gr && gr.wrapper && gr.wrapper.get(0);
			return !(el && el.style.display === 'none');
		})
		.map((row) => ({
			src: row.photo || '',
			cdt: 'Inspection Item Photo',
			cdn: row.name,
			kind: 'item',
			label: row.item_name || __('(Belum disortir)'),
		}));
}

function open_item_photo_editor(frm, cdn) {
	const slides = item_photo_slides(frm);
	const start = Math.max(0, slides.findIndex((s) => s.cdn === cdn));
	open_photo_carousel(frm, slides, start);
}

// Assigning a checklist item is only an edit of item_photos, which is allow_on_submit — so
// it stays available on a submitted EIR, which is exactly when the sorting usually happens.
// A cancelled EIR is a closed record, and a reader without write permission gets the viewer
// without the picker.
function may_sort_photos(frm) {
	return frm.doc.docstatus !== 2 && frappe.perm.has_perm(frm.doctype, 0, 'write');
}

// Section + item name come off the chosen checklist item. Shared with the grid's own
// trigger so the two can never fill a row differently.
function fill_from_checklist_item(cdt, cdn) {
	const row = (locals[cdt] || {})[cdn];
	if (!row || !row.checklist_item) return Promise.resolve();
	return frappe.db
		.get_value('Inspection Checklist Item', row.checklist_item, ['item_name', 'area'])
		.then((r) => {
			const ci = r.message || {};
			frappe.model.set_value(cdt, cdn, 'area', ci.area);
			frappe.model.set_value(cdt, cdn, 'item_name', ci.item_name);
		});
}

function show_photo(src, frm) {
	if (!src) return;
	// Called from a click on one photo: that photo is where the carousel opens, the rest is
	// what it can reach. Matched by URL because the click arrives as an <img>, not a row —
	// and two rows holding the same file are the same picture anyway.
	const slides = frm ? photo_slides(frm) : [];
	const start = Math.max(0, slides.findIndex((s) => s.src === src));
	if (!slides.length) return open_photo_carousel(frm, [{ src, kind: 'exterior', label: '' }], 0);
	open_photo_carousel(frm, slides, start);
}

function open_photo_carousel(frm, slides, start) {
	if (!slides || !slides.length) {
		frappe.msgprint(__('Belum ada foto di EIR ini.'));
		return;
	}
	let idx = Math.min(Math.max(start || 0, 0), slides.length - 1);
	const sortable = frm && may_sort_photos(frm);
	// Guards the controls' own change handlers while the carousel writes into them on every
	// slide change — without it, moving to the next photo would "assign" the previous
	// photo's item to the new row. The handlers re-check the row's stored value as well, so
	// a change event that lands after the flag has cleared is still a no-op.
	let syncing = false;

	const d = new frappe.ui.Dialog({
		title: __('Foto Inspeksi'),
		size: 'large',
		fields: [
			{ fieldname: 'viewer', fieldtype: 'HTML' },
			{
				fieldname: 'checklist_item',
				fieldtype: 'Link',
				label: __('Checklist Item'),
				options: 'Inspection Checklist Item',
				// Only the items still in use — a retired one would file the photo under a
				// section nothing else reports on.
				get_query: () => ({ filters: { is_active: 1 } }),
				read_only: sortable ? 0 : 1,
				onchange() {
					if (syncing) return;
					const slide = slides[idx];
					if (!slide || slide.kind !== 'item') return;
					const row = (locals[slide.cdt] || {})[slide.cdn] || {};
					const value = d.get_value('checklist_item') || '';
					if (value === (row.checklist_item || '')) return;
					frappe.model.set_value(slide.cdt, slide.cdn, 'checklist_item', value);
					fill_from_checklist_item(slide.cdt, slide.cdn).then(() => {
						const fresh = (locals[slide.cdt] || {})[slide.cdn] || {};
						slide.label = fresh.item_name || __('(Belum disortir)');
						frm.refresh_field('item_photos');
						render();
					});
				},
			},
			{
				fieldname: 'photo',
				fieldtype: 'Attach Image',
				label: __('Foto'),
				// `options` on an Attach control is not a link target — ControlAttach merges
				// it into its FileUploader config (set_upload_options). Naming the parent doc
				// here is what keeps the uploaded File attached to this EIR: a dialog control
				// has no `frm` to infer it from, and a private file with no attached_to is
				// readable only by whoever uploaded it — the next reviewer would get a broken
				// image. (Passing `frm` to the Dialog instead would make the control write the
				// URL onto Inspection itself and save the form; it must not.)
				options: {
					doctype: frm && frm.doctype,
					docname: frm && frm.docname,
					fieldname: 'item_photos',
					restrictions: { allowed_file_types: ['image/*'] },
				},
				onchange() {
					if (syncing) return;
					const slide = slides[idx];
					if (!slide || slide.kind !== 'item') return;
					const url = d.get_value('photo') || '';
					const row = (locals[slide.cdt] || {})[slide.cdn] || {};
					if (!url || url === (row.photo || '')) return;
					frappe.model.set_value(slide.cdt, slide.cdn, 'photo', url).then(() => {
						slide.src = url;
						frm.refresh_field('item_photos');
						render();
					});
				},
			},
		],
	});

	// Saving is the reviewer's own step, not something a slide change does behind their
	// back: paging through forty photos would otherwise be forty round trips. item_photos is
	// allow_on_submit, so a submitted EIR takes the same edits through save("Update").
	if (sortable) {
		d.set_primary_action(__('Simpan'), () => {
			d.hide();
			// A submitted EIR saves with "Update", which skips the `validate` hook — so the
			// empty rows have to go here or the mandatory check refuses the sort.
			drop_empty_photo_rows(frm);
			if (frm.is_dirty()) frm.save(frm.doc.docstatus === 1 ? 'Update' : undefined);
		});
	}

	function render() {
		const slide = slides[idx];
		const row = slide.cdn ? (locals[slide.cdt] || {})[slide.cdn] || {} : {};
		const src = slide.src ? frappe.utils.escape_html(slide.src) : '';
		// A row still waiting for its picture keeps the same stage size, so the arrows do
		// not jump around while paging through a mixed set.
		const stage = src
			? `<div class="oak-carousel-stage"><img src="${src}" alt=""></div>`
			: `<div class="oak-carousel-stage oak-carousel-empty">
					<div class="oak-photo-none">${__('Belum ada foto')}</div>
				</div>`;
		const area = slide.kind === 'item' ? row.area || '' : '';
		d.fields_dict.viewer.$wrapper.html(`
			<div class="oak-carousel">
				<button class="btn btn-default oak-carousel-nav" data-oak-step="-1"
					title="${__('Sebelumnya')}" ${idx === 0 ? 'disabled' : ''}>&lsaquo;</button>
				${stage}
				<button class="btn btn-default oak-carousel-nav" data-oak-step="1"
					title="${__('Berikutnya')}" ${idx === slides.length - 1 ? 'disabled' : ''}>&rsaquo;</button>
			</div>
			<div class="oak-carousel-caption">
				<span class="oak-carousel-count">${idx + 1} / ${slides.length}</span>
				${area ? `<span class="oak-carousel-area">${frappe.utils.escape_html(area)}</span>` : ''}
				<span>${frappe.utils.escape_html(slide.label || '')}</span>
			</div>
		`);
		d.$wrapper.find('.oak-carousel-nav').on('click', (e) => go(cint($(e.currentTarget).attr('data-oak-step'))));
		// The picker belongs to an item photo. On an exterior slide there is nothing to
		// assign, so it goes away rather than sitting there inert.
		d.set_df_property('checklist_item', 'hidden', slide.kind === 'item' ? 0 : 1);
		// The upload control is for a row that has no picture yet — a row created by hand in
		// the grid. Once the photo is there it goes away: an EIR photo is evidence, and
		// replacing it from a viewer is not an edit anyone should make in passing.
		d.set_df_property('photo', 'hidden', sortable && slide.kind === 'item' && !slide.src ? 0 : 1);
		if (slide.kind === 'item') {
			syncing = true;
			d.set_value('checklist_item', row.checklist_item || '');
			d.set_value('photo', row.photo || '');
			syncing = false;
		}
		// "Detail Foto" opens the file itself in its own tab: the stage above scales every
		// photo to the same box, and a reviewer who wants to zoom into a weld or read a plate
		// needs the original pixels, not the fitted copy.
		const $open_tab = d.get_secondary_btn();
		d.set_secondary_action_label(__('Detail Foto'));
		d.set_secondary_action(() => slide.src && window.open(slide.src, '_blank'));
		$open_tab.toggleClass('hide', !slide.src);
	}

	function go(step) {
		const next = idx + step;
		if (next < 0 || next >= slides.length) return;
		idx = next;
		render();
	}

	// Arrow keys, because a carousel you have to aim at with a mouse is not much better
	// than opening the rows one at a time. Bound on the dialog and removed with it.
	// Ignored while a control has focus, or typing into the Link's search box would page
	// the carousel away mid-word.
	d.$wrapper.on('keydown', (e) => {
		if ($(e.target).is('input, textarea, select')) return;
		if (e.key === 'ArrowLeft') go(-1);
		else if (e.key === 'ArrowRight') go(1);
	});

	render();
	d.show();
	// The dialog traps focus on its first control; put it on the body so the arrow keys
	// work without the reviewer clicking the picture first.
	d.$wrapper.find('.modal-content').attr('tabindex', '-1').trigger('focus');
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

// The save-time half of the same rule. `drop_row_without_photo` above only fires when a
// photo is CLEARED, so a row added in the grid and left empty lives on until the save —
// where Frappe's client-side mandatory check refuses it before the server's
// `drop_empty_photo_rows` can quietly do the same thing. Runs from `validate`, which
// form.js fires before check_mandatory.
//
// Not reached on a docstatus 1 "Update" save (form.js skips validate for it), so the two
// dialogs that can save a submitted EIR call this themselves.
function drop_empty_photo_rows(frm) {
	let dropped = 0;
	PHOTO_TABLES.forEach(([table_fieldname, , photo_fieldname]) => {
		const rows = frm.doc[table_fieldname] || [];
		const kept = rows.filter((row) => (row[photo_fieldname] || '').trim());
		if (kept.length === rows.length) return;
		dropped += rows.length - kept.length;
		kept.forEach((row, i) => {
			row.idx = i + 1;
		});
		frm.doc[table_fieldname] = kept;
		frm.refresh_field(table_fieldname);
	});
	if (dropped) {
		frappe.show_alert({
			message: __('{0} baris foto tanpa foto dihapus.', [dropped]),
			indicator: 'orange',
		});
	}
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
		fill_from_checklist_item(cdt, cdn);
	},
});

// --- B-D2: Inspection Damage Entry grid fetch triggers (manual in-grid editing) ---
// Mirror create_eir's mapping so a row built by hand matches one built by the
// checklist dialog / PWA: checklist item -> component + area, repair code ->
// estimated hours, damage code -> description + default severity.
frappe.ui.form.on('Inspection Damage Entry', {
	// Opening a finding shows its own photos, right under the description. The pictures
	// live in the Inspection's `damage_photos` table (a child doctype cannot own a child
	// table of its own), but nobody reading the form has to know that: the separate grid is
	// hidden, so the form carries ONE list of findings and each finding carries its shots.
	form_render(frm, cdt, cdn) {
		render_damage_photos(frm, cdt, cdn);
	},
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
		sync_followup_flags(frm, true);
		if (!row.repair_code || row.estimated_repair_hours) return;
		frappe.db.get_value('Inspection Repair Code', row.repair_code, 'standard_hours').then((r) => {
			const hours = (r.message || {}).standard_hours;
			if (hours) frappe.model.set_value(cdt, cdn, 'estimated_repair_hours', hours);
		});
	},

	damage_type(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		sync_followup_flags(frm, true);
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

	// A note the surveyor typed counts as a finding on its own (eir_followups), so the
	// "Buat M&R" box has to answer to it too.
	damage_description(frm) {
		sync_followup_flags(frm, true);
	},
});

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
