// Gate Out Plan — Desk form behaviour.
frappe.ui.form.on("Gate Out Plan", {
	setup(frm) {
		// Filter the container picker to the plan's Principal (tank owner) + Depot, so ops
		// can only list tanks that actually belong to this customer at this depot.
		frm.set_query("container", "containers", () => {
			const filters = {};
			if (frm.doc.principal) filters.principal = frm.doc.principal;
			if (frm.doc.depot) filters.depot = frm.doc.depot;
			return { filters };
		});
	},

	refresh(frm) {
		render_related_orders(frm);
		set_fulfilment_progress(frm);
		set_grid_import_button(frm);

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
		frm.add_custom_button(__("Buat Container Booking (Lift On)"), () => make_booking(frm));
	},

	principal(frm) {
		reset_containers(frm, __("Principal / Tank Owner"));
	},

	depot(frm) {
		reset_containers(frm, __("Depot"));
	},
});

// Principal and Depot scope the container picker, so changing either invalidates every row
// already listed. The table is emptied outright rather than just clearing each row's link
// (what Container Booking does): here the ROW is the tank — its target date and note only
// mean anything attached to that tank — so leaving empty rows behind would keep dates
// hanging off nothing. The server refuses a mismatched row anyway
// (``_assert_rows_match_header``); this is what keeps the operator from hitting that.
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
	// The section sits at the very top, so on a brand-new plan it would be the first thing on
	// screen with nothing in it — there are no saved containers to report on yet.
	frm.toggle_display("orders_section", !frm.is_new());
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
		field.$wrapper.html(related_orders_html(r.message || []));
	});
}

function related_orders_html(tanks) {
	const esc = frappe.utils.escape_html;
	if (!tanks.length) return `<div class="text-muted">${__("Belum ada container di plan ini.")}</div>`;

	return tanks
		.map((t) => {
			const head = [esc(t.container_no), t.target_lift_on ? `${__("Target")}: ${esc(t.target_lift_on)}` : null]
				.filter(Boolean)
				.join(" · ");
			const orders = t.orders.length
				? t.orders.map(order_line).join("")
				: `<div class="text-muted small py-1">${__("Tidak ada order cleaning / M&R atau EIR.")}</div>`;
			return `
				<div class="mb-4">
					<div class="bold mb-1">${head}</div>
					${orders}
				</div>`;
		})
		.join("");
}

function order_line(o) {
	const esc = frappe.utils.escape_html;
	// get_form_link emits this desk's own route, so the link holds wherever the desk is mounted.
	const link = frappe.utils.get_form_link(o.doctype, o.name, true, esc(o.name));
	// Orange = still holding the lift-on back. Green = finished. Grey = neither: an EIR that
	// is only a draft, or a cancelled document — history, not a warning and not a clearance.
	const tone = o.blocks ? "orange" : o.done ? "green" : "gray";
	const pill = `<span class="indicator-pill ${tone} no-indicator-dot">${esc(o.status)}</span>`;
	return `
		<div class="flex justify-between align-center py-1 border-bottom">
			<div class="ellipsis">${link} <span class="text-muted small">${esc(o.kind)}</span></div>
			${pill}
		</div>`;
}

function make_booking(frm) {
	// Mapped server-side (see ``make_container_booking``): the booking line's condition and
	// cargo are read off each tank, which the browser cannot do, and the rows that already
	// gated out are dropped there rather than filtered in two places.
	// Tick rows in the Container grid first to book only those (open_mapped_doc passes the
	// selection through) — a plan is often collected in more than one visit.
	frappe.model
		.open_mapped_doc({
			method: "container_depot.container_depot.doctype.gate_out_plan.gate_out_plan.make_container_booking",
			frm,
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

function import_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Import Container dari Excel"),
		fields: [
			{
				fieldname: "hint",
				fieldtype: "HTML",
				options: `<p class="text-muted small">${__(
					"Kolom: Container, Target Lift-On (YYYY-MM-DD), Catatan (opsional). Baris header dilewati. Container yang belum ada di master Container dilewati dan dilaporkan — daftarkan dulu di master. Tank milik principal lain atau di depo lain juga ditolak."
				)}</p>`,
			},
			{ fieldname: "file", fieldtype: "Attach", label: __("File Excel (.xlsx)"), reqd: 1 },
			{ fieldname: "replace", fieldtype: "Check", label: __("Ganti baris yang sudah ada") },
		],
		primary_action_label: __("Import"),
		primary_action(values) {
			frappe.call({
				method: "container_depot.container_depot.doctype.gate_out_plan.gate_out_plan.parse_container_xlsx",
				args: {
					file_url: values.file,
					principal: frm.doc.principal || null,
					depot: frm.doc.depot || null,
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
	// scoped to this plan's Principal so the file lists exactly what the picker allows.
	d.add_custom_action(__("Download Master Container"), () => {
		const q = frm.doc.principal ? `?principal=${encodeURIComponent(frm.doc.principal)}` : "";
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
		existing.add(ln.container);
		added++;
	});
	frm.refresh_field("containers");

	let msg = __("{0} baris ditambahkan.", [added]);
	if (skipped) msg += " " + __("{0} sudah ada di grid, dilewati.", [skipped]);
	// Two things can go partly wrong and each is named separately: numbers the master does
	// not know (skipped outright), and rows imported with something missing.
	const notes = [];
	const unknown = res.unknown || [];
	if (unknown.length) {
		notes.push(
			"<b>" +
				__("Tidak ada di master Container — dilewati ({0}):", [unknown.length]) +
				"</b><br>" +
				unknown.join(", ") +
				'<br><span class="text-muted">' +
				__("Daftarkan dulu di master Container, lalu import ulang.") +
				"</span>"
		);
	}
	const warns = res.errors || [];
	if (warns.length) notes.push("<b>" + __("Perlu diperiksa:") + "</b><br>" + warns.join("<br>"));
	if (notes.length) {
		frappe.msgprint({
			title: __("Import selesai dengan catatan"),
			message: msg + "<br><br>" + notes.join("<br><br>"),
			indicator: "orange",
		});
	} else {
		frappe.show_alert({ message: msg, indicator: "green" });
	}
}
