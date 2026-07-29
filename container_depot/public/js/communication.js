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
	{ key: "Gate Out", doctype: "Gate Out Plan", label: __("Gate Out") },
];

function open_prefilled(doctype, values) {
	frappe.model.with_doctype(doctype, () => {
		const doc = frappe.model.get_new_doc(doctype);
		Object.assign(doc, values || {});
		frappe.set_route("Form", doctype, doc.name);
	});
}

// --- Orders made from this email -------------------------------------------------
// The `reff_email` link was only readable from the order side, so the email itself could
// not say whether it had already been turned into work. This lists them at the top of the
// email — newest first, with the state each one is in — and each row routes to the order.
//
// Shown even when there is nothing yet: "belum ada order" is the answer an operator opens
// the email to get, and a card that only exists sometimes is a card nobody looks for.
//
// Rendered as a dashboard section with the standard `custom` class: the form's refresh
// wipes those before running this handler, so re-adding here can never stack up.
const LINKED_SECTION = "custom oak-email-orders";

function order_row(o) {
	const esc = frappe.utils.escape_html;
	const subtitle = [__(o.doctype), o.subtitle].filter(Boolean).map(esc).join(" · ");
	// get_form_link builds the desk's own route, so the link survives wherever the desk is
	// mounted — and being a real <a>, it can also be opened in a new tab.
	const link = frappe.utils.get_form_link(o.doctype, o.name, true, esc(o.name));
	return `
		<div class="flex justify-between align-center py-2 border-bottom">
			<div class="ellipsis">
				<div class="bold">${link}</div>
				<div class="text-muted small ellipsis">${subtitle}</div>
			</div>
			${o.state ? `<span class="indicator-pill blue no-indicator-dot">${esc(__(o.state))}</span>` : ""}
		</div>`;
}

function empty_row() {
	return `<div class="text-muted py-2">${__("Belum ada order dari email ini. Pakai tombol Buat Order di atas.")}</div>`;
}

function show_linked_orders(frm) {
	const shown_for = frm.doc.name;
	frappe.call({
		method: "container_depot.operations.mail_to_order.linked_orders",
		args: { communication: frm.doc.name },
	}).then((r) => {
		// Stale guard: the reply can land after the form has moved to another email, and the
		// section belongs to the one it was asked for.
		if (frm.doc.name !== shown_for) return;
		const orders = r.message || [];
		frm.dashboard.parent.find(".oak-email-orders").remove();
		frm.dashboard.add_section(
			orders.length ? orders.map(order_row).join("") : empty_row(),
			__("Order dari Email Ini"),
			LINKED_SECTION
		);
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

		show_linked_orders(frm);

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
