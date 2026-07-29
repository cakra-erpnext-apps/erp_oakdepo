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
