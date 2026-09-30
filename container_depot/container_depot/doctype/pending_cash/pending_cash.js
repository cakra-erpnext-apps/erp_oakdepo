// Pending Cash — erp_cakra's form. The actions and their dialogs are in
// public/js/pending_cash_actions.js (shared with the list); the server decides who may run them.

frappe.ui.form.on("Pending Cash", {
	setup(frm) {
		frm.set_query("cost_center", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
		frm.set_query("pending_cash_type", () => ({ filters: { disabled: 0 } }));
		// The party's own documents where the document names one (the server checks it too).
		frm.set_query("number", () => ({
			query: "container_depot.container_depot.doctype.pending_cash.pending_cash.connection_query",
			filters: { modul: frm.doc.modul, pay_to: frm.doc.pay_to, receive_from: frm.doc.receive_from },
		}));
	},

	onload(frm) {
		// Company is hidden but required, and the browser's mandatory check runs before the
		// server could fill it; the same goes for the company's default Cost Center.
		if (!frm.is_new()) return;
		if (!frm.doc.company) frm.set_value("company", frappe.defaults.get_user_default("Company"));
		if (!frm.doc.cost_center && frm.doc.company) {
			frappe.db.get_value("Company", frm.doc.company, "cost_center").then((r) => {
				if (r.message && r.message.cost_center && !frm.doc.cost_center) frm.set_value("cost_center", r.message.cost_center);
			});
		}
	},

	refresh(frm) {
		pc_lock(frm);
		pc_wide_column(frm);
		pc_state(frm);
		pc_refunds(frm);
	},

	total: pc_net,
	admin_fee: pc_net,
	stamp_duty: pc_net,

	modul(frm) {
		frm.set_value("number", null);
		frm.set_value("connection_party", null);
	},

	number(frm) {
		if (!frm.doc.modul || !frm.doc.number) return frm.set_value("connection_party", null);
		frappe
			.xcall("container_depot.container_depot.doctype.pending_cash.pending_cash.get_connection_party", {
				modul: frm.doc.modul,
				number: frm.doc.number,
			})
			.then((party) => frm.set_value("connection_party", party || null));
	},
});

// Validated -> the content is what was approved (the server enforces the same). Bank Account
// is chosen in the Pay dialog.
function pc_lock(frm) {
	const locked = frm.doc.validated && !frm.doc.void && !frm.is_new();
	for (const df of frm.meta.fields) {
		if (frappe.model.no_value_type.includes(df.fieldtype) || df.read_only) continue;
		frm.set_df_property(df.fieldname, "read_only", locked && df.fieldname !== "confidential" ? 1 : 0);
	}
}

// Net = what the bank moves: a kasbon costs the charges on top, a deposit arrives less them.
function pc_net(frm) {
	const charges = flt(frm.doc.admin_fee) + flt(frm.doc.stamp_duty);
	frm.set_value("net_amount_paid", flt(frm.doc.total) + (frm.doc.direction === "Cash Inflow" ? -charges : charges));
}

function pc_state(frm) {
	// The Status section is hidden: the state is the header indicator and the buttons.
	const d = frm.doc;
	if (d.void) frm.page.set_indicator(__("Void"), "gray");
	else if (d.paid && d.settled) frm.page.set_indicator(__("Completed"), "purple");
	else if (d.paid) frm.page.set_indicator(__("Paid"), "green");
	else if (d.validated) frm.page.set_indicator(__("Validated"), "blue");
	else if (!frm.is_new()) frm.page.set_indicator(__("Draft"), "orange");
	if (frm.is_new()) return;

	const run = (kind) => () => container_depot.pending_cash.run(kind, [d], () => frm.reload_doc());
	// A deposit is received, not paid out.
	const pay = d.direction === "Cash Inflow" ? __("Receive") : __("Pay");
	if (d.void) {
		frm.add_custom_button(__("Unvoid"), run("void"));
	} else {
		// Paid stands on Validated: while it is Paid, Invalidate waits for Unpaid.
		if (!d.paid) frm.add_custom_button(d.validated ? __("Invalidate") : __("Validate"), run("validate"));
		// Offered from Draft: paying a draft validates it in the same step.
		frm.add_custom_button(d.paid ? __("Unpaid") : pay, run("pay"));
		if (!d.paid) frm.add_custom_button(__("Void"), run("void"));
		// Refund may repeat, each one its own document; offered only while something is left.
		if (d.paid && !d.dont_post_to_gl) {
			frappe
				.xcall("container_depot.container_depot.doctype.pending_cash.pending_cash.get_available", { pending_cash: d.name })
				.then((left) => flt(left) > 0 && frm.add_custom_button(__("Refund"), run("refund")));
		}
	}
	if (d.journal_entry) {
		frm.add_custom_button(__("Journal Entry"), () => frappe.set_route("Form", "Journal Entry", d.journal_entry));
	}
}

// The refunds of this Pending Cash, voided ones struck through.
function pc_refunds(frm) {
	const field = frm.get_field("refund_table");
	if (frm.is_new() || !frm.doc.paid) return;
	frappe
		.xcall("container_depot.container_depot.doctype.pending_cash.pending_cash.get_refunds", { pending_cash: frm.doc.name })
		.then((rows) => {
			frm.toggle_display("sb_refund", !!(rows && rows.length));
			if (!rows || !rows.length) return;
			const esc = frappe.utils.escape_html;
			const state = (r) => (r.void ? __("Void") : r.validated ? __("Refunded") : __("Draft"));
			const body = rows
				.map(
					(r) => `<tr style="${r.void ? "text-decoration: line-through; color: var(--text-muted)" : ""}">
						<td><a href="/app/pending-cash-refund/${encodeURIComponent(r.parent)}">${esc(r.parent)}</a></td>
						<td>${frappe.format(r.refund_date, { fieldtype: "Date" })}</td>
						<td>${esc(r.bank_account || "")}</td>
						<td class="text-right">${format_currency(r.amount)}</td>
						<td>${state(r)}</td>
						<td>${esc(r.remark || "")}</td>
					</tr>`
				)
				.join("");
			field.$wrapper.html(`<table class="table table-bordered table-sm">
				<thead><tr><th>${__("Refund")}</th><th>${__("Refund Date")}</th><th>${__("Refund To Bank")}</th>
				<th class="text-right">${__("Amount")}</th><th>${__("Status")}</th><th>${__("Note")}</th></tr></thead>
				<tbody>${body}</tbody></table>`);
		});
}

// A form column is always an equal share of its section, stacked top to bottom. The third
// column (party, amount, charges, net) needs more room and Materai beside Admin Charge, as in
// erp_cakra: it is widened over the empty fourth column and wrapped.
// ponytail: widening covers the fourth column; lay it out again if that column gets fields.
function pc_wide_column(frm) {
	if (!document.getElementById("pc-wide-style")) {
		const el = document.createElement("style");
		el.id = "pc-wide-style";
		el.textContent = `
		.pc-wide-col { position: relative; z-index: 1; }
		.pc-wide-col > form { width: 205%; display: flex; flex-wrap: wrap; align-items: flex-start; }
		.pc-wide-col > form > .frappe-control { flex: 0 0 100%; }
		.pc-wide-col > form > .frappe-control[data-fieldname="stamp_duty"],
		.pc-wide-col > form > .frappe-control[data-fieldname="admin_fee"] { flex: 0 0 50%; }
		.pc-wide-col > form > .frappe-control[data-fieldname="stamp_duty"] { padding-right: 15px; }
		@media (max-width: 767px) { .pc-wide-col > form { width: 100%; } }`;
		document.head.appendChild(el);
	}
	const col = frm.get_field("total") && frm.get_field("total").$wrapper.closest(".form-column");
	if (col) col.addClass("pc-wide-col");
}
