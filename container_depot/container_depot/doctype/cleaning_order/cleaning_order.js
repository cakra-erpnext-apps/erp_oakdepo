// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

// The "Metode Cleaning (Service)" table picks one OR MORE cleaning services the container
// Owner (Principal) is priced for: members of the Depot Service Menu "Cleaning" that have a
// selling Item Price in the owner's active Price List (resolved server-side from the
// container).
//
// Each row carries the two PRICES the rate card states, side by side and never merged:
//   Tarif         — what the service itself costs
//   Tarif Manhour — what its labour costs
// Both are read straight off the owner's price list and used AS THEY STAND — no hours
// arithmetic on the order. They roll up into Total Tarif Service and Biaya Manhour, which
// stay apart: billing charges the service tariffs and settles labour on its own line, so
// folding one into the other here would bill labour twice.
// All three are SEEDED from the active Depot Contract of the container's owner the moment a
// Service is picked and stay EDITABLE — a seeded value is never re-applied, so a negotiated
// one-off figure survives every later save. They roll up into Total Tarif Service and Total
// Tarif Manhour, which are deliberately kept apart: billing charges the service tariffs as
// they stand and settles the labour once, on its own invoice line. Costing labour into the
// tariff here too would bill it twice.
frappe.ui.form.on('Cleaning Order', {
	setup(frm) {
		install_photo_thumbnails(frm);
	},
	onload(frm) {
		// Retired tanks (Active off) are out of the fleet and never offered.
		frm.set_query('container', () => ({ filters: { is_active: 1 } }));
		frm.trigger('_set_queries');
	},
	refresh(frm) {
		install_photo_thumbnails(frm);
		bind_qc_grid_clicks(frm);
		hide_sidebar_attachments(frm);
		frm.trigger('_set_queries');
		frm.trigger('_forward_button');
		frm.trigger('_render_system_facts');
		// A revision request raised from the PWA, with its reason — otherwise the request
		// reaches Admin Ops as a bell notification and leaves no trace on the order itself.
		if (frm.doc.docstatus === 1 && frm.doc.revision_requested) {
			frm.dashboard.add_comment(
				__('Revisi diminta') + (frm.doc.revision_note ? ': ' + frm.doc.revision_note : ''),
				'orange',
				true,
			);
		}
		// The other half of the PWA's "Ajukan Revisi": the request only notifies: THIS is
		// where Admin Ops acts on it. Also offered without a request — Admin Ops may spot the
		// mistake themselves. The server enforces doc.check_permission("cancel"): un-submitting
		// is cancelling, and that stays away from the field roles.
		if (frm.doc.docstatus === 1 && frappe.perm.has_perm(frm.doctype, 0, 'cancel')) {
			frm.add_custom_button(
				frm.doc.revision_requested ? __('Setujui Revisi') : __('Kembalikan ke Draft'),
				() => revert_to_draft(frm),
			).addClass(frm.doc.revision_requested ? 'btn-primary' : '');
		}
		// Waiting on THIS reviewer: the field is done, Submit is the last step.
		if (frm.doc.docstatus === 0 && frm.doc.status === 'Pending Review') {
			frm.dashboard.add_comment(
				__('Operator sudah selesai di lapangan — periksa lalu Submit untuk menyelesaikan order.'),
				'blue',
				true,
			);
		}
		// Tarif + Manhour of every cleaning service are seeded from the tank OWNER's active
		// contract; without one the grid seeds zeros and the invoice bills nothing.
		container_depot.rate_card_notice(frm, frm.doc.container_principal);
	},
	// Everything the system fills in by itself — status, the two totals, the invoice it was
	// swept into, the documents it came from — lives in the SIDEBAR (shared block, same look
	// as Container Booking) instead of taking a section on the form. The fields stay on the
	// doctype under the "Sistem" tab (hidden) because the list view, the standard filters and
	// the server all keep reading them; this is only where a human is shown them.
	//
	// Tarif and Manhour are listed as two separate facts and NEVER added up: billing charges
	// the tariff as it stands and settles the labour once, on its own invoice line.
	_render_system_facts(frm) {
		const link = container_depot.doc_link;
		const esc = frappe.utils.escape_html;
		container_depot.render_system_facts(frm, [
			[__('Status'), frm.doc.status && esc(frm.doc.status)],
			[
				__('Total Tarif Service'),
				frm.doc.cleaning_total && format_currency(frm.doc.cleaning_total, frm.doc.currency),
			],
			[
				__('Biaya Manhour'),
				frm.doc.manhour_charge_total &&
					format_currency(frm.doc.manhour_charge_total, frm.doc.currency),
			],
			[__('Owner (Principal)'), link('Customer', frm.doc.container_principal)],
			[__('Last Cargo'), link('Cargo', frm.doc.last_cargo)],
			[__('Dikerjakan Oleh'), link('User', frm.doc.assigned_to)],
			[__('Reference EIR'), link('Inspection', frm.doc.inspection)],
			[__('Container Booking'), link('Container Booking', frm.doc.container_booking)],
			[__('Sales Invoice'), link('Sales Invoice', frm.doc.sales_invoice)],
			[__('Ref Email'), link('Communication', frm.doc.reff_email)],
		]);
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
			query: 'container_depot.container_depot.doctype.cleaning_order.cleaning_order.cleaning_item_query',
			filters: { container: frm.doc.container || '' },
		}));
	},
	_forward_button(frm) {
		// Admin Ops step: while the order is in "Service Setup" they pick the cleaning
		// method(s); the button forwards it to the depot team's worklist (-> Pending).
		if (frm.is_new() || frm.doc.docstatus !== 0 || frm.doc.status !== 'Service Setup') return;
		// It ends in frm.save(), so `write` is what the server will ask for.
		if (!frappe.perm.has_perm(frm.doctype, 0, 'write')) return;
		frm.add_custom_button(__('Teruskan ke Team'), () => {
			if (!(frm.doc.cleaning_services || []).length) {
				frappe.msgprint(__('Pilih minimal satu metode cleaning (Service) dulu.'));
				return;
			}
			frm.set_value('status', 'Pending');
			frm.save().then(() => frappe.show_alert({ message: __('Diteruskan ke team cuci.'), indicator: 'green' }));
		}).addClass('btn-primary');
	},
});

// "Setujui Revisi" / "Kembalikan ke Draft" — flip a submitted order back to an editable
// draft (In_Progress), so it returns to the operator's PWA worklist and goes through review
// again. The server refuses if the order is already on an invoice.
function revert_to_draft(frm) {
	frappe.confirm(
		__('Kembalikan cleaning order ini ke draft agar bisa dikerjakan & diperiksa ulang?'),
		() => {
			frappe.call({
				method: 'container_depot.container_depot.cleaning.revert_to_draft',
				args: { name: frm.doc.name },
				freeze: true,
				freeze_message: __('Mengembalikan ke draft…'),
				callback() {
					frappe.show_alert({
						message: __('Cleaning order dikembalikan ke draft'),
						indicator: 'green',
					});
					frm.reload_doc();
				},
			});
		},
	);
}

// The order carries its own evidence — Foto QC and the surveyor's signature, both real
// fields on the form — so the generic Attachments block in the sidebar is a second,
// unmanaged place for the same thing. Dropped from the sidebar; the fields stay.
//
// Hidden by CSS CLASS, not by hiding the element: frappe.ui.form.Attachments.refresh() calls
// parent.toggle(true) on every form refresh, so an inline display:none is won straight back.
// Same fix (and the same !important rule) as hide_sidebar_attachments in inspection.js.
function hide_sidebar_attachments(frm) {
	const parent = frm.attachments && frm.attachments.parent;
	if (parent && parent.length) parent.addClass('oak-no-attachments');
}

// Foto QC shows the picture, not its file path — the same look the EIR's Foto Inspeksi grid
// has (inspection.js). Design only: nothing about how the rows are edited changes.
//
// The formatter is written onto BOTH the standard docfield and this form's per-docname copy.
// Frappe's Attach Image formatter never goes through _apply_custom_formatter, and grid rows
// read their docfields from a shallow per-docname copy — so the function has to be on the
// standard field (every later copy inherits it) and on the copy this form may already hold.
function photo_thumbnail(value) {
	if (!value) return '';
	const src = frappe.utils.escape_html(value);
	return `<img class="oak-grid-photo" src="${src}" loading="lazy" alt="">`;
}

function install_photo_thumbnails(frm) {
	const std = (frappe.meta.docfield_map['Cleaning QC Photo'] || {}).photo;
	if (std) std.formatter = photo_thumbnail;
	if (!frm.docname) return;
	const df = frappe.meta.get_docfield('Cleaning QC Photo', 'photo', frm.docname);
	if (df) df.formatter = photo_thumbnail;
}

// Click a Foto QC row -> the picture at working size in a modal, with its Keterangan beside
// it and arrows to the next row. Same job the EIR's Foto Inspeksi modal does
// (inspection.js): the grid is a list to SCAN, and a thumbnail is too small to judge a top
// flange by, so opening a row must show the photo — not swap it for the attach control.
//
// The listener has to run in the CAPTURE phase. Frappe binds click-to-edit straight onto the
// cell (grid_row.js: $col.on("click", ... toggle_editable_row())) and onto .row-index /
// .btn-open-row; a delegated handler on an ancestor fires after those, by which point the
// inline editor — the very thing that replaces the photo with its link — is already open
// underneath the dialog. Capturing on the grid wrapper gets there first, and
// stopPropagation keeps the event from ever reaching the row.
function bind_qc_grid_clicks(frm) {
	const grid = frm.fields_dict.qc_photos && frm.fields_dict.qc_photos.grid;
	const el = grid && grid.wrapper && grid.wrapper.get(0);
	// The wrapper is built once and rows re-render inside it, so one listener holds for the
	// life of the grid. The flag stops refreshes from stacking duplicates, which would open
	// one dialog per refresh.
	if (!el || el._oakQcBound) return;
	el._oakQcBound = true;
	el.addEventListener(
		'click',
		(e) => {
			if (!e.target.closest) return;
			// Only a real data row. The heading and search rows are .grid-row too but carry
			// no data-name; the checkbox and the sort handle keep their own jobs.
			const row = e.target.closest('.grid-row[data-name]');
			if (!row || e.target.closest('.grid-row-check')) return;
			if (!e.target.closest('.grid-static-col, .btn-open-row')) return;
			e.stopPropagation();
			e.preventDefault();
			open_qc_photo_editor(frm, row.getAttribute('data-name'));
		},
		true,
	);
}

// Every qc_photos row, in the order the grid shows them — including a row whose photo is
// still missing, because that is exactly the row that needs filling.
function qc_photo_slides(frm) {
	return (frm.doc.qc_photos || []).map((row) => ({
		src: row.photo || '',
		cdt: 'Cleaning QC Photo',
		cdn: row.name,
		label: row.caption || '',
	}));
}

function open_qc_photo_editor(frm, cdn) {
	const slides = qc_photo_slides(frm);
	if (!slides.length) return;
	const start = Math.max(0, slides.findIndex((s) => s.cdn === cdn));
	open_qc_carousel(frm, slides, start);
}

// qc_photos is NOT allow_on_submit, so a submitted (or cancelled) order takes no edits: the
// modal then opens as a plain viewer rather than offering fields whose save would be refused.
function may_edit_qc(frm) {
	return frm.doc.docstatus === 0 && frappe.perm.has_perm(frm.doctype, 0, 'write');
}

function open_qc_carousel(frm, slides, start) {
	let idx = Math.min(Math.max(start || 0, 0), slides.length - 1);
	const editable = may_edit_qc(frm);
	// Guards the controls' own change handlers while the carousel writes into them on every
	// slide change — without it, moving to the next photo would copy the previous photo's
	// caption onto the new row. The handlers re-check the row's stored value too, so a change
	// event landing after the flag clears is still a no-op.
	let syncing = false;

	const d = new frappe.ui.Dialog({
		title: __('Foto QC'),
		size: 'large',
		fields: [
			{ fieldname: 'viewer', fieldtype: 'HTML' },
			{
				fieldname: 'caption',
				fieldtype: 'Data',
				label: __('Keterangan'),
				read_only: editable ? 0 : 1,
				onchange() {
					if (syncing) return;
					const slide = slides[idx];
					if (!slide) return;
					const row = (locals[slide.cdt] || {})[slide.cdn] || {};
					const value = d.get_value('caption') || '';
					if (value === (row.caption || '')) return;
					frappe.model.set_value(slide.cdt, slide.cdn, 'caption', value).then(() => {
						slide.label = value;
						frm.refresh_field('qc_photos');
						render();
					});
				},
			},
			{
				fieldname: 'photo',
				fieldtype: 'Attach Image',
				label: __('Foto'),
				// `options` on an Attach control is not a link target — ControlAttach merges it
				// into its FileUploader config (set_upload_options). Naming the parent doc here
				// is what keeps the uploaded File attached to this order: a dialog control has
				// no `frm` to infer it from, and a private file with no attached_to is readable
				// only by whoever uploaded it — the next reader would get a broken image.
				options: {
					doctype: frm && frm.doctype,
					docname: frm && frm.docname,
					fieldname: 'qc_photos',
					restrictions: { allowed_file_types: ['image/*'] },
				},
				onchange() {
					if (syncing) return;
					const slide = slides[idx];
					if (!slide) return;
					const url = d.get_value('photo') || '';
					const row = (locals[slide.cdt] || {})[slide.cdn] || {};
					if (!url || url === (row.photo || '')) return;
					frappe.model.set_value(slide.cdt, slide.cdn, 'photo', url).then(() => {
						slide.src = url;
						frm.refresh_field('qc_photos');
						render();
					});
				},
			},
		],
	});

	// Saving is the reader's own step, not something a slide change does behind their back:
	// paging through twenty photos would otherwise be twenty round trips.
	if (editable) {
		d.set_primary_action(__('Simpan'), () => {
			d.hide();
			if (frm.is_dirty()) frm.save();
		});
	}

	function render() {
		const slide = slides[idx];
		const row = (locals[slide.cdt] || {})[slide.cdn] || {};
		const src = slide.src ? frappe.utils.escape_html(slide.src) : '';
		// A row still waiting for its picture keeps the same stage size, so the arrows do not
		// jump around while paging through a mixed set.
		const stage = src
			? `<div class="oak-carousel-stage"><img src="${src}" alt=""></div>`
			: `<div class="oak-carousel-stage oak-carousel-empty">
					<div class="oak-photo-none">${__('Belum ada foto')}</div>
				</div>`;
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
				<span>${frappe.utils.escape_html(row.caption || '')}</span>
			</div>
		`);
		d.$wrapper.find('.oak-carousel-nav').on('click', (e) => go(cint($(e.currentTarget).attr('data-oak-step'))));
		// The upload control is for a row that has no picture yet. Once the photo is there it
		// goes away: a QC photo is evidence, and replacing it from a viewer is not an edit
		// anyone should make in passing.
		d.set_df_property('photo', 'hidden', editable && !slide.src ? 0 : 1);
		syncing = true;
		d.set_value('caption', row.caption || '');
		d.set_value('photo', row.photo || '');
		syncing = false;
		// "Detail Foto" opens the file itself in its own tab: the stage scales every photo to
		// the same box, and reading a plate needs the original pixels, not the fitted copy.
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

	// Arrow keys, because a carousel you have to aim at with a mouse is not much better than
	// opening the rows one at a time. Ignored while a control has focus, or typing into
	// Keterangan would page the carousel away mid-word.
	d.$wrapper.on('keydown', (e) => {
		if ($(e.target).is('input, textarea, select')) return;
		if (e.key === 'ArrowLeft') go(-1);
		else if (e.key === 'ArrowRight') go(1);
	});

	render();
	d.show();
	// The dialog traps focus on its first control; put it on the body so the arrow keys work
	// without clicking the picture first.
	d.$wrapper.find('.modal-content').attr('tabindex', '-1').trigger('focus');
}

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
			method: 'container_depot.container_depot.doctype.cleaning_order.cleaning_order.service_pricing',
			args: { container: frm.doc.container, item_code: row.cleaning_item },
			callback(r) {
				const d = (r && r.message) || {};
				// A different Service means different figures, so BOTH prices — and the hours
				// behind the labour — are re-read from the price list, exactly like Tarif.
				const patch = {
					rate: d.rate || 0,
					manhour_rate: d.manhour_rate || 0,
					currency: d.currency,
					item_name: d.item_name,
				};
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

// Service tariff and labour are totalled apart — never into one figure, and neither is
// multiplied by anything: each is the sum of what the rate card charges.
function _recalc(frm) {
	let service = 0;
	let labour = 0;
	for (const row of frm.doc.cleaning_services || []) {
		service += flt(row.rate);
		labour += flt(row.manhour_rate);
	}
	frm.set_value('cleaning_total', service);
	frm.set_value('manhour_charge_total', labour);
}
