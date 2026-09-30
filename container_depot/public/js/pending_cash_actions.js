// Pending Cash actions, shared by the form, the list and the refund list (hooks doctype_js /
// doctype_list_js). The erp_cakra way: every action — one document or a list selection —
// goes through one confirmation that names the documents; Pay asks for the Bank Account and
// the date, Refund for the date and, on one document, the amount.
frappe.provide("container_depot.pending_cash");

// Each pair is the exact undo of the other; which way it goes follows each document's state.
const PC_TOGGLE = {
	validate: (d) => (d.validated ? "invalidate" : "validate"),
	pay: (d) => (d.paid ? "unpaid" : "pay"),
	void: (d) => (d.void ? "unvoid" : "void"),
};

const PC_ACTIONS = {
	validate: { verb: () => __("Validate"), note: () => __("Setelah Validate, isi dokumen terkunci. <b>Bank Account</b> dipilih saat Pay.") },
	invalidate: { verb: () => __("Invalidate"), note: () => __("Dokumen kembali ke <b>Draft</b> dan isinya bisa direvisi lagi.") },
	// A deposit is received, not paid out.
	pay: {
		verb: (single) => (single && single.direction === "Cash Inflow" ? __("Receive") : __("Pay")),
		pay: true,
		note: () => __("Dokumen yang masih <b>Draft</b> ikut di-Validate di langkah ini."),
	},
	unpaid: {
		verb: () => __("Unpaid"),
		note: () => __("<b>Journal Entry</b>-nya dibatalkan dan dokumen kembali ke <b>Validated</b>. Untuk merevisi isinya, lanjutkan dengan <b>Invalidate</b>."),
	},
	void: { verb: () => __("Void"), note: () => __("Hanya untuk yang belum Paid. Yang sudah Paid: <b>Unpaid</b> dulu, atau <b>Refund</b>.") },
	unvoid: { verb: () => __("Unvoid"), note: () => __("Dokumen yang statusnya Paid mendapat <b>Journal Entry</b> baru.") },
	refund: {
		verb: () => __("Refund"),
		refund: true,
		note: () =>
			__("Dibuat dokumen <b>Pending Cash Refund</b> (draft) bernomor sendiri. Jurnalnya terbit saat refund itu di-Validate, bertanggal refund — jurnal Paid tidak disentuh."),
	},
};

// A list cell holding several document numbers: the first one and "+N", all of them in the
// tooltip; the link opens every one of them.
container_depot.pending_cash.doc_links = function (value, doctype) {
	const names = String(value == null ? "" : value)
		.split(",")
		.map((x) => x.trim())
		.filter(Boolean);
	if (!names.length) return "<span></span>";
	const href = `/app/${frappe.router.slug(doctype)}?name=${encodeURIComponent(JSON.stringify(["in", names]))}`;
	const esc = frappe.utils.escape_html;
	const more = names.length > 1 ? `<span class="text-muted"> +${names.length - 1}</span>` : "";
	return `<a href="${href}" title="${esc(names.join(", "))}">${esc(names[0])}${more}</a>`;
};

container_depot.pending_cash.report = function (out) {
	if (!out) return;
	if (out.done && out.done.length) {
		frappe.show_alert({ message: __("{0} dokumen diproses", [out.done.length]), indicator: "green" });
	}
	if (out.failed && out.failed.length) {
		frappe.msgprint({
			title: __("Tidak Diproses"),
			indicator: "red",
			message: out.failed.map((f) => `<b>${f.name}</b>: ${frappe.utils.escape_html(f.error)}`).join("<br>"),
		});
	}
};

// kind = a PC_TOGGLE pair ("validate" | "pay" | "void") or a lone action ("refund").
// docs = the selected documents (name + validated / paid / void; the form sends [frm.doc]).
container_depot.pending_cash.run = function (kind, docs, done) {
	if (!(docs || []).length) {
		frappe.msgprint(__("Pilih dulu Pending Cash yang mau diproses."));
		return;
	}
	const groups = {};
	docs.forEach((d) => {
		const action = PC_TOGGLE[kind] ? PC_TOGGLE[kind](d) : kind;
		(groups[action] = groups[action] || []).push(d.name);
	});
	confirm_actions(groups, docs.length === 1 ? docs[0] : null, done);
};

function confirm_actions(groups, single, done) {
	const actions = Object.keys(groups);
	const esc = frappe.utils.escape_html;
	const body = actions
		.map((action) => {
			const a = PC_ACTIONS[action];
			return `<p>${__("Apakah Anda yakin ingin {0} Pending Cash di bawah ini?", [`<b>${a.verb(single)}</b>`])}</p>
				<ul>${groups[action].map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
				<p class="text-muted small">${a.note()}</p>`;
		})
		.join("<hr>");
	const fields = [{ fieldtype: "HTML", options: body }];
	if (actions.some((a) => PC_ACTIONS[a].pay)) {
		const today = frappe.datetime.get_today();
		fields.push(
			{ fieldtype: "Section Break" },
			{
				fieldtype: "Link",
				fieldname: "bank_account",
				label: __("Bank Account"),
				options: "Bank Account",
				reqd: 1,
				default: single && single.bank_account,
				get_query: () => ({
					filters: Object.assign({ is_company_account: 1, disabled: 0 }, single && single.company ? { company: single.company } : {}),
				}),
			},
			{ fieldtype: "Column Break" },
			// Not before the document: its journal cannot precede the Pending Cash it comes from.
			{ fieldtype: "Date", fieldname: "paid_date", label: __("Paid Date"), reqd: 1, default: single && single.date > today ? single.date : today },
			{ fieldtype: "Section Break" },
			{ fieldtype: "Small Text", fieldname: "paid_notes", label: __("Paid Notes") }
		);
	}
	if (actions.some((a) => PC_ACTIONS[a].refund)) {
		fields.push(
			{ fieldtype: "Section Break" },
			{ fieldtype: "Date", fieldname: "refund_date", label: __("Refund Date"), reqd: 1, default: frappe.datetime.get_today() },
			// One document only: what is left differs per document, so a list refund returns all of it.
			...(single
				? [{ fieldtype: "Currency", fieldname: "amount", label: __("Amount"), description: __("Kosongkan untuk mengembalikan seluruh sisa.") }]
				: []),
			{ fieldtype: "Data", fieldname: "remark", label: __("Remark") }
		);
	}
	const verb = actions.length === 1 ? PC_ACTIONS[actions[0]].verb(single) : __("Proses");
	const d = new frappe.ui.Dialog({
		title: actions.length === 1 ? verb : __("Pending Cash"),
		fields,
		primary_action_label: verb,
		primary_action(values) {
			d.hide();
			run_actions(groups, values || {}, done);
		},
	});
	d.show();
	// Pay: the default bank's company account when the document has none yet.
	if (actions.includes("pay") && !d.get_value("bank_account")) {
		frappe.db
			.get_value("Bank Account", Object.assign({ is_company_account: 1, disabled: 0, is_default: 1 }, single && single.company ? { company: single.company } : {}), "name")
			.then((r) => r.message && r.message.name && !d.get_value("bank_account") && d.set_value("bank_account", r.message.name));
	}
}

// One group after the other, never in parallel: two actions on one document both touch its journal.
function run_actions(groups, values, done) {
	const merged = { done: [], failed: [], created: [] };
	let chain = Promise.resolve();
	Object.keys(groups).forEach((action) => {
		chain = chain.then(() =>
			frappe
				.call({
					method: "container_depot.container_depot.doctype.pending_cash.pending_cash.run_action",
					args: { names: JSON.stringify(groups[action]), action, ...values },
					freeze: true,
					freeze_message: __("{0}...", [PC_ACTIONS[action].verb()]),
				})
				.then((r) => {
					const m = r.message || {};
					merged.done.push(...(m.done || []));
					merged.failed.push(...(m.failed || []));
					merged.created.push(...(m.created || []));
				})
		);
	});
	chain.then(() => {
		container_depot.pending_cash.report(merged);
		// One refund made from a form: open it, its journal is posted there.
		if (merged.created.length === 1) frappe.set_route("Form", "Pending Cash Refund", merged.created[0]);
		else done && done(merged);
	});
}
