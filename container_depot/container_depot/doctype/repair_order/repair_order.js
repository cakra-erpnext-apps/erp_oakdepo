// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

// Owner-approval workflow transitions (Desk). All go through the same whitelisted ESS
// endpoints the PWA uses (container_depot/mr.py is the single source of truth).
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

// The one expected next step per status, each in its own function so _mr_buttons reads as
// a table of "status -> langkah berikutnya" instead of a wall of inline callbacks.
//
// There is no "Teruskan ke Admin Ops" any more: Admin Ops is the first pair of eyes on every
// M&R, so Draft is already their desk and the first thing that leaves it goes to the owner.
function mr_publish_to_owner(frm) {
	mr_call(
		frm,
		'container_depot.ess.repairs.mr_publish_to_owner',
		{},
		__('Kirim estimasi ini ke owner untuk disetujui? Mulai sekarang owner bisa melihatnya di web customer.')
	);
}

// Recording the OWNER'S approval — not the clicker's. Desk staff type it in on their behalf.
// This is also the moment the parts LEAVE the warehouse: the workshop cannot fit a part that
// is still on a shelf, so the stock moves when the money is agreed.
function mr_approve(frm) {
	mr_call(
		frm,
		'container_depot.ess.repairs.mr_decision',
		{
			decision: 'Approved',
			line_decisions: JSON.stringify(mr_line_decisions(frm)),
		},
		__('Catat bahwa OWNER menyetujui estimasi ini? Part yang disetujui langsung KELUAR dari stok.')
	);
}

// The hand-over, same gate Cleaning Order puts in front of its team: an owner's yes settles
// the money, this settles that the depot is ready to start. Only now does the job appear on
// the PWA worklist.
function mr_forward_to_team(frm) {
	mr_call(
		frm,
		'container_depot.ess.repairs.mr_forward_to_team',
		{},
		__('Teruskan M&R ini ke team repair? Order akan muncul di worklist PWA dan bisa mulai dikerjakan.')
	);
}

// Desk signs off on the WORK and closes the job. Nothing moves in the warehouse here — the
// parts went out at approval. This is the irreversible step all the same: a Completed M&R can
// no longer be rewound to Draft, and it becomes billable.
function mr_finalize(frm) {
	mr_call(
		frm,
		'container_depot.ess.repairs.mr_finalize',
		{},
		__('Pekerjaan sudah diperiksa dan benar? M&R ditutup dan siap ditagih. Setelah ini tidak bisa dikembalikan ke Draft.')
	);
}

// The same close, taken straight from Approved — for work that never needed dispatching (a
// five-minute fix the operator watched, or a subcontractor's job already done). Same endpoint,
// different question: there is no team report to check, so it asks whether the work is
// actually finished rather than whether it has been reviewed.
function mr_finalize_direct(frm) {
	mr_call(
		frm,
		'container_depot.ess.repairs.mr_finalize',
		{},
		__('Selesaikan M&R ini sekarang tanpa diteruskan ke team? Pakai ini kalau pekerjaannya memang sudah selesai. M&R ditutup dan siap ditagih.')
	);
}

// The depot-side actions (publish / withdraw / bypass). These were gated on "Admin Ops"
// until that role was deleted on 2026-08-05 with the custom role model, so System Manager
// is the only holder left — matching the server guard in ess/repairs.py. The server
// re-checks either way; this only decides whether the button is worth showing.
function is_admin_ops() {
	return frappe.user.has_role('System Manager');
}

// Admin-Ops bypass: approve directly without ever showing it to the owner. Offered wherever
// the estimate is still in depot hands (Draft / Revision Requested / Service Setup).
function mr_bypass_button(frm, group) {
	frm.add_custom_button(
		__('Setujui Tanpa Owner'),
		() =>
			frappe.prompt(
				[{ fieldname: 'note', fieldtype: 'Small Text', label: __('Alasan (opsional)') }],
				(v) =>
					mr_call(
						frm,
						'container_depot.ess.repairs.mr_bypass_approval',
						{ note: v.note },
						__('Setujui estimasi ini langsung? Owner TIDAK akan pernah melihatnya, dan part yang disetujui langsung KELUAR dari stok.')
					),
				__('Setujui Tanpa Owner'),
				__('Setujui')
			),
		group
	);
}

// SUBMIT — the primary button, in the very slot Frappe would otherwise fill with "Save" on
// an already-saved form. Repair Order has no docstatus, so what a submittable Cleaning Order
// gets for free is done by hand here: one press closes the order from wherever it stands,
// skipping the owner, the dispatch to the team and the review (mr.submit_direct walks those
// steps server-side, so nothing is left half-done).
//
// Save is never taken away — Frappe puts it straight back the moment the form goes dirty
// (Toolbar.add_update_button_on_dirty), and the refresh after each save hands the slot back
// to us, so editing still saves normally. The toolbar sets its own primary action in
// refresh_header, which run_serially runs BEFORE the refresh script trigger: this wins.
function mr_submit_primary(frm) {
	if (frm.is_new() || frm.is_dirty()) return;
	if (['Completed', 'Cancelled', 'Rejected'].includes(frm.doc.status)) return;
	// Same gate as the server (ess/repairs._require_admin_ops): submitting approves on the
	// owner's behalf, so it stays with the bypass roles.
	if (!is_admin_ops() || !frappe.perm.has_perm(frm.doctype, 0, 'write')) return;
	// An order with nothing on it closes without billing anything — say so, because that is
	// a different thing to agree to than approving an estimate.
	const empty = !(frm.doc.used_items || []).length;
	const warn = empty
		? __('Submit M&R ini sekarang? Service & Parts masih KOSONG — order ditutup tanpa tagihan.')
		: __('Submit M&R ini sekarang? Order langsung SELESAI — owner tidak diminta menyetujui, order tidak diteruskan ke team, dan part yang disetujui KELUAR dari stok.');
	frm.page.set_primary_action(__('Submit'), () =>
		mr_call(frm, 'container_depot.ess.repairs.mr_submit_direct', {}, warn)
	);
}

function mr_decision_with_note(frm, decision, title) {
	frappe.prompt(
		[{ fieldname: 'note', fieldtype: 'Small Text', label: __('Catatan dari owner') }],
		(v) =>
			mr_call(frm, 'container_depot.ess.repairs.mr_decision', {
				decision,
				line_decisions: JSON.stringify(mr_line_decisions(frm)),
				note: v.note,
			}),
		__(title),
		__('Catat')
	);
}

// One prompt shape for every backward step (tarik / kembalikan / batalkan): ask why, confirm
// what it undoes, then call. Cancelling used to be the one destructive action that asked for
// nothing at all.
function mr_step_back(frm, opts) {
	frm.add_custom_button(
		__(opts.label),
		() =>
			frappe.prompt(
				[{ fieldname: 'note', fieldtype: 'Small Text', label: __('Alasan (opsional)') }],
				(v) => mr_call(frm, opts.method, { ...(opts.args || {}), note: v.note }, __(opts.confirm)),
				__(opts.label),
				__(opts.primary || opts.label)
			),
		opts.group
	);
}

frappe.ui.form.on('Repair Order', {
	// The photo formatter MUST be installed here, not in refresh. form.js renders the fields
	// and only then fires the refresh trigger (frappe.run_serially in render_form:
	// refresh_fields() comes before script_manager.trigger("refresh")), so a formatter
	// installed in refresh arrives after the grid has already painted its Photo column empty
	// — and nothing re-renders it afterwards. setup runs once, before any of it.
	setup(frm) {
		frm.trigger('_set_queries');
		install_damage_thumbnails(frm);
		install_work_photo_thumbnails(frm);
	},
	onload(frm) {
		frm.trigger('_set_queries');
	},
	_set_queries(frm) {
		// Retired tanks (Active off) are out of the fleet and never offered.
		frm.set_query('container', () => ({ filters: { is_active: 1 } }));
		// The Used-Items picker offers ONLY what the PWA M&R picker does: Depot Service Menu
		// "Maintenance" ∩ the container owner's contract price list (see used_item_query).
		// The picker is narrowed by the ROW: Jenis decides service vs part, and a part is
		// offered only if that row's gudang actually holds it. Both are read off the live
		// row, not the saved doc, so the list is right before Save.
		frm.set_query('item', 'used_items', (doc, cdt, cdn) => {
			const row = locals[cdt][cdn] || {};
			return {
				query: 'container_depot.container_depot.doctype.repair_order.repair_order.used_item_query',
				filters: {
					repair_order: frm.doc.name || '',
					warehouse: row.warehouse || '',
					line_type: row.line_type || '',
				},
			};
		});
		// Real, enabled warehouses of the company, scoped to the container's branch.
		frm.set_query('warehouse', 'used_items', () => ({
			query: 'container_depot.container_depot.doctype.repair_order.repair_order.used_item_warehouse_query',
			filters: { repair_order: frm.doc.name || '' },
		}));
		// A proof photo may only name a service/part the owner is actually being charged for.
		// The list is built from the live grid rather than the saved doc, so a line added a
		// moment ago is already photographable. The server re-checks this on validate — this
		// only saves the operator from picking something that would be refused.
		frm.set_query('item', 'work_photos', () => ({
			filters: { name: ['in', used_item_codes(frm)] },
		}));
	},
	_refresh_on_hand(frm) {
		// The Stok column is stamped server-side on save; this keeps it current while the
		// form sits open (another M&R may have consumed the same part meanwhile). Asked per
		// (item, gudang) because each row may draw from a different warehouse.
		const pairs = (frm.doc.used_items || [])
			.filter((r) => r.item && r.line_type === 'Part')
			.map((r) => ({ item: r.item, warehouse: r.warehouse || '' }));
		if (!pairs.length) return;
		frappe.call({
			method: 'container_depot.container_depot.doctype.repair_order.repair_order.used_items_on_hand',
			args: { pairs: JSON.stringify(pairs), repair_order: frm.doc.name || '' },
			callback(r) {
				const stock = r.message || {};
				// Assigned directly, NOT via set_value: reading live stock must never mark the
				// form dirty, or every visit would look like an unsaved edit.
				(frm.doc.used_items || []).forEach((row) => {
					const wh = row.warehouse || '';
					const hit = row.item && row.line_type === 'Part' ? stock[`${row.item}::${wh}`] : null;
					row.on_hand = hit != null ? String(hit) : null;
				});
				frm.refresh_field('used_items');
			},
		});
	},
	refresh(frm) {
		frm.trigger('_set_queries');
		frm.trigger('_refresh_on_hand');
		frm.trigger('_render_system_facts');
		// Rates on this order come from the tank OWNER's contract price list, not the
		// depot's — with no live contract every line prices at 0 and the invoice bills 0.
		container_depot.rate_card_notice(frm, frm.doc.principal);
		// A "buka lagi" request raised from the PWA, with its reason — otherwise it reaches
		// Admin Ops as a bell notification and leaves no trace on the order itself.
		if (frm.doc.reopen_requested) {
			frm.dashboard.add_comment(
				__('Team minta M&R ini dibuka lagi') + (frm.doc.reopen_note ? ': ' + frm.doc.reopen_note : ''),
				'orange',
				true
			);
		}
		// Status intro banner — says where the M&R stands AND names the button that moves it,
		// so the label on screen and the sentence above it are the same words.
		const intros = {
			Draft: [__('Draft — meja Admin Ops. Susun estimasi di Service & Parts, lalu Kirim ke Owner.'), 'blue'],
			'Pending Approval': [__('Sudah di web customer, menunggu keputusan owner. Admin Ops masih bisa Tarik dari Owner.'), 'orange'],
			'Revision Requested': [__('Owner minta revisi. Perbaiki itemnya, lalu Kirim ke Owner lagi.'), 'orange'],
			Approved: [__('Disetujui owner dan part sudah keluar dari stok. Teruskan ke Team agar masuk worklist PWA, atau Selesaikan Langsung kalau pekerjaannya sudah selesai.'), 'green'],
			Rejected: [__('Ditolak owner.'), 'red'],
			Pending: [__('Sudah di worklist PWA team repair, menunggu dikerjakan.'), 'blue'],
			'In Progress': [__('Sedang dikerjakan di workshop.'), 'yellow'],
			'Pending Review': [__('Team sudah selesai di lapangan — periksa pekerjaannya, lalu Selesaikan M&R.'), 'orange'],
			Completed: [__('Selesai dan siap ditagih. Tank siap dilayani.'), 'green'],
			Cancelled: [__('M&R ini dibatalkan.'), 'red'],
		};
		if (intros[frm.doc.status]) frm.set_intro(intros[frm.doc.status][0], intros[frm.doc.status][1]);

		frm.trigger('_mr_buttons');
		mr_submit_primary(frm);
		frm.trigger('_lock_estimate_grid');
		install_work_photo_thumbnails(frm);
		bind_work_photo_clicks(frm);
	},
	// Everything the order fills in by itself — its id, where it stands, who owns the tank,
	// the money, the papers it came from — lives in the SIDEBAR, next to Created By / Last
	// Edited By, instead of taking a section on the form. None of it is an isian, and a form
	// section full of read-only fields reads like work waiting to be done. The fields stay on
	// the doctype (hidden) because the list view, the standard filters and the server all
	// keep reading them; this is only where a human is shown them.
	_render_system_facts(frm) {
		const link = container_depot.doc_link;
		const esc = frappe.utils.escape_html;
		container_depot.render_system_facts(frm, [
			[__('Repair Order ID'), frm.doc.repair_order_id && esc(frm.doc.repair_order_id)],
			[__('Status'), frm.doc.status && esc(frm.doc.status)],
			[__('Principal (Owner)'), frm.doc.principal && esc(frm.doc.principal)],
			[__('Container No'), frm.doc.container_no && esc(frm.doc.container_no)],
			[__('Order Created'), frm.doc.order_created && esc(frappe.datetime.str_to_user(frm.doc.order_created))],
			[__('Inspection Reference'), link('Inspection', frm.doc.inspection)],
			[__('Container Booking'), link('Container Booking', frm.doc.container_booking)],
			[__('Dikerjakan Oleh'), link('User', frm.doc.started_by)],
			[__('Start Date'), frm.doc.start_date && esc(frappe.datetime.str_to_user(frm.doc.start_date))],
			[__('Completion Date'), frm.doc.completion_date && esc(frappe.datetime.str_to_user(frm.doc.completion_date))],
			// One line per currency: an M&R can mix them (each Item Price carries its own),
			// so a single number would be adding rupiah to dollars.
			[
				__('Total Cost'),
				(frm.doc.totals || [])
					.map((t) => esc(format_currency(t.total, t.currency)))
					.join('<br>'),
			],
			// Total Cost carries the ITEMS only. Labour is added by the invoice, so say what
			// it will come to here rather than let the total read as the whole bill.
			//
			// The money on its own. The hours used to be printed beside it and the separator
			// read as a multiplication sign — "6,00 jam · $ 24,00" looked like a sum still to
			// be done instead of the answer. Summed over the lines the invoice will bill.
			[
				__('Total Biaya Manhour'),
				(() => {
					const rows = (frm.doc.used_items || []).filter((r) => (r.decision || 'Pending') !== 'Rejected');
					const amount = rows.reduce((n, r) => n + flt(r.manhour_rate), 0);
					if (!amount) return '';
					return esc(format_currency(amount, (rows.find((r) => r.currency) || {}).currency));
				})(),
			],
			[__('Billing Status'), frm.doc.billing_status && esc(frm.doc.billing_status)],
		]);
	},
	_mr_buttons(frm) {
		if (frm.is_new()) return;
		const s = frm.doc.status;
		// Every button below ends in an ess/repairs endpoint, and each of those asks for
		// Repair Order write (on top of require_menu("mr")). A read-only holder — Management,
		// Warehouse, Team EIR — gets none of them, so SAY why instead of leaving them staring
		// at a form that looks broken. The Admin-Ops-only ones keep their own is_admin_ops().
		if (!frappe.perm.has_perm(frm.doctype, 0, 'write')) {
			if (!['Completed', 'Cancelled'].includes(s)) {
				frm.dashboard.add_comment(
					__('Anda hanya bisa melihat M&R ini — tanpa izin ubah, tidak ada tombol tindakan.'),
					'gray',
					true
				);
			}
			return;
		}

		// LANGKAH BERIKUTNYA — exactly one primary button per status, labelled with what it
		// really does. Draft is Admin Ops' own desk, so the first move is straight to the
		// owner; after the owner agrees the tail mirrors Cleaning Order (Teruskan ke Team →
		// team works in the PWA → Pending Review → Desk finalises).
		const next = {
			// The Admin-Ops gate: nothing reaches the customer web until this is clicked.
			Draft: is_admin_ops() ? ['Kirim ke Owner', mr_publish_to_owner] : null,
			'Revision Requested': is_admin_ops() ? ['Kirim ke Owner', mr_publish_to_owner] : null,
			'Pending Approval': ['Owner Setuju', mr_approve],
			Approved: is_admin_ops() ? ['Teruskan ke Team', mr_forward_to_team] : null,
			// Pending / In Progress belong to the team in the PWA — Desk has nothing to press
			// until the work comes back for review.
			'Pending Review': ['Selesaikan M&R', mr_finalize],
		}[s];
		if (next) frm.add_custom_button(__(next[0]), () => next[1](frm)).addClass('btn-primary');

		// The owner's two other answers, flat beside "Owner Setuju" so the three read as one
		// set. Prefixed "Owner" because that is WHOSE decision is being recorded — depot staff
		// only type it in on their behalf (decided_by is whoever clicks).
		if (s === 'Pending Approval') {
			frm.add_custom_button(__('Owner Minta Revisi'), () =>
				mr_decision_with_note(frm, 'Revision Requested', 'Owner Minta Revisi')
			);
			frm.add_custom_button(__('Owner Menolak'), () => mr_decision_with_note(frm, 'Rejected', 'Owner Menolak'));
		}

		// The other half of the PWA's "Ajukan Revisi": the request only notifies, THIS is where
		// Admin Ops acts on it. Offered without a request too — they may spot the mistake
		// themselves. Reopening goes to In Progress, not Draft: what was wrong is the repair,
		// not the estimate the owner already agreed to. Refused server-side once the order has
		// reached an invoice, so it is not offered here either.
		if (is_admin_ops() && s === 'Completed' && (frm.doc.billing_status || 'Unbilled') === 'Unbilled') {
			frm.add_custom_button(
				frm.doc.reopen_requested ? __('Setujui Revisi') : __('Buka Lagi ke In Progress'),
				() =>
					frappe.prompt(
						[{ fieldname: 'note', fieldtype: 'Small Text', label: __('Alasan (opsional)') }],
						(v) =>
							mr_call(
								frm,
								'container_depot.ess.repairs.mr_reopen_completed',
								{ note: v.note },
								__('Buka kembali M&R ini? Status kembali ke In Progress dan tanggal selesai dihapus; estimasi, persetujuan owner dan part yang sudah keluar tetap.')
							),
						__('Buka Lagi M&R'),
						__('Buka Lagi')
					)
			).addClass(frm.doc.reopen_requested ? 'btn-primary' : '');
		}

		// The other road out of Approved, flat beside "Teruskan ke Team" because it is a peer
		// choice and not an escape hatch: hand it to the team, or close it because the work is
		// already done. Anything in the dropdown below reads as "something went wrong"; this
		// does not.
		if (s === 'Approved') {
			frm.add_custom_button(__('Selesaikan Langsung'), () => mr_finalize_direct(frm));
		}

		// Everything that steps BACKWARD or around the flow lives in one dropdown, so the
		// happy path is never buried among escape hatches.
		const group = __('Tindakan Lain');

		if (is_admin_ops() && ['Draft', 'Revision Requested'].includes(s)) {
			mr_bypass_button(frm, group);
		}
		// The team's own correction, before Desk finalises it — nothing has left the
		// warehouse yet, so this costs nothing to undo.
		if (s === 'Pending Review') {
			mr_step_back(frm, {
				label: 'Kembalikan ke Team',
				method: 'container_depot.ess.repairs.mr_withdraw_review',
				confirm: 'Kembalikan M&R ini ke team untuk diperbaiki? Statusnya kembali In Progress.',
				primary: 'Kembalikan',
				group,
			});
		}
		// "Tarik ulang" — pull it back off the customer web to arrange it again. Only while
		// the owner has not decided (the server enforces that too).
		if (is_admin_ops() && s === 'Pending Approval') {
			mr_step_back(frm, {
				label: 'Tarik dari Owner',
				method: 'container_depot.ess.repairs.mr_withdraw_from_owner',
				confirm: 'Tarik estimasi ini dari owner? Keputusan per-item direset dan bisa dikirim ulang.',
				primary: 'Tarik',
				group,
			});
		}
		// Human-error recovery: rewind to an editable Draft to fix a wrong / missing input,
		// then run approval again. Adm Ops only; not from Draft (already editable) or after
		// Completed (parts issued → Batalkan instead).
		if (
			is_admin_ops() &&
			['Pending Approval', 'Revision Requested', 'Approved', 'Pending', 'In Progress', 'Pending Review', 'Rejected'].includes(s)
		) {
			mr_step_back(frm, {
				label: 'Kembalikan ke Draft',
				method: 'container_depot.ess.repairs.mr_reopen_draft',
				confirm: 'Kembalikan M&R ini ke Draft? Seluruh ronde approval dihapus (keputusan per-item, waktu pengajuan, keputusan owner) dan part yang sudah keluar DIKEMBALIKAN ke stok; item tetap.',
				primary: 'Kembalikan',
				group,
			});
		}
		if (['Draft', 'Revision Requested', 'Pending Approval', 'Approved', 'Pending', 'In Progress', 'Pending Review'].includes(s)) {
			mr_step_back(frm, {
				label: 'Batalkan M&R',
				method: 'container_depot.ess.repairs.set_repair_status',
				args: { status: 'Cancelled' },
				confirm: 'Batalkan M&R ini? Pekerjaan dianggap tidak jadi, part yang sudah keluar DIKEMBALIKAN ke stok, dan tank dilepas dari order ini.',
				primary: 'Batalkan',
				group,
			});
		}
	},
	_lock_estimate_grid(frm) {
		const grid = frm.fields_dict.used_items && frm.fields_dict.used_items.grid;
		if (!grid) return;
		// Estimate editable while it is still in depot/Admin-Ops hands — Service Setup
		// included, since arranging it before the customer sees it is the point of that
		// step. The per-line owner decision + remark are editable only while Pending
		// Approval (mirrors MR_EDITABLE_STATUSES server-side).
		const editable = ['Draft', 'Revision Requested'].includes(frm.doc.status);
		const pending = frm.doc.status === 'Pending Approval';
		grid.cannot_add_rows = !editable;
		grid.cannot_delete_rows = !editable;
		// The adjustable cost inputs follow the estimate-build phase (the three amounts are
		// always derived, so they stay read-only via the doctype).
		['item', 'quantity', 'item_rate', 'manhour_rate'].forEach((f) =>
			grid.update_docfield_property(f, 'read_only', editable ? 0 : 1)
		);
		['decision', 'owner_remark'].forEach((f) => grid.update_docfield_property(f, 'read_only', pending ? 0 : 1));
		grid.refresh();

		// The evidence album follows the WORK, not the estimate: photos are taken while the
		// repair is happening, which is long after the prices froze. It closes when the order
		// does (mr.MR_PHOTO_STATUSES) — a closed album is part of what the owner was shown.
		const photos = frm.fields_dict.work_photos && frm.fields_dict.work_photos.grid;
		if (photos) {
			const open = ['Draft', 'Revision Requested', 'Approved', 'Pending', 'In Progress'].includes(
				frm.doc.status
			);
			photos.cannot_add_rows = !open;
			photos.cannot_delete_rows = !open;
			['photo', 'item', 'caption'].forEach((f) =>
				photos.update_docfield_property(f, 'read_only', open ? 0 : 1)
			);
			photos.refresh();
		}
	},
	// The row form's own close control is an icon-only chevron in the corner of the heading,
	// which reads as "collapse" rather than "done with this line". A labelled button sits
	// beside it instead.
	//
	// It ONLY closes. There is deliberately no Save here: every field writes straight into the
	// M&R as it is typed, so a closed row has lost nothing, and what puts it in the database is
	// the order's own Save — one press at the end, not one per line.
	//
	// Re-injected on every render because the toolbar is rebuilt with the form, and guarded by
	// its own class so a second render never stacks two buttons.
	used_items_on_form_rendered(frm) {
		const grid_form = frm.fields_dict.used_items && frm.fields_dict.used_items.grid.open_grid_row;
		if (!grid_form) return;
		const actions = grid_form.wrapper.find('.grid-form-heading .row-actions');
		if (!actions.length || actions.find('.mr-row-close').length) return;
		$(`<button class="btn btn-primary btn-sm pull-right mr-row-close">${__('Tutup')}</button>`)
			.prependTo(actions)
			.on('click', () => {
				grid_form.row.toggle_view(false);
				// Swallow the click. The heading this button sits in carries a handler of its
				// own that TOGGLES the row, so a bubbling click reopens what was just closed
				// — which is why every native button in this toolbar returns false too.
				return false;
			});
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

// Items on this order, for the evidence-photo picker. Read off the live grid so a line just
// typed in is already offerable; de-duplicated because one item may hold two lines and the
// picker should not show it twice.
function used_item_codes(frm) {
	const codes = (frm.doc.used_items || []).map((r) => r.item).filter(Boolean);
	// An empty list would make Frappe drop the filter and offer the whole Item master, which
	// is the opposite of the point — a name nothing can match keeps it empty instead.
	return codes.length ? [...new Set(codes)] : ['__none__'];
}

// The evidence album. `used_item` pins a photo to one Service & Parts ROW, which only matters
// when the same item is on the order twice; picking the item is all a human does, and the
// first line carrying it is the right answer everywhere else. The server re-derives this on
// validate, so this is a convenience, not the rule.
frappe.ui.form.on('Repair Work Photo', {
	item(frm, cdt, cdn) {
		const row = locals[cdt][cdn] || {};
		const line = (frm.doc.used_items || []).find((r) => r.item === row.item);
		frappe.model.set_value(cdt, cdn, 'used_item', line ? line.name : null);
	},
});

// Everything on a line that is only true BECAUSE of the item picked on it, and the value it
// falls back to. Dropping the item alone is not enough: the price, the currency, the manhour
// preview and the Stok reading all outlive it and would sit under the next item as if they
// had been quoted for it. Qty is in here too — changing Jenis or Gudang starts the line over,
// so it starts at the doctype default. Remarks and the owner's decision are NOT: those are
// typed about the line, not derived from the item.
const USED_ROW_DERIVED = {
	item: null,
	item_name: null,
	currency: null,
	on_hand: null,
	is_stock_item: 0,
	item_rate: 0,
	item_amount: 0,
	amount: 0,
	manhour: 0,
	manhour_rate: 0,
	quantity: 1,
};

function reset_used_row(frm, cdt, cdn) {
	// An untouched row has nothing to undo, and clearing it would dirty the form the instant
	// a fresh line's Jenis is set.
	if (!(frappe.get_doc(cdt, cdn) || {}).item) return;
	// item first: its own handler bails on an empty item, so nothing re-seeds what follows.
	Object.keys(USED_ROW_DERIVED).forEach((f) => frappe.model.set_value(cdt, cdn, f, USED_ROW_DERIVED[f]));
	recompute_used_total(frm);
}

// Service & Parts — a line costs the ITEM only:
//   Total Cost (amount) = Qty × Item Rate
// Tarif Manhour sits beside it and is deliberately left OUT of Total Cost: the invoice
// charges labour once in its own header (invoicing.apply_manhour_charge), so adding it here
// would bill the owner twice. It is an INPUT — seeded from the owner's contract, then typed
// over freely — while Total Cost stays derived. Editable: quantity, item_rate, manhour_rate.
frappe.ui.form.on('Repair Used Item', {
	line_type(frm, cdt, cdn) {
		// Jenis narrows the picker, so an item chosen under the old Jenis is no longer valid
		// — and neither is anything that was derived from it. Only "Part" draws from a gudang.
		reset_used_row(frm, cdt, cdn);
		if (frappe.get_doc(cdt, cdn).line_type !== 'Part') frappe.model.set_value(cdt, cdn, 'warehouse', null);
	},
	warehouse(frm, cdt, cdn) {
		// Stock is per gudang: a part valid in one warehouse may not exist in another, and
		// the Stok figure has to follow the row's own warehouse.
		reset_used_row(frm, cdt, cdn);
		frm.trigger('_refresh_on_hand');
	},
	item(frm, cdt, cdn) {
		const row = frappe.get_doc(cdt, cdn);
		if (!row.item || frm.is_new()) return;
		frm.trigger('_refresh_on_hand');
		// Default the cost inputs from the owner's Item Price for the picked item.
		frappe.call({
			method: 'container_depot.ess.repairs.mr_item_pricing',
			args: { repair_order: frm.doc.name, item: row.item },
			callback: (r) => {
				const b = r.message || {};
				// Currency follows the item's own Item Price (lines may differ).
				frappe.model.set_value(cdt, cdn, 'currency', b.currency || '');
				frappe.model.set_value(cdt, cdn, 'item_rate', flt(b.item_rate));
				// A fresh item means fresh labour: reseed from the owner's contract, the same
				// figures the server would seed. The tariff is taken AS IT STANDS — no hours
				// arithmetic on the order — and neither figure touches Total Cost.
				frappe.model.set_value(cdt, cdn, 'manhour', flt(b.manhour));
				frappe.model.set_value(cdt, cdn, 'manhour_rate', flt(b.manhour_rate));
			},
		});
	},
	quantity: price_used_row,
	item_rate: price_used_row,
	// Typing a labour tariff only repaints the sidebar total — it is never priced into the
	// line, so there is nothing to recompute on the row itself.
	manhour_rate(frm) {
		frm.trigger('_render_system_facts');
	},
	decision: recompute_used_total,
	used_items_remove: recompute_used_total,
	// Filling a line is a sequence — Jenis, then Gudang, then Item, then the numbers the
	// item seeds — and the grid can only ever show a few of those columns at once. So a new
	// row opens straight into its OWN form, where the whole line is visible and the fields
	// sit in the order they are meant to be filled; the grid itself stays a list, and an
	// existing line is still editable in place.
	//
	// Deferred by a tick on purpose: Grid.add_new_row fires this trigger BEFORE it calls
	// refresh(), so the GridRow for the new line does not exist yet at trigger time.
	used_items_add(frm, cdt, cdn) {
		setTimeout(() => {
			const grid = frm.fields_dict.used_items && frm.fields_dict.used_items.grid;
			const row = grid && grid.grid_rows_by_docname && grid.grid_rows_by_docname[cdn];
			if (row) row.toggle_view(true);
		}, 0);
	},
});

function price_used_row(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	const item_amount = flt(row.quantity) * flt(row.item_rate);
	frappe.model.set_value(cdt, cdn, 'item_amount', item_amount);
	// Labour is an input, is NOT scaled by qty, and is NOT added to the line total — the
	// invoice settles it in its own header. Nothing here derives from it.
	frappe.model.set_value(cdt, cdn, 'amount', item_amount);
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


// --- Checklist Kerusakan (read-only) -----------------------------------------------
//
// The M&R's `damages` table is a frozen snapshot of what the EIR found, so it is READ, never
// filled: the grid is `read_only` on the doctype, which already makes both the row and its
// detail non-editable. What is copied from the EIR here is the LOOK — same columns, same
// widths, same photo thumbnail — so a finding reads the same on the M&R as it did on the EIR
// it came from (inspection.js, "Checklist Kerusakan").
//
// The photos are the row's own `photos` column (a JSON array of URLs stamped by
// eir_followups.seed_damages_from_eir), not a sibling table as on the EIR — so the formatter
// gets everything it needs from the child row it is handed, with no reach back to the form.
function damage_photos_of(row) {
	if (!row || !row.photos) return [];
	try {
		const parsed = JSON.parse(row.photos);
		return Array.isArray(parsed) ? parsed.filter(Boolean) : [];
	} catch (e) {
		return [];
	}
}

// The Photo column of the damage grid: first shot, plus a "+n" badge for the rest.
function damage_thumbnail(value, df, options, doc) {
	const photos = damage_photos_of(doc);
	if (!photos.length) return '';
	const src = frappe.utils.escape_html(photos[0]);
	const more = photos.length > 1 ? `<span class="oak-damage-more">+${photos.length - 1}</span>` : '';
	return `<span class="oak-damage-thumb"><img class="oak-grid-photo" src="${src}" data-oak-photo="${src}" loading="lazy" alt="">${more}</span>`;
}

function install_damage_thumbnails(frm) {
	const std = (frappe.meta.docfield_map['Repair Damage Entry'] || {}).photos_preview;
	if (std) std.formatter = damage_thumbnail;
	if (!frm.docname) return;
	const df = frappe.meta.get_docfield('Repair Damage Entry', 'photos_preview', frm.docname);
	if (df) df.formatter = damage_thumbnail;
}

// The evidence at working size, walked with the Next button. Read-only: an EIR photo is a
// fact of the inspection, and the M&R is not where it gets changed.
function open_damage_photos(photos, start) {
	if (!photos.length) return;
	let idx = Math.min(Math.max(start || 0, 0), photos.length - 1);
	const d = new frappe.ui.Dialog({
		title: __('Foto Kerusakan'),
		size: 'large',
		fields: [{ fieldname: 'viewer', fieldtype: 'HTML' }],
	});
	const paint = () => {
		const src = frappe.utils.escape_html(photos[idx]);
		d.fields_dict.viewer.$wrapper.html(
			`<div class="oak-photo-large"><img src="${src}" alt=""></div>
			 <div class="text-muted text-center mt-2">${idx + 1} / ${photos.length}</div>`
		);
	};
	if (photos.length > 1) {
		d.set_secondary_action_label(__('Berikutnya ›'));
		d.set_secondary_action(() => {
			idx = (idx + 1) % photos.length;
			paint();
		});
	}
	paint();
	d.show();
}

// Foto per temuan inside the opened row — the same strip the EIR shows, minus the drop and
// add buttons (there is nothing to edit here).
function render_damage_photos(frm, cdt, cdn) {
	const grid = frm.fields_dict.damages && frm.fields_dict.damages.grid;
	const grid_row = grid && grid.grid_rows_by_docname && grid.grid_rows_by_docname[cdn];
	const field = grid_row && grid_row.grid_form && grid_row.grid_form.fields_dict.photos_html;
	if (!field) return;

	const photos = damage_photos_of((locals[cdt] || {})[cdn]);
	if (!photos.length) {
		field.$wrapper.html(`<div class="oak-photo-none">${__('Tidak ada foto di EIR untuk temuan ini.')}</div>`);
		return;
	}
	field.$wrapper.html(
		`<div class="oak-damage-photos">${photos
			.map((p, i) => {
				const src = frappe.utils.escape_html(p);
				return `<div class="oak-damage-photo"><img src="${src}" data-oak-idx="${i}" alt=""></div>`;
			})
			.join('')}</div>`
	);
	field.$wrapper.find('img[data-oak-idx]').on('click', (e) => {
		open_damage_photos(photos, parseInt(e.currentTarget.getAttribute('data-oak-idx'), 10));
	});
}

// `form_render` belongs on the CHILD doctype: grid_row.show_form triggers it under the child
// doctype's own handlers, so one registered on Repair Order would never be reached.
frappe.ui.form.on('Repair Damage Entry', {
	form_render(frm, cdt, cdn) {
		render_damage_photos(frm, cdt, cdn);
	},
});

// --- Foto Bukti Pekerjaan ------------------------------------------------------------
//
// Read the same way Foto Inspeksi is read on the EIR (inspection.js), because it is the same
// job: a wall of /files/… paths that has to be SCANNED — is that the right part, was the weld
// actually done — and Frappe renders an Attach Image column as its bare URL inside an <a>.
// So: a thumbnail in the row, and a click anywhere on the row opens the picture at working
// size with its two editable fields beside it, stepping to the next without closing.
//
// Why a second copy of inspection.js's machinery rather than a shared module: the two forms
// load independently and the pieces differ where it matters (an EIR photo is filed under a
// checklist item and carries no caption; this one is filed under a Service & Parts line and
// does). The CSS they share IS shared — public/css/container_depot.css lists both tables.

function work_photo_thumbnail(value) {
	if (!value) return '';
	const src = frappe.utils.escape_html(value);
	// data-oak-photo carries the URL for the viewer; the <img> src is the same file, so no
	// second request and no thumbnail to generate.
	return `<img class="oak-grid-photo" src="${src}" data-oak-photo="${src}" loading="lazy" alt="">`;
}

// Must run from setup: form.js renders the fields and only then fires refresh, so a formatter
// installed in refresh arrives after the column has already painted. Written onto the
// STANDARD docfield (every per-docname copy made later inherits it, because grid.js copies
// with a shallow copy_dict) and onto the copy this form may already hold.
function install_work_photo_thumbnails(frm) {
	const std = (frappe.meta.docfield_map['Repair Work Photo'] || {}).photo;
	if (std) std.formatter = work_photo_thumbnail;
	if (!frm.docname) return;
	const df = frappe.meta.get_docfield('Repair Work Photo', 'photo', frm.docname);
	if (df) df.formatter = work_photo_thumbnail;
}

// Click a row -> open it in the carousel. CAPTURE phase, because Frappe binds click-to-edit
// straight on the cell (grid_row.js) and a delegated handler on an ancestor would fire after
// the inline row form had already opened underneath the dialog.
function bind_work_photo_clicks(frm) {
	const grid = frm.fields_dict.work_photos && frm.fields_dict.work_photos.grid;
	const el = grid && grid.wrapper && grid.wrapper.get(0);
	// The wrapper is built once and rows re-render inside it, so one listener holds for the
	// life of the grid; the flag stops refreshes stacking duplicates (one dialog per refresh).
	if (!el || el._oakWorkPhotoBound) return;
	el._oakWorkPhotoBound = true;
	el.addEventListener(
		'click',
		(e) => {
			if (!e.target.closest) return;
			// The large preview inside an opened row: nothing to protect it from, it zooms.
			const large = e.target.closest('.oak-photo-large img');
			if (large) {
				e.preventDefault();
				open_work_photo_carousel(frm, large.getAttribute('data-oak-photo'));
				return;
			}
			// Only a real data row. The heading and search rows are .grid-row too but carry
			// no data-name; the checkbox keeps its own job.
			const row = e.target.closest('.grid-row[data-name]');
			if (!row || e.target.closest('.grid-row-check')) return;
			if (!e.target.closest('.grid-static-col, .btn-open-row')) return;
			e.stopPropagation();
			e.preventDefault();
			open_work_photo_carousel(frm, null, row.getAttribute('data-name'));
		},
		true
	);
}

// The photo at working size inside the opened row panel. Rendered into a plain HTML docfield
// rather than injected beside the Attach control, so it survives whatever that control does
// to its own markup between framework versions.
function render_work_photo_preview(frm, cdt, cdn) {
	const grid = frm.fields_dict.work_photos && frm.fields_dict.work_photos.grid;
	const grid_row = grid && grid.grid_rows_by_docname && grid.grid_rows_by_docname[cdn];
	const grid_form = grid_row && grid_row.grid_form;
	const field = grid_form && grid_form.fields_dict.photo_preview;
	if (!field) return;

	// Kill ControlAttachImage's hover popover: the CSS hides its anchor, so it can no longer
	// be triggered, but an instance created before that has to be disposed or it hangs around
	// over the form.
	const control = grid_form.fields_dict.photo;
	const $link = control && control.$value && control.$value.find('.attached-file-link');
	if ($link && $link.length && $link.popover) {
		try {
			$link.popover('dispose');
		} catch (e) {
			try {
				$link.popover('destroy');
			} catch (e2) {
				/* no popover attached — nothing to do */
			}
		}
	}

	const url = ((locals[cdt] || {})[cdn] || {}).photo;
	if (!url) {
		field.$wrapper.html(`<div class="oak-photo-none">${__('Belum ada foto')}</div>`);
		return;
	}
	const src = frappe.utils.escape_html(url);
	field.$wrapper.html(`<div class="oak-photo-large"><img src="${src}" data-oak-photo="${src}" alt=""></div>`);
}

// Every row the grid is showing, in its order — INCLUDING rows whose photo is still missing,
// because those are exactly the ones that need filling.
function work_photo_slides(frm) {
	return (frm.doc.work_photos || []).map((row) => ({
		src: row.photo || '',
		cdn: row.name,
		label: row.item_name || row.item || __('(Belum dipilih)'),
	}));
}

function may_edit_work_photos(frm) {
	return (
		['Draft', 'Revision Requested', 'Approved', 'Pending', 'In Progress'].includes(frm.doc.status) &&
		frappe.perm.has_perm(frm.doctype, 0, 'write')
	);
}

// Open at a row (from a row click) or at a URL (from the big preview). One dialog: picture on
// a fixed stage, the two fields that belong to it, ‹ › and arrow keys, and a Simpan that is
// the reviewer's own step — paging through twenty photos must not be twenty round trips.
function open_work_photo_carousel(frm, src, cdn) {
	const slides = work_photo_slides(frm);
	if (!slides.length) {
		frappe.msgprint(__('Belum ada foto bukti pekerjaan di M&R ini.'));
		return;
	}
	let idx = Math.max(
		0,
		slides.findIndex((sl) => (cdn ? sl.cdn === cdn : sl.src === src))
	);
	const editable = may_edit_work_photos(frm);
	// Guards the controls' own change handlers while the carousel writes into them on every
	// slide change — without it, moving to the next photo would re-file the previous one.
	let syncing = false;

	const d = new frappe.ui.Dialog({
		title: __('Foto Bukti Pekerjaan'),
		size: 'large',
		fields: [
			{ fieldname: 'viewer', fieldtype: 'HTML' },
			{
				fieldname: 'item',
				fieldtype: 'Link',
				label: __('Untuk Item'),
				options: 'Item',
				// Only what the owner is actually being charged for on this order — a photo
				// filed under anything else reads as proof of work nobody agreed to, and the
				// server refuses it on validate anyway.
				get_query: () => ({ filters: { name: ['in', used_item_codes(frm)] } }),
				read_only: editable ? 0 : 1,
				onchange() {
					if (syncing) return;
					const slide = slides[idx];
					if (!slide) return;
					const row = (locals['Repair Work Photo'] || {})[slide.cdn] || {};
					const value = d.get_value('item') || '';
					if (value === (row.item || '')) return;
					frappe.model.set_value('Repair Work Photo', slide.cdn, 'item', value);
					// The line is what the server keys on; re-derive it whenever the item moves.
					const line = (frm.doc.used_items || []).find((r) => r.item === value);
					frappe.model.set_value('Repair Work Photo', slide.cdn, 'used_item', line ? line.name : null);
					slide.label = value;
					frm.refresh_field('work_photos');
					render();
				},
			},
			{
				fieldname: 'caption',
				fieldtype: 'Data',
				label: __('Keterangan'),
				description: __('mis. "sebelum", "sesudah las", "nomor seri baru"'),
				read_only: editable ? 0 : 1,
				onchange() {
					if (syncing) return;
					const slide = slides[idx];
					if (!slide) return;
					const row = (locals['Repair Work Photo'] || {})[slide.cdn] || {};
					const value = d.get_value('caption') || '';
					if (value === (row.caption || '')) return;
					frappe.model.set_value('Repair Work Photo', slide.cdn, 'caption', value);
					frm.refresh_field('work_photos');
				},
			},
			{
				fieldname: 'photo',
				fieldtype: 'Attach Image',
				label: __('Foto'),
				// `options` on an Attach control is not a link target — ControlAttach merges it
				// into its FileUploader config. Naming the parent doc here is what keeps the
				// uploaded File attached to this M&R: a dialog control has no `frm` to infer it
				// from, and a private file with no attached_to is readable only by whoever
				// uploaded it, so the owner would get a broken image.
				options: {
					doctype: frm && frm.doctype,
					docname: frm && frm.docname,
					fieldname: 'work_photos',
					restrictions: { allowed_file_types: ['image/*'] },
				},
				onchange() {
					if (syncing) return;
					const slide = slides[idx];
					if (!slide) return;
					const url = d.get_value('photo') || '';
					const row = (locals['Repair Work Photo'] || {})[slide.cdn] || {};
					if (!url || url === (row.photo || '')) return;
					frappe.model.set_value('Repair Work Photo', slide.cdn, 'photo', url).then(() => {
						slide.src = url;
						frm.refresh_field('work_photos');
						render();
					});
				},
			},
		],
	});

	if (editable) {
		d.set_primary_action(__('Simpan'), () => {
			d.hide();
			if (frm.is_dirty()) frm.save();
		});
	}

	function render() {
		const slide = slides[idx];
		const row = (locals['Repair Work Photo'] || {})[slide.cdn] || {};
		const url = slide.src ? frappe.utils.escape_html(slide.src) : '';
		// A row still waiting for its picture keeps the same stage size, so the arrows do not
		// jump around while paging through a mixed set.
		const stage = url
			? `<div class="oak-carousel-stage"><img src="${url}" alt=""></div>`
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
				<span>${frappe.utils.escape_html(row.item_name || row.item || '')}</span>
				${row.caption ? `<span class="oak-carousel-area">${frappe.utils.escape_html(row.caption)}</span>` : ''}
			</div>
		`);
		d.$wrapper.find('.oak-carousel-nav').on('click', (e) => go(cint($(e.currentTarget).attr('data-oak-step'))));
		// The upload control is for a row that has no picture yet — one added by hand in the
		// grid. Once the photo is there it goes away: this is evidence, and replacing it from
		// a viewer is not an edit anyone should make in passing.
		d.set_df_property('photo', 'hidden', editable && !slide.src ? 0 : 1);
		syncing = true;
		d.set_value('item', row.item || '');
		d.set_value('caption', row.caption || '');
		d.set_value('photo', row.photo || '');
		syncing = false;
		// "Detail Foto" opens the file itself in its own tab: the stage scales every photo to
		// the same box, and reading a serial plate needs the original pixels.
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

	// Arrow keys — a carousel you have to aim at with a mouse is barely better than opening
	// the rows one at a time. Ignored while a control has focus, or typing a caption would
	// page the carousel away mid-word.
	d.$wrapper.on('keydown', (e) => {
		if ($(e.target).is('input, textarea, select')) return;
		if (e.key === 'ArrowLeft') go(-1);
		else if (e.key === 'ArrowRight') go(1);
	});

	render();
	d.show();
	// The dialog traps focus on its first control; put it on the body so the arrow keys work
	// without the reviewer clicking the picture first.
	d.$wrapper.find('.modal-content').attr('tabindex', '-1').trigger('focus');
}

frappe.ui.form.on('Repair Work Photo', {
	form_render(frm, cdt, cdn) {
		render_work_photo_preview(frm, cdt, cdn);
	},
	// A photo row without a photo is not a row. `photo` is reqd, so an emptied one could never
	// be saved anyway — Frappe would refuse with "Foto is required" and leave the user to work
	// out which of twenty rows it meant. The record exists only to carry the image.
	photo(frm, cdt, cdn) {
		const row = (locals[cdt] || {})[cdn];
		if (!row || row.photo || row.__islocal) return;
		frm.get_field('work_photos').grid.grid_rows_by_docname[cdn].remove();
	},
});
