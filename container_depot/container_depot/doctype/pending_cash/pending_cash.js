// Pending Cash (kasbon): one button per next step, the server decides who may press it
// (pending_cash.run_action). Locked fields follow the server's lock after Validate.
// container_depot.pending_cash.run lives in public/js/pending_cash_actions.js (shared with the list).
frappe.ui.form.on("Pending Cash", {
	setup(frm) {
		frm.set_query("bank_account", () => ({
			filters: { company: frm.doc.company, is_group: 0, account_type: ["in", ["Bank", "Cash"]] },
		}));
		frm.set_query("cost_center", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
		frm.set_query("pending_cash_type", () => ({ filters: { disabled: 0 } }));
		frm.set_query("number", () => ({
			query: "container_depot.container_depot.doctype.pending_cash.pending_cash.connection_query",
			filters: { modul: frm.doc.modul },
		}));
	},

	refresh(frm) {
		const locked = frm.doc.validated && !frm.is_new();
		for (const df of frm.meta.fields) {
			if (["Section Break", "Column Break", "Tab Break"].includes(df.fieldtype)) continue;
			if (df.fieldname === "bank_account") frm.set_df_property(df.fieldname, "read_only", frm.doc.paid ? 1 : 0);
			else if (!df.read_only) frm.set_df_property(df.fieldname, "read_only", locked ? 1 : 0);
		}
		if (frm.is_new()) return;

		const act = (label, action, danger) => {
			const b = frm.add_custom_button(label, () =>
				container_depot.pending_cash.run([frm.doc.name], action, {}, () => frm.reload_doc())
			);
			if (danger) b.removeClass("btn-default").addClass("btn-danger");
		};
		if (frm.doc.void) {
			act(__("Unvoid"), "unvoid");
			return;
		}
		if (!frm.doc.validated) act(__("Validate"), "validate");
		else if (!frm.doc.paid) {
			act(__("Pay"), "pay");
			act(__("Invalidate"), "invalidate");
		} else act(__("Unpaid"), "unpaid");
		act(__("Void"), "void", true);
		if (frm.doc.journal_entry) {
			frm.add_custom_button(__("Journal Entry"), () => frappe.set_route("Form", "Journal Entry", frm.doc.journal_entry));
		}
	},

	modul(frm) {
		frm.set_value("number", null);
	},
});
