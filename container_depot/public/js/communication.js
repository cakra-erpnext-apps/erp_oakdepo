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
// not say whether it had already been turned into work. This lists them, newest first,
// with the state each one is in.
//
// Rendered as a dashboard section with the standard `custom` class: the form's refresh
// wipes those before running this handler, so re-adding here can never stack up.
const LINKED_SECTION = "custom oak-email-orders";

function order_row(o) {
	const esc = frappe.utils.escape_html;
	const route = `/app/${frappe.router.slug(o.doctype)}/${encodeURIComponent(o.name)}`;
	const subtitle = [__(o.doctype), o.subtitle].filter(Boolean).map(esc).join(" · ");
	return `
		<div class="flex items-center justify-between py-2 border-bottom">
			<div class="ellipsis">
				<a href="${route}" class="bold">${esc(o.name)}</a>
				<div class="text-muted small ellipsis">${subtitle}</div>
			</div>
			${o.state ? `<span class="indicator-pill no-indicator-dot whitespace-nowrap">${esc(__(o.state))}</span>` : ""}
		</div>`;
}

function show_linked_orders(frm) {
	frappe.call({
		method: "container_depot.operations.mail_to_order.linked_orders",
		args: { communication: frm.doc.name },
	}).then((r) => {
		const orders = r.message || [];
		// Stale guard: an async reply that lands after the user has routed away, or after a
		// second refresh already drew the section.
		if (frm.doc.name !== frappe.get_route()[2]) return;
		frm.dashboard.parent.find(".oak-email-orders").remove();
		if (!orders.length) return;
		frm.dashboard.add_section(orders.map(order_row).join(""), __("Order dari Email Ini"), LINKED_SECTION);
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
