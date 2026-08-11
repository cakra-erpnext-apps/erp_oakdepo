// Consolidated ("generate") Sales Invoice UX.
//
// A generated invoice carries a rollback manifest (custom field depot_billed_sources)
// listing the depot orders it swept. Its line items are frozen server-side
// (consolidated_billing.protect_consolidated_items). Here we surface a prominent,
// visible button to discard/cancel the invoice — which rolls every order back to
// un-invoiced (consolidated_billing.rollback_billed_sources). We do NOT hide any of
// the standard Delete/Cancel actions in the ⋮ menu; this only adds a clearer button.
// --- Tagihan Depot: build the invoice from the depot's unbilled work ----------------
//
// "Ambil Tagihan" lists EVERY unbilled order the customer has — no section or date filter,
// because the tick-list already is the filter and two ways to say the same thing is what
// made this form unreadable. On an invoice that was already generated the same button
// RE-runs: the server rolls the previous sweep back before collecting again, so pressing
// it twice never double-charges.
//
// A run that picks up more than one currency yields more than one invoice — ERPNext
// documents are single-currency — tied together by Nomor Tagihan. The dialog says so
// before anything is created, so the operator is never surprised by a second document.
function money(amount, currency) {
	return format_currency(amount, currency);
}

// Show what the filters matched, then let the operator commit. Preview and fill call the
// same server-side collector, so this list is exactly what the invoice will carry.
function preview_then_fill(frm) {
	frappe.call({
		method: "container_depot.consolidated_billing.preview_bill",
		// No filters: show EVERYTHING unbilled for this customer and let the operator tick.
		args: { customer: frm.doc.customer },
		freeze: true,
		freeze_message: __("Menghitung tagihan…"),
		callback: (r) => {
			const p = r.message;
			if (!p || !p.total_orders) {
				frappe.msgprint({
					title: __("Tidak ada yang ditagih"),
					message: __("Tidak ada pekerjaan yang belum ditagih untuk {0}.", [
						frappe.utils.escape_html(frm.doc.customer),
					]),
					indicator: "blue",
				});
				return;
			}
			show_preview_dialog(frm, p);
		},
	});
}

// The preview is a worksheet, not a receipt: every order is its own tickable row, so a run
// can be narrowed down to individual orders instead of being all-or-nothing per section.
// Only the ticked keys are sent; the server re-collects and filters by them.
function show_preview_dialog(frm, p) {
	const rows = p.sections.flatMap((s) => s.rows.map((r) => ({ ...r, category: s.category })));

	const body = p.sections
		.map((s) => {
			const cells = s.rows
				.map(
					(r) => `<tr>
						<td style="padding:5px 8px;width:34px;">
							<input type="checkbox" class="oak-bill-row" data-key="${frappe.utils.escape_html(r.key)}" checked>
						</td>
						<td style="padding:5px 8px;"><b>${frappe.utils.escape_html(r.label)}</b>
							<div style="color:var(--text-muted);font-size:11px;">${frappe.utils.escape_html(r.detail || "")}</div>
						</td>
						<td style="padding:5px 8px;text-align:right;white-space:nowrap;">${money(r.amount, r.currency)}</td>
					</tr>`
				)
				.join("");
			return `<tr style="background:var(--control-bg);color:var(--text-color);">
					<td style="padding:5px 8px;">
						<input type="checkbox" class="oak-bill-section" data-section="${frappe.utils.escape_html(s.category)}" checked>
					</td>
					<td colspan="2" style="padding:5px 8px;"><b>${frappe.utils.escape_html(s.category)}</b>
						<span style="color:var(--text-muted);">· ${s.rows.length} order</span></td>
				</tr>${cells}`;
		})
		.join("");

	const d = new frappe.ui.Dialog({
		title: __("Pilih tagihan · {0}", [p.customer]),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "picker",
				options: `
					<div style="font-size:13px;">
						<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
							<span style="color:var(--text-muted);">${__("Centang order yang mau ditagih")}</span>
							<span>
								<button class="btn btn-xs btn-default oak-bill-all">${__("Pilih semua")}</button>
								<button class="btn btn-xs btn-default oak-bill-none">${__("Kosongkan")}</button>
							</span>
						</div>
						<div style="max-height:340px;overflow-y:auto;border:1px solid var(--border-color);border-radius:4px;">
							<table class="table" style="margin:0;">
								<tbody>${body}</tbody>
							</table>
						</div>
						<div class="oak-bill-summary" style="margin-top:12px;"></div>
					</div>`,
			},
		],
		primary_action_label: __("Buat Invoice"),
		primary_action() {
			const keys = selected_keys(d);
			if (!keys.length) {
				frappe.msgprint({
					title: __("Belum ada yang dipilih"),
					message: __("Centang minimal satu order."),
					indicator: "orange",
				});
				return;
			}
			d.hide();
			run_fill(frm, keys);
		},
	});

	d.show();
	wire_picker(d, rows);
}

function selected_keys(d) {
	return d.$wrapper
		.find(".oak-bill-row:checked")
		.map((_, el) => $(el).data("key"))
		.get();
}

// Totals are recomputed from the ticked rows rather than taken from the preview response,
// so the figure under the table always matches what the primary action will bill.
function wire_picker(d, rows) {
	const $w = d.$wrapper;
	const by_key = Object.fromEntries(rows.map((r) => [r.key, r]));

	function refresh() {
		const keys = selected_keys(d);
		const totals = {};
		for (const k of keys) {
			const r = by_key[k];
			if (!r) continue;
			totals[r.currency] = (totals[r.currency] || 0) + r.amount;
		}
		const ccys = Object.keys(totals);
		const lines = ccys
			.map(
				(c) =>
					`<tr><td style="padding:3px 8px;"><b>${frappe.utils.escape_html(c)}</b></td>
					 <td style="padding:3px 8px;text-align:right;">${money(totals[c], c)}</td></tr>`
			)
			.join("");
		const multi =
			ccys.length > 1
				? `<div class="alert alert-warning" style="margin:8px 0 0;">${__(
						"Pilihan ini memuat {0} mata uang, jadi akan dibuat {0} Sales Invoice dengan <b>Nomor Tagihan yang sama</b> — satu dokumen per mata uang. Cetakannya tetap satu PDF, satu halaman per mata uang.",
						[ccys.length]
				  )}</div>`
				: "";
		$w.find(".oak-bill-summary").html(
			keys.length
				? `<div style="color:var(--text-muted);margin-bottom:4px;">${__("{0} order dipilih · nilai belum PPN", [
						keys.length,
				  ])}</div>
				   <table class="table table-bordered" style="margin:0;"><tbody>${lines}</tbody></table>${multi}`
				: `<div style="color:var(--text-muted);">${__("Belum ada order yang dipilih.")}</div>`
		);
		// A section box reflects its rows: checked only when every row under it is.
		$w.find(".oak-bill-section").each((_, el) => {
			const $sec = $(el);
			const $rows = $sec.closest("tr").nextUntil("tr:has(.oak-bill-section)").find(".oak-bill-row");
			$sec.prop("checked", $rows.length && $rows.filter(":checked").length === $rows.length);
		});
	}

	$w.on("change", ".oak-bill-row", refresh);
	$w.on("change", ".oak-bill-section", function () {
		const on = $(this).prop("checked");
		$(this).closest("tr").nextUntil("tr:has(.oak-bill-section)").find(".oak-bill-row").prop("checked", on);
		refresh();
	});
	$w.on("click", ".oak-bill-all", (e) => {
		e.preventDefault();
		$w.find(".oak-bill-row").prop("checked", true);
		refresh();
	});
	$w.on("click", ".oak-bill-none", (e) => {
		e.preventDefault();
		$w.find(".oak-bill-row").prop("checked", false);
		refresh();
	});
	refresh();
}

function run_fill(frm, keys) {
	frappe.call({
		method: "container_depot.consolidated_billing.fill_invoice",
		args: {
			customer: frm.doc.customer,
			keys: JSON.stringify(keys),
			// Only an already-generated draft is re-run in place; a fresh form just creates.
			sales_invoice: frm.doc.depot_billed_sources && !frm.is_new() ? frm.doc.name : null,
		},
		freeze: true,
		freeze_message: __("Membuat invoice…"),
		callback: (r) => {
			const out = r.message || {};
			const invoices = out.invoices || [];
			if (!invoices.length) {
				frappe.msgprint({ title: __("Tidak ada yang ditagih"), indicator: "blue" });
				return;
			}
			frappe.show_alert({
				message: __("{0} invoice dibuat · Nomor Tagihan {1}", [invoices.length, out.group]),
				indicator: "green",
			});
			// The re-run discarded this document and built new ones, so there is nothing here
			// to refresh — go to the first of the freshly created set.
			frappe.set_route("Form", "Sales Invoice", invoices[0]);
		},
	});
}

// Changing the party invalidates everything collected for the old one. Rather than
// silently re-bill someone else's work, hand the invoice back to the depot and start over.
function reset_on_customer_change(frm) {
	if (frm.is_new() || !frm.doc.depot_billed_sources) return;
	frappe.confirm(
		__(
			"Invoice ini berisi tagihan yang dikumpulkan untuk customer sebelumnya. " +
				"Mengganti customer akan mengembalikan semua order itu ke status belum di-invoice " +
				"dan menghapus invoice ini. Lanjutkan?"
		),
		() => frm.savetrash(),
		() => frm.set_value("customer", frm.doc.__onload_customer || "")
	);
}

frappe.ui.form.on("Sales Invoice", {
	onload(frm) {
		// Remember the party we were opened with, so a cancelled reset can put it back.
		frm.doc.__onload_customer = frm.doc.customer;
	},

	customer: reset_on_customer_change,

	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			const label = frm.doc.depot_billed_sources
				? __("Ambil Tagihan Ulang")
				: __("Ambil Tagihan");
			frm.add_custom_button(label, () => {
				if (!frm.doc.customer) {
					frappe.msgprint({
						title: __("Pilih Customer"),
						message: __("Isi <b>Customer</b> dulu — tagihan dikumpulkan per customer."),
						indicator: "orange",
					});
					return;
				}
				preview_then_fill(frm);
			}).addClass("btn-primary");
		}

		if (!frm.doc.depot_billed_sources) return; // only generated invoices

		if (frm.doc.depot_bill_group) {
			frm.add_custom_button(__("Lihat Satu Tagihan"), () =>
				frappe.set_route("List", "Sales Invoice", { depot_bill_group: frm.doc.depot_bill_group })
			);
		}

		frm.set_intro(
			__(
				"Faktur ini dibuat lewat Generate — item terkunci (tidak bisa diubah/dihapus). " +
					"Untuk membatalkan, pakai tombol Batalkan & Kembalikan Order: semua order kembali " +
					"ke status belum di-invoice dan bisa di-generate ulang."
			),
			"blue"
		);

		// These stand in for Frappe's own Delete and Cancel, which are permission-gated —
		// so these are too, on the same rights. savetrash()/savecancel() would be refused
		// server-side anyway; the point is not to offer a red button that cannot work.
		if (frm.doc.docstatus === 0 && frappe.perm.has_perm(frm.doctype, 0, "delete")) {
			// Draft → discard (delete). on_trash rolls the orders back and unblocks the delete.
			frm.add_custom_button(__("Batalkan & Kembalikan Order"), () => frm.savetrash())
				.removeClass("btn-default")
				.addClass("btn-danger");
		} else if (frm.doc.docstatus === 1 && frappe.perm.has_perm(frm.doctype, 0, "cancel")) {
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
