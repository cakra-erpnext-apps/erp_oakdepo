// Pending Cash Refund — money going back for one party, one transfer for several Pending
// Cash. Refund Amount is the sum of the rows; what is left of each comes from the server
// (row_info), the same figure validate refuses an excess with.
const PCR = "container_depot.container_depot.doctype.pending_cash_refund.pending_cash_refund";

frappe.ui.form.on("Pending Cash Refund", {
	setup(frm) {
		frm.set_query("bank_account", () => ({ filters: { company: frm.doc.company, is_company_account: 1, disabled: 0 } }));
		// Only what can still be refunded, and not what another row already took.
		frm.set_query("pending_cash", "allocations", () => ({
			query: `${PCR}.open_pending_cash_query`,
			filters: {
				party_type: frm.doc.party_type,
				party: frm.doc.party,
				company: frm.doc.company,
				exclude: frm.is_new() ? "" : frm.doc.name,
				chosen: (frm.doc.allocations || []).map((r) => r.pending_cash).filter(Boolean),
			},
		}));
	},

	onload(frm) {
		if (frm.is_new() && !frm.doc.company) frm.set_value("company", frappe.defaults.get_user_default("Company"));
	},

	refresh(frm) {
		// Validated or Void -> locked (the server enforces the same); Invalidate reopens it.
		const locked = !!(frm.doc.validated || frm.doc.void);
		for (const df of frm.meta.fields) {
			if (frappe.model.no_value_type.includes(df.fieldtype) || df.read_only) continue;
			frm.set_df_property(df.fieldname, "read_only", locked ? 1 : 0);
		}
		frm.set_df_property("allocations", "read_only", locked ? 1 : 0);

		if (frm.doc.void) frm.page.set_indicator(__("Void"), "gray");
		else if (frm.doc.validated) frm.page.set_indicator(__("Refunded"), "green");
		else if (!frm.is_new()) frm.page.set_indicator(__("Draft"), "orange");
		if (frm.is_new()) return;

		const act = (label, method, msg) =>
			frm.add_custom_button(label, () =>
				frappe.confirm(msg, () =>
					frappe
						.call({ method: `${PCR}.${method}`, args: { names: [frm.doc.name] }, freeze: true })
						.then((r) => {
							container_depot.pending_cash.report(r.message);
							frm.reload_doc();
						})
				)
			);
		if (!frm.doc.void) {
			if (frm.doc.validated) {
				act(__("Invalidate"), "bulk_invalidate", __("Invalidate {0}? Jurnalnya dibatalkan, dokumen kembali ke Draft.", [frm.doc.name]));
			} else {
				act(__("Validate"), "bulk_validate", __("Validate {0}? Jurnal refund diterbitkan.", [frm.doc.name]));
			}
			// Void is the trace: the journal is cancelled but kept, the number stays used.
			act(__("Void"), "bulk_void", __("Void refund {0}? Jurnalnya dibatalkan (tetap disimpan sebagai jejak).", [frm.doc.name]));
		}
		if (frm.doc.journal_entry) {
			frm.add_custom_button(__("Journal Entry"), () => frappe.set_route("Form", "Journal Entry", frm.doc.journal_entry));
		}
	},

	party_type(frm) {
		frm.set_value("party", null);
	},

	party(frm) {
		// Rows of the previous party no longer apply.
		frm.clear_table("allocations");
		frm.refresh_field("allocations");
		pcr_sum(frm);
	},
});

frappe.ui.form.on("Pending Cash Refund Allocation", {
	pending_cash(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.pending_cash) return;
		frappe.xcall(`${PCR}.row_info`, { pending_cash: row.pending_cash, exclude: frm.is_new() ? null : frm.doc.name }).then((d) => {
			frappe.model.set_value(cdt, cdn, "paid_date", d.paid_date);
			frappe.model.set_value(cdt, cdn, "outstanding", d.available || 0);
			// Warned here, next to its cause: the date was typed long before this row.
			if (frm.doc.refund_date && d.paid_date && frm.doc.refund_date < d.paid_date) {
				frappe.show_alert({
					message: __("Refund Date lebih awal dari Paid Date Pending Cash ini ({0}).", [frappe.format(d.paid_date, { fieldtype: "Date" })]),
					indicator: "orange",
				});
			}
			// Default: all of what is left; part of it is typed over.
			if (!flt(row.amount)) frappe.model.set_value(cdt, cdn, "amount", d.available || 0);
			else pcr_sum(frm);
		});
	},

	amount(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		// Capped at what is left, right where it is typed; the server refuses it too.
		if (row.outstanding && flt(row.amount) > flt(row.outstanding)) {
			frappe.show_alert({
				message: __("Refund {0} melebihi Outstanding {1} — dipotong ke sisanya.", [format_currency(row.amount), format_currency(row.outstanding)]),
				indicator: "orange",
			});
			frappe.model.set_value(cdt, cdn, "amount", row.outstanding);
			return;
		}
		pcr_sum(frm);
	},

	allocations_remove: pcr_sum,
});

function pcr_sum(frm) {
	frm.set_value("amount", (frm.doc.allocations || []).reduce((t, r) => t + flt(r.amount), 0));
}
