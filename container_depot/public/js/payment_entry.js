// Payment Entry, the erp_cakra way (server side: container_depot/payment_entry.py).
//
// The Dokumen / Item grid is where a payment is filled: "Ambil Dokumen" picks the party's
// outstanding invoices; in Expense / Income mode each row is an account + amount instead.
// The native references and the deduction rows are derived from it on save; the totals
// below only preview what the server will write.
const PE_METHOD = "container_depot.payment_entry.";

// A "Settlement" payment has no bank: its account is picked on the form. ERPNext's own
// mode-of-payment handler would demand a default Cash/Bank account for it and throw.
if (erpnext.accounts && erpnext.accounts.pos && !erpnext.accounts.pos.__depot_settlement) {
	const original = erpnext.accounts.pos.get_payment_mode_account;
	erpnext.accounts.pos.get_payment_mode_account = function (frm, mode_of_payment, callback) {
		if ((mode_of_payment || "").toLowerCase() === "settlement") return;
		return original.apply(this, arguments);
	};
	erpnext.accounts.pos.__depot_settlement = true;
}

function pe_smart(raw, base) {
	const [mode, num] = container_depot.parse_smart(raw);
	return mode === "pct" ? (flt(base) * num) / 100 : num;
}

// Preview only: the server recomputes the same numbers (payment_entry._apply_amounts).
function pe_totals(frm) {
	if (frm.doc.docstatus !== 0) return;
	const lines = frm.doc.depot_lines || [];
	const alloc = lines.reduce((s, r) => s + flt(r.amount || r.outstanding), 0);
	if (!lines.length) return;
	const pay = frm.doc.payment_type === "Pay";
	const notes = lines.reduce((s, r) => s + flt(r.credit_amount) - flt(r.debit_amount), 0);
	const comp =
		pe_smart(frm.doc.depot_tax_input, alloc) +
		flt(frm.doc.depot_materai) +
		flt(frm.doc.depot_admin_fee) +
		(pay ? -1 : 1) * pe_smart(frm.doc.depot_pph_input, alloc);
	const amount = pay ? alloc + notes + comp : alloc + notes - comp;
	frm.set_value("depot_allocated", alloc);
	if (frm.doc.paid_from_account_currency === frm.doc.paid_to_account_currency) {
		frm.set_value("paid_amount", amount);
	}
}

function toggle_direct(frm) {
	const direct = !!frm.doc.depot_direct;
	["party_type", "party", "party_name", "party_balance", "party_bank_account", "contact_person", "contact_email"].forEach(
		(f) => frm.toggle_display(f, !direct)
	);
	const grid = frm.get_field("depot_lines").grid;
	grid.cannot_add_rows = !direct; // document rows come from "Ambil Dokumen" only
	grid.refresh();
}

function pick_documents(frm) {
	const exclude = (frm.doc.depot_lines || []).map((r) => r.document_no).filter(Boolean);
	frappe
		.call(PE_METHOD + "get_payment_documents", {
			party_type: frm.doc.party_type,
			party: frm.doc.party,
			company: frm.doc.company,
			payment_type: frm.doc.payment_type,
			exclude: JSON.stringify(exclude),
		})
		.then((r) => {
			const rows = r.message || [];
			if (!rows.length) {
				frappe.msgprint(__("Tidak ada dokumen outstanding untuk {0}.", [frm.doc.party]));
				return;
			}
			pick_dialog(
				__("Ambil Dokumen · {0}", [frm.doc.party]),
				rows,
				[
					[__("Dokumen"), (r) => `<b>${r.document_no}</b><div class="text-muted small">${r.doc_label}</div>`],
					[__("Tanggal"), (r) => frappe.datetime.str_to_user(r.date)],
					[__("Total"), (r) => format_currency(r.grand_total, r.currency), "right"],
					[__("Sisa"), (r) => format_currency(r.outstanding, r.currency), "right"],
				],
				(picked) => {
					for (const d of picked) {
						frm.add_child("depot_lines", {
							document_type: d.document_type,
							doc_label: d.doc_label,
							document_no: d.document_no,
							date: d.date,
							grand_total: d.grand_total,
							outstanding: d.outstanding,
							amount: d.outstanding,
						});
					}
					frm.refresh_field("depot_lines");
					pe_totals(frm);
				}
			);
		});
}

function pick_kasbon(frm) {
	const exclude = (frm.doc.depot_kasbon || []).map((r) => r.pending_cash).filter(Boolean);
	const load = (supplier) =>
		frappe.call(PE_METHOD + "get_kasbon", {
			supplier: supplier || null,
			company: frm.doc.company,
			exclude: JSON.stringify(exclude),
			exclude_parent: frm.is_new() ? null : frm.doc.name,
		});
	// The kasbon recipient is often not the party being paid (an employee settling a
	// supplier's bill), so the filter starts empty rather than at the payment's party.
	load(null).then((r) => {
		const rows = r.message || [];
		if (!rows.length) {
			frappe.msgprint(__("Tidak ada kasbon Paid yang masih tersisa."));
			return;
		}
		pick_dialog(
			__("Ambil Kasbon"),
			rows,
			[
				[__("Kasbon"), (r) => `<b>${r.name}</b><div class="text-muted small">${frappe.utils.escape_html(r.pay_to)}</div>`],
				[__("Dibayar"), (r) => frappe.datetime.str_to_user(r.paid_date)],
				[__("Nominal"), (r) => format_currency(r.total), "right"],
				[__("Sisa"), (r) => format_currency(r.outstanding), "right"],
			],
			(picked) => {
				for (const k of picked) {
					frm.add_child("depot_kasbon", {
						pending_cash: k.name,
						pay_to: k.pay_to,
						grand_total: k.total,
						outstanding: k.outstanding,
						allocated: k.outstanding,
					});
				}
				frm.refresh_field("depot_kasbon");
			}
		);
	});
}

// A tick-list over already-fetched rows. Small by nature (one party's open documents).
function pick_dialog(title, rows, columns, on_pick) {
	const head = columns.map(([label, , align]) => `<th style="text-align:${align || "left"}">${label}</th>`).join("");
	const body = rows
		.map(
			(r, i) =>
				`<tr><td><input type="checkbox" class="depot-pick" data-i="${i}"></td>` +
				columns.map(([, cell, align]) => `<td style="text-align:${align || "left"}">${cell(r)}</td>`).join("") +
				"</tr>"
		)
		.join("");
	const d = new frappe.ui.Dialog({
		title,
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "list",
				options: `<div style="max-height:380px;overflow:auto;">
					<table class="table table-condensed"><thead><tr>
						<th><input type="checkbox" class="depot-pick-all"></th>${head}
					</tr></thead><tbody>${body}</tbody></table></div>`,
			},
		],
		primary_action_label: __("Tambahkan"),
		primary_action() {
			const picked = d.$wrapper
				.find(".depot-pick:checked")
				.map((_, el) => rows[$(el).data("i")])
				.get();
			d.hide();
			if (picked.length) on_pick(picked);
		},
	});
	d.$wrapper.on("change", ".depot-pick-all", function () {
		d.$wrapper.find(".depot-pick").prop("checked", $(this).prop("checked"));
	});
	d.show();
}

frappe.ui.form.on("Payment Entry", {
	setup(frm) {
		const company_account = () => ({ filters: { company: frm.doc.company, is_group: 0 } });
		frm.set_query("depot_settlement_account", company_account);
		frm.set_query("account", "depot_lines", company_account);
		frm.set_query("credit_account", "depot_lines", company_account);
		frm.set_query("debit_account", "depot_lines", company_account);
		frm.set_query("cost_center", "depot_lines", company_account);
		frm.set_query("pending_cash", "depot_kasbon", () => ({ filters: { paid: 1, void: 0, company: frm.doc.company } }));
	},
	refresh: toggle_direct,
	depot_direct(frm) {
		if (frm.doc.depot_direct) {
			frm.set_value({ party_type: null, party: null });
			frm.clear_table("references");
		}
		frm.clear_table("depot_lines");
		frm.refresh_fields();
		toggle_direct(frm);
	},
	depot_get_items: pick_documents,
	depot_get_kasbon: pick_kasbon,
	depot_tax_input: pe_totals,
	depot_pph_input: pe_totals,
	depot_materai: pe_totals,
	depot_admin_fee: pe_totals,
	party(frm) {
		// Another party's documents cannot be paid on this one.
		if ((frm.doc.depot_lines || []).some((r) => r.document_no)) {
			frm.set_value("depot_lines", (frm.doc.depot_lines || []).filter((r) => !r.document_no));
		}
	},
});

frappe.ui.form.on("Payment Entry Line", {
	amount: pe_totals,
	credit_amount: pe_totals,
	debit_amount: pe_totals,
	depot_lines_remove: pe_totals,
});
