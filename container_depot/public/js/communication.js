// Email → Order.
//
// An incoming email (Communication, medium Email, Received) is the reference behind a
// booking / repair / survey / cleaning request. Here we add a "Buat Order" group on the
// Communication form: each button opens a fresh, pre-filled order form (customer resolved
// from the sender, the email copied into remarks, subject as external reference — see
// operations/mail_to_order.py). We never save on the user's behalf; they complete the
// mandatory fields (container / items) and save, so the email stays the paper trail.

const ORDER_TYPES = [
	{ key: "Booking", doctype: "Container Booking", label: __("Booking") },
	{ key: "M&R", doctype: "Repair Order", label: __("M&R") },
	{ key: "Survey", doctype: "Survey Order", label: __("Survey") },
	{ key: "Cleaning", doctype: "Cleaning Order", label: __("Cleaning") },
];

function open_prefilled(doctype, values) {
	frappe.model.with_doctype(doctype, () => {
		const doc = frappe.model.get_new_doc(doctype);
		Object.assign(doc, values || {});
		frappe.set_route("Form", doctype, doc.name);
	});
}

frappe.ui.form.on("Communication", {
	refresh(frm) {
		// Only incoming emails are an order reference.
		const is_incoming_email =
			frm.doc.communication_type === "Communication" &&
			frm.doc.communication_medium === "Email" &&
			frm.doc.sent_or_received === "Received";
		if (!is_incoming_email || frm.is_new()) return;

		for (const t of ORDER_TYPES) {
			if (!frappe.model.can_create(t.doctype)) continue;
			frm.add_custom_button(
				t.label,
				() => {
					frappe.call({
						method: "container_depot.operations.mail_to_order.get_order_prefill",
						args: { communication: frm.doc.name, order_type: t.key },
						freeze: true,
						freeze_message: __("Menyiapkan order…"),
					}).then((r) => {
						if (r.message) open_prefilled(r.message.doctype, r.message.values);
					});
				},
				__("Buat Order")
			);
		}
	},
});
