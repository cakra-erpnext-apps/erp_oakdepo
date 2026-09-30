// Payment Entry, the erp_cakra way (server side: container_depot/payment_entry.py; layout:
// install.PAYMENT_FORM).
//
// The Payment Item grid is where a payment is filled: "Add Items" picks the party's
// outstanding invoices; in Expense / Income mode each row is an account + amount instead.
// The native references and the deduction rows are derived from it on save. The amount is
// the user's: typed, or set by the Pay / Receive button beside it; the server fills an empty
// one.
const PE_METHOD = "container_depot.payment_entry.";

// On a Payment Entry the bank side comes from the Bank field (or the Settlement Account), not
// from the mode of payment: ERPNext's own handler would demand a default Cash/Bank account on
// every mode of payment and throw. payment_entry._fill_bank_side still falls back to it.
if (erpnext.accounts && erpnext.accounts.pos && !erpnext.accounts.pos.__depot_settlement) {
	const original = erpnext.accounts.pos.get_payment_mode_account;
	erpnext.accounts.pos.get_payment_mode_account = function (frm, mode_of_payment, callback) {
		if (frm && frm.doctype === "Payment Entry") return;
		return original.apply(this, arguments);
	};
	erpnext.accounts.pos.__depot_settlement = true;
}

// ERPNext re-shows these on every currency / amount change, and makes the cheque fields
// mandatory for a Bank account. The form is install.PAYMENT_FORM: they stay down, and
// payment_entry.py fills what they hold.
const PE_NATIVE_HIDDEN = [
	"source_exchange_rate", "target_exchange_rate", "base_paid_amount", "base_received_amount",
	"base_total_taxes_and_charges", "received_amount", "base_total_allocated_amount",
	"write_off_difference_amount", "party_type",
];
const PE_NOT_REQUIRED = ["reference_no", "reference_date", "paid_from", "paid_to"];

function pe_is_settlement(frm) {
	return (frm.doc.mode_of_payment || "").trim().toLowerCase() === "settlement";
}

function pe_currency(frm) {
	return (
		frm.doc.paid_from_account_currency ||
		(frm.doc.company && frappe.get_doc(":Company", frm.doc.company)?.default_currency) ||
		frappe.boot.sysdefaults.currency
	);
}

function pe_hide_native(frm) {
	PE_NATIVE_HIDDEN.forEach((f) => frm.fields_dict[f] && frm.toggle_display(f, false));
	PE_NOT_REQUIRED.forEach((f) => frm.fields_dict[f] && frm.toggle_reqd(f, false));
}

function pe_labels(frm) {
	const receive = frm.doc.payment_type === "Receive";
	const cur = pe_currency(frm);
	frm.set_df_property("party", "label", receive ? __("Received From") : __("Pay To"));
	frm.set_df_property("paid_amount", "label", `${receive ? __("Amount Received") : __("Amount Paid")} (${cur})`);
	frm.set_df_property("depot_allocated", "label", `${__("Item Total Amount")} (${cur})`);
}

// Party Type follows the direction and is not shown: the user only picks the party.
function pe_party_type(frm) {
	if (frm.doc.depot_direct || frm.doc.docstatus !== 0) return;
	const want = frm.doc.payment_type === "Receive" ? "Customer" : "Supplier";
	if (["Pay", "Receive"].includes(frm.doc.payment_type) && frm.doc.party_type !== want) {
		frm.set_value("party_type", want);
	}
}

// One grid, two modes (erp_cakra's Payment Entry Items): the invoices being settled, or in
// Expense / Income the accounts paid. Ten column units, the most a Frappe grid lays out.
function pe_items_columns(frm) {
	const grid = frm.fields_dict.depot_lines && frm.fields_dict.depot_lines.grid;
	if (!grid) return;
	const direct = !!frm.doc.depot_direct;
	const cols = direct
		? { description: 3, account: 3, amount: 2, remark: 2 }
		: { document_no: 2, date: 1, grand_total: 1, outstanding: 1, amount: 2, credit_amount: 1, debit_amount: 1, remark: 1 };
	for (const df of grid.docfields) {
		grid.update_docfield_property(df.fieldname, "in_list_view", cols[df.fieldname] ? 1 : 0);
		if (cols[df.fieldname]) grid.update_docfield_property(df.fieldname, "columns", cols[df.fieldname]);
	}
	grid.update_docfield_property("amount", "label", direct ? __("Amount") : __("Allocated Amount"));
	grid.cannot_add_rows = !direct; // invoice rows come from "Add Items" only
	grid.visible_columns = undefined;
	grid.setup_visible_columns();
	grid.wrapper.find(".grid-body .rows").empty();
	grid.grid_rows = [];
	grid.grid_rows_by_docname = {};
	grid.refresh();
}

function pe_toggle(frm) {
	const direct = !!frm.doc.depot_direct;
	["party", "party_name", "party_balance"].forEach((f) => frm.fields_dict[f] && frm.toggle_display(f, !direct));
	// Pending Cash rows name their party: the kasbon's recipient on a Pay, the depositing
	// customer on a Receive.
	const kasbon = frm.fields_dict.depot_kasbon && frm.fields_dict.depot_kasbon.grid;
	if (kasbon) {
		const receive = frm.doc.payment_type === "Receive";
		kasbon.update_docfield_property("pay_to", "in_list_view", receive ? 0 : 1);
		kasbon.update_docfield_property("customer", "in_list_view", receive ? 1 : 0);
		kasbon.update_docfield_property("customer", "columns", 2);
		kasbon.visible_columns = undefined;
		kasbon.setup_visible_columns();
		kasbon.wrapper.find(".grid-body .rows").empty();
		kasbon.grid_rows = [];
		kasbon.grid_rows_by_docname = {};
	}
	for (const table of ["depot_kasbon", "depot_advance"]) {
		const grid = frm.fields_dict[table] && frm.fields_dict[table].grid;
		if (!grid) continue;
		grid.cannot_add_rows = true; // rows come from "Add Pending Cash" / "Add Purchase Order" only
		grid.refresh();
	}
	pe_items_columns(frm);
	pe_labels(frm);
	pe_hide_native(frm);
}

// ---- Bank -> its company Bank Account -> the bank side ---------------------------------
function pe_apply_bank(frm) {
	if (!frm.doc.depot_bank) return;
	frappe.db
		.get_value("Bank Account", { bank: frm.doc.depot_bank, company: frm.doc.company, is_company_account: 1, disabled: 0 }, ["name", "account"])
		.then((r) => {
			const ba = r.message || {};
			if (!ba.name) {
				frappe.show_alert({ message: __("Bank {0} belum punya Bank Account (rekening company).", [frm.doc.depot_bank]), indicator: "orange" });
				return;
			}
			frm.set_value("bank_account", ba.name);
			const side = frm.doc.payment_type === "Receive" ? "paid_to" : "paid_from";
			if (ba.account && frm.doc[side] !== ba.account) frm.set_value(side, ba.account);
		});
}

// A new payment starts from the bank marked Default Bank.
function pe_default_bank(frm) {
	if (!frm.is_new() || frm.doc.depot_bank || pe_is_settlement(frm) || frm._pe_default_bank) return;
	frm._pe_default_bank = true;
	// Through the server: Finance and Cashier may pick a Bank, not list them.
	frappe.xcall(PE_METHOD + "default_bank").then((bank) => {
		frm._pe_default_bank = false;
		if (bank && frm.is_new() && !frm.doc.depot_bank && !pe_is_settlement(frm)) {
			frm.set_value("depot_bank", bank);
		}
	});
}

// ---- Amounts ---------------------------------------------------------------------------
function pe_smart(raw, base) {
	const [mode, num] = container_depot.parse_smart(raw);
	return mode === "pct" ? (flt(base) * num) / 100 : num;
}

function pe_lines_total(frm) {
	return (frm.doc.depot_lines || []).reduce((s, r) => s + flt(r.amount || r.outstanding), 0);
}

// What the amount should be (payment_entry._apply_amounts): the lines, their Credit / Debit
// Notes and the Accumulation boxes. Pay: tax, materai and admin add, PPh cuts; Receive: all
// of them are cuts from what comes in.
function pe_target(frm) {
	const lines = frm.doc.depot_lines || [];
	const alloc = pe_lines_total(frm);
	if (frm.doc.depot_direct) return alloc;
	const pay = frm.doc.payment_type === "Pay";
	const notes = lines.reduce((s, r) => s + (flt(r.amount) < 0 ? -1 : 1) * (flt(r.credit_amount) - flt(r.debit_amount)), 0);
	const boxes = pe_smart(frm.doc.depot_tax_input, alloc) + flt(frm.doc.depot_materai) + flt(frm.doc.depot_admin_fee);
	const pph = pe_smart(frm.doc.depot_pph_input, alloc);
	return pay ? alloc + notes + boxes - pph : alloc + notes - boxes - pph;
}

// Preview of the server's numbers; never writes the amount itself (that is the user's).
function pe_totals(frm) {
	if (frm.doc.docstatus !== 0) return;
	const alloc = pe_lines_total(frm);
	if (flt(frm.doc.depot_allocated) !== flt(alloc)) frm.set_value("depot_allocated", alloc);
	if (frm.doc.depot_direct && alloc) frm.set_value("paid_amount", alloc);
	for (const f of ["depot_tax_input", "depot_pph_input"]) {
		const amount = pe_smart(frm.doc[f], alloc);
		frm.set_df_property(f, "description", amount ? `= ${format_currency(amount, pe_currency(frm))}` : "");
	}
	const bank = flt(frm.doc.paid_amount) - flt(frm.doc.depot_kasbon_amount);
	if (flt(frm.doc.depot_bank_amount) !== bank) frm.set_value("depot_bank_amount", bank);
}

// "Pay" / "Receive" beside the amount: sets it to what the lines and boxes come to, in whole
// rupiah — the tail goes to a Pembulatan deduction when the payment is saved.
function pe_pay_button(frm) {
	setTimeout(() => {
		const field = frm.fields_dict.paid_amount;
		const $slot = field && field.$wrapper && field.$wrapper.find(".control-input-wrapper").first();
		if (!$slot || !$slot.length) return;
		$slot.find(".depot-pay-btn").remove();
		if (frm.doc.docstatus !== 0 || frm.doc.depot_direct) return;
		const $btn = $(`<button type="button" class="btn btn-xs btn-primary depot-pay-btn">${
			frm.doc.payment_type === "Receive" ? __("Receive") : __("Pay")
		}</button>`).css({
			position: "absolute", right: "100%", top: "50%", transform: "translateY(-50%)",
			"margin-right": "8px", padding: "0 8px", "white-space": "nowrap",
		});
		$btn.on("click", () => {
			const amount = pe_target(frm);
			const whole = Math.round(amount);
			frm.set_value("paid_amount", whole);
			if (flt(amount - whole, 2)) {
				frappe.show_alert({
					message: __("Dibulatkan jadi {0}; selisih {1} masuk baris Deductions <b>Pembulatan</b> saat disimpan.", [
						format_currency(whole, pe_currency(frm)), format_currency(Math.abs(amount - whole), pe_currency(frm)),
					]),
					indicator: "blue",
				}, 8);
			}
		});
		$slot.css("position", "relative").append($btn);
	}, 250);
}

// ---- Pickers ---------------------------------------------------------------------------
function pick_documents(frm) {
	if (!frm.doc.party) return frappe.msgprint(__("Pilih <b>{0}</b> dulu.", [frm.fields_dict.party.df.label]));
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
				__("Add Items · {0}", [frm.doc.party]),
				rows,
				[
					[__("Document No"), (r) => `<b>${r.document_no}</b><div class="text-muted small">${r.doc_label}</div>`],
					[__("Tanggal"), (r) => frappe.datetime.str_to_user(r.date)],
					[__("Amount"), (r) => format_currency(r.grand_total, r.currency), "right"],
					[__("Unallocated Amount"), (r) => format_currency(r.outstanding, r.currency), "right"],
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
	// The kasbon recipient is often not the party being paid (an employee settling a
	// supplier's bill), so the list is not narrowed to the payment's party.
	frappe
		.call(PE_METHOD + "get_kasbon", {
			company: frm.doc.company,
			payment_type: frm.doc.payment_type,
			customer: frm.doc.payment_type === "Receive" ? frm.doc.party : null,
			exclude: JSON.stringify(exclude),
			exclude_parent: frm.is_new() ? null : frm.doc.name,
		})
		.then((r) => {
			const rows = r.message || [];
			if (!rows.length) {
				frappe.msgprint(
					frm.doc.payment_type === "Receive"
						? __("Tidak ada deposit {0} yang masih tersisa.", [frm.doc.party || ""])
						: __("Tidak ada Pending Cash Paid yang masih tersisa.")
				);
				return;
			}
			pick_dialog(
				__("Add Pending Cash"),
				rows,
				[
					[__("Document No"), (r) => `<b>${r.name}</b><div class="text-muted small">${frappe.utils.escape_html(r.pay_to || r.receive_from || "")}</div>`],
					[__("Tanggal"), (r) => frappe.datetime.str_to_user(r.paid_date)],
					[__("Total"), (r) => format_currency(r.total), "right"],
					[__("Unallocated Amount"), (r) => format_currency(r.outstanding), "right"],
				],
				(picked) => {
					// Each takes what is left of it, up to what the payment still needs; the rest
					// stays for the next payment (or a refund).
					let need = flt(frm.doc.paid_amount || pe_target(frm)) - flt(frm.doc.depot_kasbon_amount);
					for (const k of picked) {
						const allocated = need > 0 ? Math.min(flt(k.outstanding), need) : flt(k.outstanding);
						need -= allocated;
						frm.add_child("depot_kasbon", {
							pending_cash: k.name,
							pay_to: k.pay_to,
							customer: k.receive_from,
							grand_total: k.total,
							outstanding: k.outstanding,
							allocated,
						});
					}
					frm.refresh_field("depot_kasbon");
					pe_kasbon_total(frm);
				}
			);
		});
}

function pick_advance(frm) {
	const exclude = (frm.doc.depot_advance || []).map((r) => r.purchase_order).filter(Boolean);
	frappe
		.call(PE_METHOD + "get_purchase_orders", { supplier: frm.doc.party, company: frm.doc.company, exclude: JSON.stringify(exclude) })
		.then((r) => {
			const rows = r.message || [];
			if (!rows.length) {
				frappe.msgprint(__("Tidak ada Purchase Order {0} yang masih bisa diberi uang muka.", [frm.doc.party]));
				return;
			}
			pick_dialog(
				__("Add Purchase Order · {0}", [frm.doc.party]),
				rows,
				[
					[__("Document No"), (r) => `<b>${r.name}</b>`],
					[__("Tanggal"), (r) => frappe.datetime.str_to_user(r.transaction_date)],
					[__("Total"), (r) => format_currency(r.total, r.currency), "right"],
					[__("Unallocated Amount"), (r) => format_currency(r.outstanding, r.currency), "right"],
				],
				(picked) => {
					for (const po of picked) {
						frm.add_child("depot_advance", {
							purchase_order: po.name,
							supplier: frm.doc.party,
							date: po.transaction_date,
							grand_total: po.total,
							outstanding: po.outstanding,
							allocated: po.outstanding,
						});
					}
					frm.refresh_field("depot_advance");
					pe_advance_total(frm);
				}
			);
		});
}

// An advance is the whole payment: its total is the amount (payment_entry._apply_advance).
function pe_advance_total(frm) {
	const total = (frm.doc.depot_advance || []).reduce((s, r) => s + flt(r.allocated), 0);
	frm.set_value("depot_advance_amount", total);
	if (total) frm.set_value("paid_amount", total);
}

function pe_kasbon_total(frm) {
	const total = (frm.doc.depot_kasbon || []).reduce((s, r) => s + flt(r.allocated), 0);
	frm.set_value("depot_kasbon_amount", total);
	pe_totals(frm);
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
	onload(frm) {
		pe_default_bank(frm);
	},
	refresh(frm) {
		pe_party_type(frm);
		pe_default_bank(frm);
		pe_toggle(frm);
		pe_pay_button(frm);
	},
	// ERPNext's own show/hide pass, run on every currency and amount change: ours replaces it
	// (frm.events keeps the last handler) and, when triggered, runs after it.
	hide_unhide_fields: pe_hide_native,
	set_dynamic_labels: pe_labels,
	// The cheque fields turn mandatory for a Bank account in an ERPNext callback: not here.
	validate: pe_hide_native,
	payment_type(frm) {
		// Another direction: nothing picked for the old one stays.
		frm.set_value({ party: "", paid_from: "", paid_to: "", paid_from_account_currency: "", paid_to_account_currency: "" });
		frm.clear_table("depot_lines");
		frm.clear_table("references");
		frm.refresh_fields();
		pe_party_type(frm);
		pe_toggle(frm);
		pe_pay_button(frm);
		pe_apply_bank(frm);
	},
	depot_direct(frm) {
		if (frm.doc.depot_direct) {
			frm.set_value({ party_type: null, party: null });
			frm.clear_table("references");
		} else {
			pe_party_type(frm);
		}
		frm.clear_table("depot_lines");
		frm.refresh_fields();
		pe_toggle(frm);
		pe_pay_button(frm);
	},
	mode_of_payment(frm) {
		// A settlement has no bank; leaving it, the settlement account goes.
		if (pe_is_settlement(frm)) {
			frm.set_value({ depot_bank: "", bank_account: "" });
		} else {
			frm.set_value("depot_settlement_account", "");
			pe_default_bank(frm);
		}
	},
	depot_bank: pe_apply_bank,
	depot_get_items: pick_documents,
	depot_get_kasbon: pick_kasbon,
	depot_get_advance: pick_advance,
	depot_advance_remove: pe_advance_total,
	depot_tax_input: pe_totals,
	depot_pph_input: pe_totals,
	depot_materai: pe_totals,
	depot_admin_fee: pe_totals,
	paid_amount: pe_totals,
	depot_kasbon_remove: pe_kasbon_total,
	depot_lines_remove: pe_totals,
	party(frm) {
		// Another party's documents cannot be paid on this one.
		if ((frm.doc.depot_lines || []).some((r) => r.document_no)) {
			frm.set_value("depot_lines", (frm.doc.depot_lines || []).filter((r) => !r.document_no));
		}
		pe_labels(frm);
	},
});

frappe.ui.form.on("Payment Entry Line", {
	amount: pe_totals,
	credit_amount: pe_totals,
	debit_amount: pe_totals,
});

frappe.ui.form.on("Payment Entry Advance", {
	allocated(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (flt(row.allocated) > flt(row.outstanding)) {
			frappe.show_alert({ message: __("Uang muka tidak boleh melebihi sisa Purchase Order."), indicator: "orange" });
			frappe.model.set_value(cdt, cdn, "allocated", row.outstanding);
			return;
		}
		pe_advance_total(frm);
	},
});

frappe.ui.form.on("Payment Entry Kasbon", {
	allocated(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (flt(row.allocated) > flt(row.outstanding)) {
			frappe.show_alert({ message: __("Allocated Amount tidak boleh melebihi sisa Pending Cash."), indicator: "orange" });
			frappe.model.set_value(cdt, cdn, "allocated", row.outstanding);
			return;
		}
		pe_kasbon_total(frm);
	},
});
