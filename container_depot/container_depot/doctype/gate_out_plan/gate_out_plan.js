// Gate Out Plan — Desk form behaviour.
frappe.ui.form.on("Gate Out Plan", {
	setup(frm) {
		// Owner only — every tank of this Principal, whatever its status or whereabouts.
		// A plan is a notice written days ahead: the tank is routinely still In_Depot, out
		// on a previous trip, or has no depot at all because it never gated in here, and
		// none of that stops the customer from announcing they will lift it on. There is no
		// header Depot to narrow by either — this is an OUTBOUND notice, so each row shows
		// the depot its own tank stands in (fetched from the Container master). Retired
		// tanks (Active off) still never appear — they are out of the fleet, and the server
		// refuses them on save anyway.
		frm.set_query("container", "containers", () => {
			const filters = { is_active: 1 };
			if (frm.doc.principal) filters.principal = frm.doc.principal;
			return { filters };
		});
	},

	refresh(frm) {
		render_related_orders(frm);
		render_system_facts(frm);
		set_fulfilment_progress(frm);
		set_grid_import_button(frm);
		mark_new_containers(frm);
		set_status_buttons(frm);

		// Where the plan ends: a Container Booking (Tank Out / Lift On) carrying these
		// tanks. Top-level, not buried in a "Buat" menu — it is the one action a finished
		// plan exists for, and an operator should not have to go looking for it.
		// We DON'T save it — customer (Bill To), charges and payment are completed on the
		// booking form (Container Booking is priced & submittable; the plan has no pricing).
		if (frm.is_new() || !(frm.doc.containers || []).length) return;
		if (!frappe.model.can_create("Container Booking")) return;
		// A cancelled plan is a closed record, and a plan whose tanks have all left has
		// nothing to book — offering the button there only leads to a server-side throw.
		if (frm.doc.status === "Cancelled") return;
		if (!(frm.doc.containers || []).some((r) => r.container && !r.gated_out)) return;
		frm.add_custom_button(__("Buat Container Booking (Lift On)"), () =>
			pick_containers_then_book(frm)
		);
	},

	principal(frm) {
		reset_containers(frm, __("Principal / Tank Owner"));
	},
});

// Everything the plan fills in by itself lives in the sidebar, above Last Edited By — same
// block Container Booking / Order Bongkar / Order Muat use (public/js/system_facts.js). The
// fields stay on the doctype (hidden) for the list view, the standard filters and the server.
function render_system_facts(frm) {
	const esc = frappe.utils.escape_html;
	container_depot.render_system_facts(frm, [
		[__("Status"), frm.doc.status && esc(frm.doc.status)],
		[
			__("Lift-On Terdekat"),
			frm.doc.next_lift_on && frappe.datetime.str_to_user(frm.doc.next_lift_on),
		],
		// Two decimals like the progress bar, not the Percent field's own six.
		[__("% Keluar"), frm.doc.container_summary ? `${flt(frm.doc.per_fulfilled, 2)}%` : null],
		[__("Container"), frm.doc.container_summary && esc(frm.doc.container_summary)],
		[__("Sumber"), frm.doc.source && esc(frm.doc.source)],
		[__("Ref Email"), container_depot.doc_link("Communication", frm.doc.reff_email)],
	]);
}

// Status is no longer a field on the form, so the one thing an operator did with it needs a
// button: closing a notice the customer called off. Fulfilled is never set by hand — it is
// what a full gate-out means. A normal save (not db_set) so on_update releases the tanks'
// lift-on stamps, exactly as editing the field used to.
function set_status_buttons(frm) {
	if (frm.is_new() || !frappe.perm.has_perm(frm.doctype, 0, "write")) return;
	if (frm.doc.status === "Open") {
		frm.add_custom_button(__("Batalkan Plan"), () => cancel_plan(frm));
	} else if (frm.doc.status === "Cancelled") {
		frm.add_custom_button(__("Buka Lagi"), () =>
			frm.set_value("status", "Open").then(() => frm.save())
		);
	}
}

// Asked BEFORE the status is touched. The server refuses to close a plan whose tanks are
// already on a live Tank Out booking — closing it would pull the lift-on priority out from
// under a pickup that is still on — and meeting that refusal from a form already flipped to
// Cancelled leaves the operator with a dirty doc to reload out of. Same check either way;
// this one just arrives in time to be useful, and names the way forward.
function cancel_plan(frm) {
	frappe.call({
		method: "container_depot.container_depot.doctype.gate_out_plan.gate_out_plan.blocking_bookings",
		args: { gate_out_plan: frm.doc.name },
		freeze: true,
		freeze_message: __("Memeriksa booking yang sudah dibuat…"),
	}).then((r) => {
		const held = r.message || [];
		if (held.length) {
			const esc = frappe.utils.escape_html;
			frappe.msgprint({
				title: __("Plan Sudah Dipakai"),
				indicator: "red",
				message:
					__(
						"Container berikut sudah dibuatkan Container Booking (Tank Out) yang masih berjalan:"
					) +
					`<ul>${held
						.map(
							(h) =>
								`<li>${esc(h.container_no)} → ${esc(h.booking)} (${esc(
									h.status || __("Draft")
								)})</li>`
						)
						.join("")}</ul>` +
					__(
						"Batalkan dulu booking-nya, atau biarkan plan tetap Open dan hapus hanya container yang belum dibooking."
					),
			});
			return;
		}
		frappe.confirm(
			__("Batalkan plan ini? Target lift-on dilepas dari semua container-nya."),
			() => frm.set_value("status", "Cancelled").then(() => frm.save())
		);
	});
}

// Principal scopes the container picker, so changing it invalidates every row already
// listed. (Depot does not — it says where the hand-over happens, not which tanks qualify.)
// The table is emptied outright rather than just clearing each row's link (what Container
// Booking does): here the ROW is the tank — its target date and note only mean anything
// attached to that tank — so leaving empty rows behind would keep dates hanging off
// nothing. The server refuses a mismatched row anyway (``_assert_rows_match_header``);
// this is what keeps the operator from hitting that.
function reset_containers(frm, what) {
	if (!(frm.doc.containers || []).length) return;
	frm.clear_table("containers");
	frm.refresh_field("containers");
	frappe.show_alert(
		{ message: __("Daftar container direset karena {0} diganti.", [what]), indicator: "orange" },
		7
	);
}

// --- % Keluar --------------------------------------------------------------------
// The same progress bar ERPNext puts on a Purchase Receipt for "% Amount Billed": how much
// of this notice has physically left. Percent alone reads as a number; the bar makes a
// half-collected plan obvious at a glance. Filled in by the server as each tank gates out.
function set_fulfilment_progress(frm) {
	const rows = (frm.doc.containers || []).filter((r) => r.container);
	if (frm.is_new() || !rows.length) return;
	const per = Math.min(100, Math.max(0, flt(frm.doc.per_fulfilled, 2)));
	const gone = rows.filter((r) => r.gated_out).length;
	// reset() first: refresh runs on every save, and the progress area otherwise stacks.
	frm.dashboard.reset();
	frm.dashboard.add_progress(__("Keluar Depo"), [
		{
			title: __("{0} dari {1} tank sudah keluar", [gone, rows.length]),
			width: `${per}%`,
			progress_class: per >= 100 ? "progress-bar-success" : "progress-bar-warning",
		},
	]);
}

// --- Order & EIR Terkait ---------------------------------------------------------
// The Kesiapan column says a tank is held up but not by WHAT. This names the cleaning / M&R
// orders per container, marks the ones still blocking, and links each to its form. The tank's
// EIR-In / EIR-Out sit in the same list as condition history — never as blockers.
//
// Read on every refresh rather than stored on the doc: the stored Kesiapan is kept current by
// hooks, but this list is the evidence behind it and must never be able to disagree with the
// orders themselves.
function render_related_orders(frm) {
	const field = frm.get_field("related_orders_html");
	if (!field) return;
	// Nothing to report on a brand-new plan — no saved containers yet.
	if (frm.is_new()) {
		field.$wrapper.empty();
		return;
	}
	// Placeholder while the call is in flight: at the top of the form an empty box reads as
	// "no orders", which is a different answer from "not loaded yet".
	field.$wrapper.html(`<div class="text-muted">${__("Memuat…")}</div>`);
	const shown_for = frm.doc.name;
	frappe.call({
		method: "container_depot.container_depot.doctype.gate_out_plan.gate_out_plan.related_orders",
		args: { gate_out_plan: frm.doc.name },
	}).then((r) => {
		if (frm.doc.name !== shown_for) return; // reply landed after the form moved on
		const tanks = r.message || [];
		field.$wrapper.html(related_orders_html(tanks));
		sync_row_status(frm, tanks);
	});
}

// The grid's Status column is a stored mirror, refreshed by fetch_from on save — so between
// saves it drifts from the master, and the tank whose cleaning just finished still reads
// In_Depot in the grid while this tab already says Available. The live answer is in hand
// anyway, so the grid is repainted with it.
//
// Assigned straight onto the row rather than through frappe.model.set_value: this is a
// display refresh of a read-only field the server recomputes on every save, and marking the
// form dirty for it would ask the operator to save a change they did not make.
function sync_row_status(frm, tanks) {
	const live = {};
	tanks.forEach((t) => (live[t.container] = t.status));
	let changed = false;
	(frm.doc.containers || []).forEach((row) => {
		const status = live[row.container];
		if (status && row.container_status !== status) {
			row.container_status = status;
			changed = true;
		}
	});
	if (changed) frm.refresh_field("containers");
}

function related_orders_html(tanks) {
	const esc = frappe.utils.escape_html;
	if (!tanks.length) return `<div class="text-muted">${__("Belum ada container di plan ini.")}</div>`;

	// Same shape as Container Booking's "Pekerjaan per Container" block: the tank as a link
	// to its master, then one flush row per document — pill first, then the link, then what
	// kind of document it is. Two panels answering the same question should not look like
	// two different features.
	return tanks
		.map((t) => {
			const title = frappe.utils.get_form_link(
				"Container", t.container, true, esc(t.container_no)
			);
			// "Available" is the only state a Tank Out booking may be submitted from, so it
			// is the one worth calling out in green; everything else is stated plainly.
			const status = t.status
				? `<span class="indicator-pill ${
						t.status === "Available" ? "green" : "gray"
				  } no-indicator-dot">${esc(t.status)}</span>`
				: "";
			const target = t.target_lift_on
				? `<span class="text-muted small">${__("Target")}: ${esc(t.target_lift_on)}</span>`
				: "";
			const counts = t.blocking_count
				? `<span class="text-danger small">${__("{0} menahan lift-on", [t.blocking_count])}</span>`
				: t.open_count
				  ? `<span class="text-muted small">${__("{0} belum selesai", [t.open_count])}</span>`
				  : "";
			// Every tank is listed even when it has nothing open — "this one is clear" is an
			// answer the operator came for, and a tank that silently vanished from the list
			// would read as one nobody has looked at. Say it out loud rather than leaving an
			// empty block, which reads as a broken panel.
			const rows = summary_rows(t.orders);
			const body = rows.length
				? `<div class="mt-2">${rows.map(order_line).join("")}</div>`
				: `<div class="text-muted mt-2">${__("Belum ada dokumen yang tercatat pada tank ini.")}</div>`;

			return `<div class="mb-4">
				<div class="d-flex align-items-center" style="gap: .5rem;">
					<b>${title}</b>${status}${target}
					<span class="ml-auto">${counts}</span>
				</div>
				${body}
			</div>`;
		})
		.join("");
}

// One line per kind: the tank's LAST cleaning, last M&R, last EIR-In, last EIR-Out, last
// booking, last bon. On a tank that has been through the depot twenty times the full history
// is dozens of rows and none of it is news — "what happened last" is the question, and the
// toggle is there for the rest.
//
// The one exception is an OLDER document still unfinished. That is rare (a cleaning left at
// Pending while a newer one was raised and finished), and precisely the thing an operator
// must not have hidden from them — this tab exists to surface outstanding work. So it stays
// on the list even though something newer of its kind is already shown.
//
// Voided documents are never the representative: "the last thing that happened" being a
// cancellation says nothing about the tank. Each producer returns its kind newest-first, so
// the first surviving row of a kind IS the latest one.
function summary_rows(orders) {
	const shown_kind = new Set();
	return orders.filter((o) => {
		if (o.cancelled) return false;
		if (!shown_kind.has(o.kind)) {
			shown_kind.add(o.kind);
			return true;
		}
		return o.open;
	});
}

function order_line(o) {
	const esc = frappe.utils.escape_html;
	// get_form_link emits this desk's own route, so the link holds wherever the desk is mounted.
	const link = frappe.utils.get_form_link(o.doctype, o.name, true, esc(o.name));
	// Orange = unfinished AND holding the lift-on back (only Cleaning / M&R can). Blue =
	// unfinished but not in the way: a draft EIR, a booking still being prepared. Green =
	// finished. Grey = cancelled — history, neither a warning nor a clearance.
	const tone = o.blocks ? "orange" : o.cancelled ? "gray" : o.open ? "blue" : "green";
	const kind = o.detail ? `${o.kind} · ${o.detail}` : o.kind;
	return `<div class="d-flex align-items-center" style="gap: .5rem; padding: 2px 0;">
		<span class="indicator-pill ${tone}">${esc(o.status || "—")}</span>
		<span style="min-width: 11rem;">${link}</span>
		<span class="text-muted">${esc(kind)}</span>
	</div>`;
}

// A plan is collected over several visits, so the question "which tanks is THIS booking
// for?" is asked outright instead of being buried in grid tick-boxes nobody finds. The ones
// actually ready to leave are pre-ticked; the rest can still be chosen deliberately, because
// a booking is often raised a day ahead of the cleaning finishing.
function pick_containers_then_book(frm) {
	// Status is read LIVE from the server, never off the grid row. The row's copy is only as
	// fresh as the last save, so a tank whose cleaning finished since then still offered
	// itself as In_Depot while the Order & EIR tab — which reads live — already called it
	// Available. Same endpoint family as that tab, so the two cannot disagree again.
	frappe.call({
		method: "container_depot.container_depot.doctype.gate_out_plan.gate_out_plan.pickable_containers",
		args: { gate_out_plan: frm.doc.name },
		freeze: true,
		freeze_message: __("Membaca status container…"),
	}).then((r) => {
		const rows = r.message || [];
		if (!rows.length) {
			frappe.msgprint(__("Semua container di plan ini sudah keluar."));
			return;
		}
		show_picker(frm, rows);
	});
}

function show_picker(frm, rows) {
	const options = rows.map((r) => {
		const bits = [r.status || __("status tidak diketahui")];
		if (r.target_lift_on) bits.push(`${__("Target")}: ${frappe.datetime.str_to_user(r.target_lift_on)}`);
		// Only the work itself is worth adding — the status already says "Booked" or
		// "Gate_Out", and repeating that as "Belum tiba" tells the operator nothing twice.
		if (r.blockers && r.blockers.length) bits.push(__("Belum: {0}", [r.blockers.join(", ")]));
		// Already on a lift-on booking that has not gone yet. Left on the list — there are
		// reasons to add it to another — but never pre-ticked, and the booking is named, so
		// booking the same tank twice takes a deliberate click instead of a default one.
		if (r.booking) bits.push(__("sudah dibooking {0}", [r.booking]));
		return {
			label: `${frappe.utils.escape_html(r.container_no)} — ${frappe.utils.escape_html(
				bits.join(" · ")
			)}`,
			value: r.container,
			checked: r.ready,
			danger: !!r.booking,
			warning: !r.ready && !r.booking,
			description: r.booking
				? __("Sudah ada booking berjalan")
				: r.ready
				? __("Siap diambil")
				: __("Belum siap diambil"),
		};
	});
	const ready_count = options.filter((o) => o.checked).length;

	const d = new frappe.ui.Dialog({
		title: __("Pilih container untuk dibooking"),
		fields: [
			{
				fieldname: "hint",
				fieldtype: "HTML",
				options: `<p class="text-muted small">${
					ready_count
						? __("{0} dari {1} container siap diambil (Available) — sudah dicentang.", [
								ready_count,
								options.length,
						  ])
						: __("Belum ada container yang Available. Centang manual kalau booking dibuat lebih dulu.")
				}</p>`,
			},
			{
				fieldname: "containers",
				fieldtype: "MultiCheck",
				label: __("Container"),
				options,
				select_all: true,
				sort_options: false,
			},
		],
		primary_action_label: __("Buat Booking"),
		primary_action() {
			const picked = d.get_value("containers") || [];
			if (!picked.length) {
				frappe.msgprint(__("Pilih minimal satu container."));
				return;
			}
			d.hide();
			make_booking(frm, picked);
		},
	});
	d.show();
}

function make_booking(frm, picked) {
	// Mapped server-side (see ``make_container_booking``): the booking line's condition and
	// cargo are read off each tank, which the browser cannot do, and the rows that already
	// gated out are dropped there rather than filtered in two places.
	frappe.model
		.open_mapped_doc({
			method: "container_depot.container_depot.doctype.gate_out_plan.gate_out_plan.make_container_booking",
			frm,
			args: { containers: picked },
			freeze_message: __("Menyiapkan booking…"),
		})
		.then((r) => {
			// Only once a booking actually opened: on a refused plan (every tank already out)
			// the server throws and there is nothing to complete.
			if (!r || r.exc) return;
			// Charges are never seeded from a plan (it has no pricing), so that ask always
			// stands; Customer (Bill To) only when the plan did not record one.
			const todo = frm.doc.customer
				? __("Lengkapi biaya & pembayaran, lalu simpan.")
				: __("Lengkapi Customer (Bill To), biaya & pembayaran, lalu simpan.");
			frappe.show_alert({ message: todo, indicator: "blue" }, 7);
		});
}

// --- Import Excel on the Container grid ------------------------------------------
// A lift-on notice routinely names twenty tanks and arrives as a spreadsheet attached to the
// customer's mail. Same dialog as Container Booking's grid importer — parsed server-side and
// added client-side, so it works on a brand-new, unsaved plan too.
function set_grid_import_button(frm) {
	const grid = frm.fields_dict.containers && frm.fields_dict.containers.grid;
	if (!grid) return;
	// Only while the plan is still a live worklist, and only for someone who could save the
	// rows it adds. (grid.add_custom_button dedups by label, so calling it on every refresh
	// is safe.)
	if (frm.doc.status !== "Open") return;
	if (!frappe.perm.has_perm(frm.doctype, 0, "write")) return;
	grid.add_custom_button(__("Import Excel"), () => import_dialog(frm));
}

// Tell apart, at a glance, the rows whose Container master this import just registered from
// the ones that picked an existing tank. A badge appended to the Container No column rather
// than a column of its own: the grid's ten column-widths are already spoken for, and the
// badge belongs next to the number it qualifies anyway.
function mark_new_containers(frm) {
	const grid = frm.fields_dict.containers && frm.fields_dict.containers.grid;
	const df = grid && grid.get_docfield("container_no");
	if (!df || df.formatter) return;
	// Append to what the stock formatter returns rather than replacing it. `value` arrives
	// already HTML-escaped — the grid pre-escapes plain-text fieldtypes before formatting
	// (grid_row.js `_escape_for_format`) — so it must not be escaped a second time.
	const base = frappe.form.get_formatter(df.fieldtype);
	df.formatter = (value, _df, _options, row) => {
		const cell = base(value, _df, _options, row);
		if (!row || !row.is_new_container) return cell;
		return `${cell} <span class="indicator-pill green" title="${__(
			"Master Container dibuat lewat import ini"
		)}">${__("Baru")}</span>`;
	};
	// The grid's columns were already painted by the time a refresh script runs
	// (frm.refresh_fields precedes it), so the freshly attached formatter needs one repaint
	// to show. Guarded above, this happens once per form load.
	grid.refresh();
}

// Same dialog as Container Booking's grid importer, field for field: the hint, the Principal
// picker that writes back to the form, the file, and "Ganti baris yang ada". Only the column
// list differs — a plan carries a target date and a note where a booking carries condition
// and cargo. Parsed server-side, rows added client-side, so it works on an unsaved plan too.
function import_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Import Container dari Excel"),
		fields: [
			{
				fieldname: "hint",
				fieldtype: "HTML",
				options: `<p class="text-muted small">${__(
					"Kolom: Container, Target Lift-On (YYYY-MM-DD), Catatan (opsional). Baris judul dilewati."
				)}</p>`,
			},
			// Principal is shown (and editable) here because it decides what the import does:
			// it OWNS every container master the file registers, and it is what a row is
			// refused for belonging to someone else. Editing it writes straight back to the
			// form, so the two can never drift — and changing it clears the rows already on
			// the grid, exactly as changing it on the form does.
			{
				fieldname: "principal",
				fieldtype: "Link",
				options: "Customer",
				label: __("Principal / Tank Owner"),
				reqd: 1,
				default: frm.doc.principal || "",
				description: __("Pemilik tank. Container baru didaftarkan atas nama ini."),
				onchange() {
					const picked = this.get_value();
					if (picked && picked !== frm.doc.principal) frm.set_value("principal", picked);
				},
			},
			{ fieldname: "file", fieldtype: "Attach", label: __("File Excel (.xlsx)"), reqd: 1 },
			{ fieldname: "replace", fieldtype: "Check", label: __("Ganti baris yang ada") },
		],
		primary_action_label: __("Import"),
		primary_action(values) {
			frappe.call({
				method: "container_depot.container_depot.doctype.gate_out_plan.gate_out_plan.parse_container_xlsx",
				args: {
					file_url: values.file,
					// A Container cannot be created without an owner; the dialog carries it
					// (and has already written it back to the form).
					principal: values.principal || frm.doc.principal || null,
					// Always on, as on a booking: a lift-on notice routinely names a tank whose
					// master entry lags behind, and every number registered is reported back by
					// name so a typo is caught here rather than months later.
					create_missing: 1,
				},
				freeze: true,
				freeze_message: __("Membaca file…"),
				callback(r) {
					d.hide();
					apply_import(frm, r.message || {}, values.replace);
				},
			});
		},
	});
	// Downloads live in the dialog so the template and the list of valid container numbers
	// are one click away. window.open (not frappe.call) because these stream a file back,
	// not JSON; the session cookie rides along so the GET is authenticated.
	const gop = "/api/method/container_depot.container_depot.doctype.gate_out_plan.gate_out_plan";
	const bkg = "/api/method/container_depot.container_depot.doctype.container_booking.container_booking";
	d.add_custom_action(__("Download Template"), () => {
		window.open(`${gop}.download_container_template`);
	});
	// The Container master is Container Booking's endpoint, reused as-is: same tanks, and
	// scoped to the principal the operator is looking at right now — not the one the form
	// carried when the dialog opened.
	d.add_custom_action(__("Download Master Container"), () => {
		const owner = d.get_value("principal") || frm.doc.principal;
		const q = owner ? `?principal=${encodeURIComponent(owner)}` : "";
		window.open(`${bkg}.download_container_master${q}`);
	});
	d.show();
}

function apply_import(frm, res, replace) {
	const rows = res.rows || [];
	if (replace) frm.clear_table("containers");
	// Skip containers already on the grid (the server refuses a duplicate on save anyway).
	const existing = new Set();
	(frm.doc.containers || []).forEach((r) => {
		if (r.container) existing.add(r.container);
	});
	let added = 0;
	let skipped = 0;
	rows.forEach((ln) => {
		if (existing.has(ln.container)) {
			skipped++;
			return;
		}
		const row = frm.add_child("containers");
		row.container = ln.container;
		row.container_no = ln.container_no;
		row.target_lift_on = ln.target_lift_on;
		row.remark = ln.remark;
		row.is_new_container = ln.is_new ? 1 : 0;
		existing.add(ln.container);
		added++;
	});
	frm.refresh_field("containers");

	let msg = __("{0} baris ditambahkan.", [added]);
	if (skipped) msg += " " + __("{0} sudah ada di grid, dilewati.", [skipped]);
	// Same three outcomes a booking import names, in the same order.
	const notes = [];
	// Registering a Container master is the one thing an import does outside this plan, so
	// the numbers it created are named first and by name — a typo caught here costs nothing,
	// one found later is a phantom tank.
	const created = res.created || [];
	if (created.length) {
		notes.push(
			"<b>" +
				__("Baru didaftarkan ({0}):", [created.length]) +
				"</b><br>" +
				created.join(", ") +
				'<br><span class="text-muted">' +
				__("Cek ejaannya — hapus barisnya kalau salah ketik.") +
				"</span>"
		);
	}
	const unknown = res.unknown || [];
	if (unknown.length) {
		notes.push(
			"<b>" +
				__("Tidak dikenal — dilewati ({0}):", [unknown.length]) +
				"</b><br>" +
				unknown.join(", ") +
				'<br><span class="text-muted">' +
				__("Daftarkan di master Container dulu.") +
				"</span>"
		);
	}
	const warns = res.errors || [];
	if (warns.length) notes.push("<b>" + __("Tidak diimport:") + "</b><br>" + warns.join("<br>"));
	if (notes.length) {
		frappe.msgprint({
			title: __("Catatan import"),
			message: msg + "<br><br>" + notes.join("<br><br>"),
			indicator: "orange",
		});
	} else {
		frappe.show_alert({ message: msg, indicator: "green" });
	}
}
