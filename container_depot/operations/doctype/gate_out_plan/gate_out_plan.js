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

		// Optional bridge for a customer who actually proceeds to pick up: hand OAK a
		// pre-filled Container Booking (Tank Out / Lift On) carrying the plan's containers.
		// We DON'T save it — pricing / payment / customer are completed in the booking form
		// (Container Booking is priced & submittable; the plan itself has no pricing).
		if (frm.is_new() || !(frm.doc.containers || []).length) return;
		if (!frappe.model.can_create("Container Booking")) return;
		frm.add_custom_button(
			__("Container Booking (Lift On)"),
			() => make_booking(frm),
			__("Buat")
		);
	},
});

// --- Order Terkait ---------------------------------------------------------------
// The Kesiapan column says a tank is held up but not by WHAT. This names the cleaning / M&R
// orders per container, marks the ones still blocking, and links each to its form.
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
		method: "container_depot.operations.doctype.gate_out_plan.gate_out_plan.related_orders",
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
				: `<div class="text-muted small py-1">${__("Tidak ada order cleaning / M&R.")}</div>`;
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
	// Only a blocking order is coloured — a finished one is history, not a warning.
	const pill = o.blocks
		? `<span class="indicator-pill orange no-indicator-dot">${esc(o.status)}</span>`
		: `<span class="indicator-pill green no-indicator-dot">${esc(o.status)}</span>`;
	return `
		<div class="flex justify-between align-center py-1 border-bottom">
			<div class="ellipsis">${link} <span class="text-muted small">${esc(o.kind)}</span></div>
			${pill}
		</div>`;
}

function make_booking(frm) {
	frappe.model.with_doctype("Container Booking", () => {
		const doc = frappe.model.get_new_doc("Container Booking");
		// Steer the booking to the outbound flow; direction/lift_type are otherwise derived
		// from the Lift Service, which the booking auto-resolves to the Lift On item.
		doc.principal = frm.doc.principal;
		doc.depot = frm.doc.depot;
		doc.direction = "Tank Out";
		doc.lift_type = "Lift On";
		doc.reff_email = frm.doc.reff_email;
		doc.reff_doc = frm.doc.reff_doc;
		(frm.doc.containers || []).forEach((r) => {
			if (!r.container) return;
			const row = frappe.model.add_child(doc, "Container Booking Item", "items");
			row.container = r.container;
			row.container_no = r.container_no;
			row.condition = "EMPTY CLEAN";
			row.tanggal_bongkar = frappe.datetime.get_today();
		});
		frappe.set_route("Form", "Container Booking", doc.name);
		frappe.show_alert(
			{ message: __("Lengkapi Customer & Pembayaran, lalu simpan."), indicator: "blue" },
			7
		);
	});
}
