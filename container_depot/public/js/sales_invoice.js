// Consolidated ("generate") Sales Invoice UX.
//
// A generated invoice carries a rollback manifest (custom field depot_billed_sources)
// listing the depot orders it swept. Its line items are frozen server-side
// (consolidated_billing.protect_consolidated_items). Here we surface a prominent,
// visible button to discard/cancel the invoice — which rolls every order back to
// un-invoiced (consolidated_billing.rollback_billed_sources). We do NOT hide any of
// the standard Delete/Cancel actions in the ⋮ menu; this only adds a clearer button.
frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (!frm.doc.depot_billed_sources) return; // only generated invoices

		frm.set_intro(
			__(
				"Faktur ini dibuat lewat Generate — item terkunci (tidak bisa diubah/dihapus). " +
					"Untuk membatalkan, pakai tombol Batalkan & Kembalikan Order: semua order kembali " +
					"ke status belum di-invoice dan bisa di-generate ulang."
			),
			"blue"
		);

		if (frm.doc.docstatus === 0) {
			// Draft → discard (delete). on_trash rolls the orders back and unblocks the delete.
			frm.add_custom_button(__("Batalkan & Kembalikan Order"), () => frm.savetrash())
				.removeClass("btn-default")
				.addClass("btn-danger");
		} else if (frm.doc.docstatus === 1) {
			// Submitted → cancel. on_cancel rolls the orders back.
			frm.add_custom_button(__("Cancel & Kembalikan Order"), () => frm.savecancel())
				.removeClass("btn-default")
				.addClass("btn-danger");
		}
	},
});

// --- Labour (manhour) -------------------------------------------------------------
// Each line carries the manhour its contract books; the hours never touch that line's own
// amount. The header totals them and charges them once:
//
//     Total = Total Price + (Total Manhour × Hour)
//
// Each item line carries the manhour its contract books (a column in the items grid). The
// hours never touch that line's price; they are totalled under Total / Net Total and charged
// once, as a "Manhour" row at the TOP of the tax table — first, so a percentage tax below it
// lands on services + labour alike:
//
//     Total Price + Biaya Manhour  ->  tax on that sum  ->  Grand Total
//
// The row is created/updated here as you type so the Grand Total moves immediately; the
// server writes the same numbers authoritatively on save (invoicing.apply_manhour_charge).
const MANHOUR_CHARGE = "Manhour";

// Labour posts exactly where the item lines do — same revenue, just charged once as a flat
// amount instead of per unit. Reading it off the lines (rather than resolving an account of
// its own) means the two can never drift apart, and costs no server round-trip.
function item_posting(frm) {
	const item = (frm.doc.items || []).find((i) => i.income_account);
	return item ? { account: item.income_account, cost_center: item.cost_center } : null;
}

async function recalc_manhour(frm) {
	// Manhour does NOT scale with qty — that is what sets it apart from the rate. The rate
	// is per unit and multiplied by qty; the manhours are summed as they stand, and the
	// SUM is multiplied by Hour, once.
	let hours = 0;
	for (const row of frm.doc.items || []) hours += flt(row.manhour);
	const amount = hours * flt(frm.doc.manhour_hour);
	frm.set_value("total_manhour", hours);
	frm.set_value("manhour_amount", amount);

	let row = (frm.doc.taxes || []).find((t) => (t.description || "").trim() === MANHOUR_CHARGE);
	if (!amount) {
		if (row) {
			// Put back what inserting the row changed, or the percentage below it would be
			// left charging "On Previous Row Total" against a row that no longer exists.
			for (const t of frm.doc.taxes || []) {
				if (t.charge_type === "On Previous Row Total" && cint(t.row_id) === cint(row.idx)) {
					t.charge_type = "On Net Total";
					t.row_id = null;
				}
			}
			frm.get_field("taxes").grid.grid_rows_by_docname[row.name].remove();
			frm.refresh_field("taxes");
		}
		return;
	}
	if (!row) {
		const posting = item_posting(frm);
		if (!posting) return; // no income account on the lines yet — the server will report it
		row = frm.add_child("taxes", {
			charge_type: "Actual",
			description: MANHOUR_CHARGE,
			account_head: posting.account,
			tax_amount: 0,
			// ERPNext will not book a Profit-and-Loss account without a Cost Center, so the
			// row carries the lines' one too.
			cost_center: posting.cost_center,
		});
		// Move it to the front and repoint any Net-Total percentage at it, exactly as the
		// server does — otherwise the previewed total would differ from the saved one.
		frm.doc.taxes = [row, ...frm.doc.taxes.filter((t) => t.name !== row.name)];
		frm.doc.taxes.forEach((t, i) => (t.idx = i + 1));
		for (const t of frm.doc.taxes) {
			if (t.charge_type === "On Net Total") {
				t.charge_type = "On Previous Row Total";
				t.row_id = 1;
			}
		}
		frm.refresh_field("taxes");
	}
	if (flt(row.tax_amount) !== amount) {
		// Through the model so ERPNext's own handler re-totals the document.
		frappe.model.set_value(row.doctype, row.name, "tax_amount", amount);
	}
}

// Deleting the labour row in the grid is how a user says "don't bill labour on this
// invoice". The row is derived, so on its own the deletion would not survive the next
// recalc — zero the multiplier instead, which is what the server does too (see
// invoicing._charge_row_deleted) and what typing an Hour again undoes.
function honour_manhour_row_delete(frm) {
	if (!flt(frm.doc.manhour_hour)) return; // already off — nothing to honour
	if (!(frm.doc.items || []).some((i) => flt(i.manhour))) return; // no labour to bill
	if ((frm.doc.taxes || []).some((t) => (t.description || "").trim() === MANHOUR_CHARGE)) return;
	frm.set_value("manhour_hour", 0); // -> recalc_manhour: amount 0, so the row stays out
	frappe.show_alert({
		message: __("Biaya Manhour dihapus — Hour diset 0. Isi Hour lagi untuk menagihkannya kembali."),
		indicator: "orange",
	});
}

frappe.ui.form.on("Sales Invoice", {
	// No `company` handler any more: the charge row reads its account off the item lines
	// every time, so there is no cached per-company account left to invalidate.
	manhour_hour: recalc_manhour,
	// Single-row delete and the grid's multi-select delete fire different events.
	taxes_remove: honour_manhour_row_delete,
	taxes_delete: honour_manhour_row_delete,
});

frappe.ui.form.on("Sales Invoice Item", {
	manhour: (frm) => recalc_manhour(frm),
	qty: (frm) => recalc_manhour(frm),
	items_remove: (frm) => recalc_manhour(frm),
});
