// Consolidated ("generate") Sales Invoice UX.
//
// A generated invoice carries a rollback manifest (custom field depot_billed_sources)
// listing the depot orders it swept. The lines it billed (depot_source) are locked
// server-side (consolidated_billing.protect_consolidated_items); the red Cancel gives every
// order back (consolidated_billing.rollback_billed_sources). No banner explains the lock:
// the server's message says it when someone tries (user, 2026-09-29: fewer notices).
// --- Tagihan Depot: build the invoice from the depot's unbilled work ----------------
//
// Picking an Invoice Type opens "Pilih Order": EVERY unbilled order of that type the customer
// has, as a report-style tick-list (Gabungan = every type, Manual = no list). The same list
// stays one click away on the Pilih Order button. On a saved draft the list also shows the
// orders it already bills, ticked, and the pick edits THAT invoice: unticked orders go back,
// newly ticked ones are added (consolidated_billing._refill). One invoice, many orders.
//
// Currency: every line keeps the currency its order states. One run is ONE invoice in one
// currency: the dialog asks which, and the other currencies are converted into it through
// their kurs to IDR, the ledger's currency. No more invoice per currency (user, 2026-09-28).
// One print format for an invoice, OAK Invoice (install.ensure_invoice_print): the rest are
// disabled there, and Frappe's generated "Standard" goes from the list here.
const get_print_formats = frappe.meta.get_print_formats;
frappe.meta.get_print_formats = function (doctype) {
	const list = get_print_formats.apply(this, arguments);
	return doctype === "Sales Invoice" && list.length > 1 ? list.filter((f) => f !== "Standard") : list;
};

function money(amount, currency) {
	return format_currency(amount, currency);
}

// The Invoice Type picked in the header decides which orders are offered. Gabungan = all.
function type_categories(frm) {
	const t = frm.doc.depot_invoice_type;
	return t && t !== "Gabungan" ? JSON.stringify([t]) : null;
}

// Show what the filters matched, then let the operator commit. Preview and fill call the
// same server-side collector, so this list is exactly what the invoice will carry.
function preview_then_fill(frm) {
	// A saved draft is edited in place by the server: save what is typed on it first.
	if (!frm.is_new() && frm.is_dirty()) return frm.save().then(() => preview_then_fill(frm));
	frappe.call({
		method: "container_depot.consolidated_billing.preview_bill",
		// Everything unbilled of this Invoice Type for the customer (plus what this draft
		// already bills); the operator ticks.
		args: { customer: frm.doc.customer, categories: type_categories(frm), sales_invoice: saved_draft(frm) },
		freeze: true,
		freeze_message: __("Menghitung tagihan…"),
		callback: (r) => {
			const p = r.message;
			if (!p || !p.total_orders) {
				frappe.msgprint({
					title: __("Tidak ada yang ditagih"),
					message: __("Tidak ada order {0} yang belum ditagih untuk {1}.", [
						frappe.utils.escape_html(frm.doc.depot_invoice_type),
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

// The draft a pick edits in place; null = the pick raises a new invoice.
function saved_draft(frm) {
	return !frm.is_new() && frm.doc.docstatus === 0 ? frm.doc.name : null;
}

// The preview is a worksheet, not a receipt: every order is its own tickable row, laid out
// like the Order Billing Status report (already narrowed to this customer and Invoice Type),
// so a run can be narrowed down to individual orders. Only the ticked keys are sent; the
// server re-collects and filters by them.
function show_preview_dialog(frm, p) {
	const rows = p.sections.flatMap((s) => s.rows.map((r) => ({ ...r, category: s.category })));
	// Editing a draft: its own orders start ticked, the rest are there to add. A new invoice
	// starts with everything ticked.
	const editing = !!p.invoice_currency;
	const esc = frappe.utils.escape_html;
	const cell = "padding:5px 8px;";
	const body = rows
		.map(
			(r) => `<tr class="oak-bill-tr${r.on_invoice ? " oak-bill-cur" : ""}" title="${esc(r.detail || "")}" data-date="${esc(r.date || "")}"
					data-search="${esc([r.category, r.label, r.tank, r.detail].join(" ").toLowerCase())}">
				<td style="${cell}width:34px;"><input type="checkbox" class="oak-bill-row" data-key="${esc(r.key)}"${!editing || r.on_invoice ? " checked" : ""}></td>
				<td style="${cell}">${esc(r.category)}${r.on_invoice ? `<div class="text-muted small">${__("di invoice ini")}</div>` : ""}</td>
				<td style="${cell}">${r.doctype && r.doctype !== "Storage Charge"
					? `<a href="${frappe.utils.get_form_link(r.doctype, r.name)}" target="_blank">${esc(r.label)}</a>`
					: esc(r.label)}</td>
				<td style="${cell}">${esc(r.tank || "")}</td>
				<td style="${cell}white-space:nowrap;">${r.date ? frappe.datetime.str_to_user(r.date) : ""}</td>
				<td style="${cell}">${esc(r.currency)}</td>
				<td style="${cell}text-align:right;white-space:nowrap;">${money(r.amount, r.currency)}</td>
			</tr>`
		)
		.join("");
	const th = (label, right) => `<th style="${cell}${right ? "text-align:right;" : ""}">${__(label)}</th>`;

	const d = new frappe.ui.Dialog({
		title: __("Pilih Order {0} · {1}", [frm.doc.depot_invoice_type, p.customer]),
		size: "large",
		fields: [
			// Narrow the list by the order's date (the Tanggal column); empty = no bound.
			{ fieldtype: "Date", fieldname: "from_date", label: __("Dari Tanggal"), change: () => d.apply_filters && d.apply_filters() },
			{ fieldtype: "Column Break" },
			{ fieldtype: "Date", fieldname: "to_date", label: __("Sampai Tanggal"), change: () => d.apply_filters && d.apply_filters() },
			{ fieldtype: "Section Break" },
			{
				fieldtype: "HTML",
				fieldname: "picker",
				options: `
					<div style="font-size:13px;">
						<div style="display:flex;gap:8px;align-items:center;margin-bottom:6px;">
							<input type="text" class="form-control oak-bill-search" style="max-width:260px;"
								placeholder="${__("Cari order / tank")}">
							<span style="margin-left:auto;white-space:nowrap;">
								<button class="btn btn-xs btn-default oak-bill-all">${__("Pilih semua")}</button>
								<button class="btn btn-xs btn-default oak-bill-none">${__("Kosongkan")}</button>
							</span>
						</div>
						<div style="max-height:360px;overflow:auto;border:1px solid var(--border-color);border-radius:4px;">
							<table class="table" style="margin:0;">
								<thead style="position:sticky;top:0;background:var(--control-bg);">
									<tr><th style="${cell}width:34px;"><input type="checkbox" class="oak-bill-head" title="${__("Pilih semua / kosongkan")}"></th>${th("Seksi")}${th("Order")}${th("Tank")}${th("Tanggal")}${th("Mata Uang")}${th("Amount", true)}</tr>
								</thead>
								<tbody>${body}</tbody>
							</table>
						</div>
						<div class="oak-bill-summary" style="margin-top:12px;"></div>
					</div>`,
			},
			{
				fieldtype: "Select",
				fieldname: "bill_currency",
				label: __("Ditagih dalam"),
				options: [],
				change: () => render_currency_block(d, p),
			},
			{ fieldtype: "HTML", fieldname: "kurs_html" },
		],
		primary_action_label: editing ? __("Simpan ke Invoice") : __("Buat Invoice"),
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
			const plan = currency_plan(d, p);
			const kurs = read_kurs(d);
			const missing = plan.need.filter((c) => !kurs[c]);
			if (missing.length) {
				frappe.msgprint({
					title: __("Kurs belum diisi"),
					message: __("Isi kurs ke {0} untuk: {1}", [p.company_currency, missing.join(", ")]),
					indicator: "orange",
				});
				return;
			}
			d.hide();
			run_fill(frm, keys, plan.currency, kurs);
		},
	});

	d.ccys = [];
	d.show();
	wire_picker(d, rows, p);
}

// The invoice currency and the currencies whose kurs the run needs. IDR needs none.
function currency_plan(d, p) {
	const currency = d.get_value("bill_currency") || d.ccys[0] || p.company_currency;
	const all = [...new Set([...d.ccys, currency])];
	return { currency, need: all.filter((c) => c !== p.company_currency) };
}

// Which currency to bill in, and the kurs every currency on the bill converts at. Offered
// whenever the selection is not plain company currency: even a single-currency USD run may
// be billed in IDR.
function render_currency_block(d, p) {
	const base = p.company_currency;
	const ccys = d.ccys;
	const f = d.fields_dict;
	// A customer whose receivable is foreign can only be billed in it (ERPNext rule). A draft
	// being edited starts in its own currency.
	const options = p.locked_currency
		? [p.locked_currency]
		: [...new Set([...ccys, base, p.invoice_currency].filter(Boolean))];
	if (JSON.stringify(f.bill_currency.df.options) !== JSON.stringify(options)) {
		const keep = d.get_value("bill_currency");
		f.bill_currency.df.options = options;
		f.bill_currency.refresh();
		d.set_value(
			"bill_currency",
			options.includes(keep) ? keep
				: options.length === 1 ? options[0]
				: p.invoice_currency || (ccys.length === 1 ? ccys[0] : base)
		);
	}
	f.bill_currency.$wrapper.toggle(!!(p.locked_currency || p.invoice_currency) || !(ccys.length === 1 && ccys[0] === base));
	f.bill_currency.set_description(
		p.locked_currency ? __("Piutang customer ini dalam {0}: invoice wajib {0}.", [p.locked_currency]) : ""
	);
	const prev = read_kurs(d);
	const need = currency_plan(d, p).need;
	f.kurs_html.$wrapper.html(
		need.length
			? `<div style="font-size:13px;margin-bottom:4px;color:var(--text-muted);">${__("Kurs ke {0}", [base])}</div>` +
					need
						.map(
							(c) => `<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
								<span style="width:70px;"><b>1 ${frappe.utils.escape_html(c)}</b> =</span>
								<input type="text" class="form-control oak-kurs" data-ccy="${frappe.utils.escape_html(c)}"
									style="max-width:180px;" value="${prev[c] || p.kurs[c] || ""}">
								<span>${frappe.utils.escape_html(base)}</span>
							</div>`
						)
						.join("")
			: ""
	);
}

function read_kurs(d) {
	const out = {};
	d.$wrapper.find(".oak-kurs").each((_, el) => {
		const v = container_depot.parse_smart($(el).val())[1];
		if (v) out[$(el).data("ccy")] = v;
	});
	return out;
}

// Only what the filters leave on screen is billed: a row filtered out is not picked.
function selected_keys(d) {
	return d.$wrapper
		.find(".oak-bill-tr:not(.oak-bill-off) .oak-bill-row:checked")
		.map((_, el) => $(el).data("key"))
		.get();
}

// Totals are recomputed from the ticked rows rather than taken from the preview response,
// so the figure under the table always matches what the primary action will bill.
function wire_picker(d, rows, p) {
	const $w = d.$wrapper;
	const by_key = Object.fromEntries(rows.map((r) => [r.key, r]));

	function refresh() {
		const keys = selected_keys(d);
		// Head checkbox mirrors the rows on screen: all ticked, none, or some (indeterminate).
		const $shown = $w.find(".oak-bill-tr:not(.oak-bill-off) .oak-bill-row");
		const ticked = $shown.filter(":checked").length;
		$w.find(".oak-bill-head")
			.prop("checked", !!$shown.length && ticked === $shown.length)
			.prop("indeterminate", ticked > 0 && ticked < $shown.length);
		const totals = {};
		for (const k of keys) {
			const r = by_key[k];
			if (!r) continue;
			totals[r.currency] = (totals[r.currency] || 0) + r.amount;
		}
		const ccys = Object.keys(totals);
		d.ccys = ccys;
		render_currency_block(d, p);
		const lines = ccys
			.map(
				(c) =>
					`<tr><td style="padding:3px 8px;"><b>${frappe.utils.escape_html(c)}</b></td>
					 <td style="padding:3px 8px;text-align:right;">${money(totals[c], c)}</td></tr>`
			)
			.join("");
		$w.find(".oak-bill-summary").html(
			keys.length
				? `<div style="color:var(--text-muted);margin-bottom:4px;">${__("{0} order dipilih · nilai belum PPN", [
						keys.length,
				  ])}</div>
				   <table class="table table-bordered" style="margin:0;"><tbody>${lines}</tbody></table>`
				: `<div style="color:var(--text-muted);">${__("Belum ada order yang dipilih.")}</div>`
		);
	}

	// Search and the date range hide rows (and so leave them out of the bill); the two
	// buttons act on what is left. The orders already on the draft always stay in view:
	// hiding one would drop it from the invoice without anyone unticking it.
	d.apply_filters = () => {
		const q = ($w.find(".oak-bill-search").val() || "").trim().toLowerCase();
		const from = d.get_value("from_date");
		const to = d.get_value("to_date");
		$w.find(".oak-bill-tr:not(.oak-bill-cur)").each((_, tr) => {
			const date = $(tr).attr("data-date");
			const on =
				(!q || $(tr).attr("data-search").includes(q)) &&
				(!date || ((!from || date >= from) && (!to || date <= to)));
			$(tr).toggleClass("oak-bill-off", !on).toggle(on);
		});
		refresh();
	};
	$w.on("input", ".oak-bill-search", d.apply_filters);
	$w.on("change", ".oak-bill-row", refresh);
	$w.on("click", ".oak-bill-all", (e) => {
		e.preventDefault();
		$w.find(".oak-bill-tr:not(.oak-bill-off) .oak-bill-row").prop("checked", true);
		refresh();
	});
	$w.on("change", ".oak-bill-head", (e) => {
		$w.find(".oak-bill-tr:not(.oak-bill-off) .oak-bill-row").prop("checked", e.currentTarget.checked);
		refresh();
	});
	$w.on("click", ".oak-bill-none", (e) => {
		e.preventDefault();
		$w.find(".oak-bill-tr:not(.oak-bill-off) .oak-bill-row").prop("checked", false);
		refresh();
	});
	refresh();
}

function run_fill(frm, keys, currency, kurs) {
	frappe.call({
		method: "container_depot.consolidated_billing.fill_invoice",
		args: {
			customer: frm.doc.customer,
			categories: type_categories(frm),
			keys: JSON.stringify(keys),
			currency: currency || null,
			kurs: JSON.stringify(kurs || {}),
			// A saved draft is edited in place; an unsaved form raises a new invoice.
			sales_invoice: saved_draft(frm),
			// What the form already says: an unsaved form is left behind for the new invoice.
			header: JSON.stringify({
				branch: frm.doc.branch,
				customer_address: frm.doc.customer_address,
				posting_date: frm.doc.posting_date,
				depot_invoice_type: frm.doc.depot_invoice_type,
			}),
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
			if (invoices[0] === frm.doc.name) {
				frappe.show_alert({ message: __("Order invoice diperbarui"), indicator: "green" });
				frm.reload_doc();
				return;
			}
			frappe.show_alert({ message: __("Invoice {0} dibuat", [invoices[0]]), indicator: "green" });
			frappe.set_route("Form", "Sales Invoice", invoices[0]);
		},
	});
}

// Attachment / Paid Attachment: several files each. They are the invoice's own File
// attachments (also in the sidebar), grouped by attached_to_field — the hidden Attach field.
const ATTACH_BOXES = { depot_attachment: __("Attachment"), depot_paid_attachment: __("Paid Attachment") };
function render_attachments(frm) {
	const esc = frappe.utils.escape_html;
	const boxes = Object.entries(ATTACH_BOXES).filter(([key]) => frm.fields_dict[key + "_html"]);
	const paint = (files) => {
		for (const [key, label] of boxes) {
			const $w = frm.fields_dict[key + "_html"].$wrapper;
			const head = `<label class="control-label" style="padding-right:0;">${label}</label>`;
			if (frm.is_new()) {
				$w.html(`${head}<div class="text-muted small">${__("Simpan dulu untuk melampirkan file.")}</div>`);
				continue;
			}
			const rows = (files[key] || [])
				.map(
					(f) => `<div style="display:flex;gap:8px;align-items:center;margin-bottom:4px;">
						<a href="${encodeURI(f.file_url)}" target="_blank" style="overflow:hidden;text-overflow:ellipsis;">${esc(f.file_name || f.file_url)}</a>
						<a href="#" class="text-muted oak-att-del" data-name="${esc(f.name)}" title="${__("Hapus")}">&times;</a>
					</div>`
				)
				.join("");
			$w.html(`${head}<div style="margin-bottom:6px;">${rows}</div>
				<button class="btn btn-xs btn-default oak-att-add">${__("Tambah file")}</button>`);
			$w.find(".oak-att-add").on("click", () =>
				new frappe.ui.FileUploader({
					doctype: frm.doctype,
					docname: frm.docname,
					fieldname: key,
					allow_multiple: true,
					on_success: () => render_attachments(frm),
				})
			);
			$w.find(".oak-att-del").on("click", (e) => {
				e.preventDefault();
				const fid = $(e.currentTarget).data("name");
				frappe.confirm(__("Hapus file ini?"), () =>
					frappe
						.xcall("frappe.desk.form.utils.remove_attach", { fid, dt: frm.doctype, dn: frm.docname })
						.then(() => render_attachments(frm))
				);
			});
		}
	};
	if (frm.is_new()) return paint({});
	frappe
		.xcall("container_depot.invoicing.invoice_attachments", { sales_invoice: frm.doc.name })
		.then((files) => paint(files || {}));
}

// Sumber Tagihan tab (erp_cakra's Connection tab): what this invoice bills, order by order.
function render_sources(frm) {
	const $w = frm.fields_dict.depot_sources_html.$wrapper;
	if (!frm.doc.depot_billed_sources || frm.is_new()) return $w.empty();
	frappe.call("container_depot.consolidated_billing.invoice_sources", { sales_invoice: frm.doc.name }).then((r) => {
		const esc = frappe.utils.escape_html;
		const rows = (r.message || [])
			.map(
				(s) => `<tr>
					<td>${esc(__(s.doctype))}</td>
					<td><a href="${frappe.utils.get_form_link(s.doctype, s.name)}">${esc(s.name)}</a></td>
					<td>${esc(s.reff_doc || "")}</td>
					<td>${esc(s.tank || "")}</td>
					<td style="text-align:right;">${Object.entries(s.amounts).map(([c, a]) => money(a, c)).join("<br>")}</td>
				</tr>`
			)
			.join("");
		$w.html(`<table class="table table-bordered" style="margin:0;">
			<thead><tr><th>${__("Jenis")}</th><th>${__("Nomor")}</th><th>${__("Reff Doc")}</th><th>${__("Tank")}</th>
				<th style="text-align:right;">${__("Nominal")}</th></tr></thead>
			<tbody>${rows}</tbody></table>`);
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
		// Invoice Date (posting_date) is always editable; ERPNext locks it unless this is on.
		// Older drafts were saved with it off (the server forces it on too: header_rules).
		if (frm.doc.docstatus === 0) frm.doc.set_posting_time = 1;
	},

	customer(frm) {
		reset_on_customer_change(frm);
		// Payment Term (a label) starts as the customer's contract states it.
		if (frm.doc.docstatus !== 0 || !frm.doc.customer) return;
		frappe
			.call("container_depot.invoicing.contract_payment_term", { customer: frm.doc.customer })
			.then((r) => r.message && frm.set_value("depot_payment_term", r.message));
	},

	// Customer first, then the type: picking it opens the order list straight away.
	depot_invoice_type(frm) {
		const t = frm.doc.depot_invoice_type;
		if (!t || t === "Manual" || frm.doc.docstatus !== 0 || frm.doc.depot_billed_sources) return;
		if (!frm.doc.customer) {
			frappe.show_alert({ message: __("Isi Customer dulu untuk memilih order."), indicator: "orange" });
			return;
		}
		preview_then_fill(frm);
	},

	setup(frm) {
		// No "Get Items From": depot invoices are filled by Ambil Tagihan or typed by hand.
		// ERPNext builds the whole dropdown in this one method, on refresh and on is_return.
		frm.cscript.toggle_get_items = () => {};
		// With editable_grid off, Frappe renders ERPNext's item card template (item_grid.html:
		// Rate / Amount plus stacked details) instead of the columns. The M&R grid has none.
		frm.fields_dict.items.grid.template = null;
		// A line's rate is Harga × kurs, nothing else. ERPNext's item fetch, price-list and
		// margin handlers all derive rate from the Price List through this one method (by
		// plain assignment, no event), which billed a no-contract item at list price.
		frm.cscript.apply_pricing_rule_on_item = (item) => line_rate(frm, item.doctype, item.name);
		// The contract defaults go on AFTER ERPNext's own item fetch: in v16 that is a server
		// round trip (process_item_selection) whose returned doc overwrites the row, so
		// defaults applied first were wiped and the Price List rate billed instead. Calling
		// ERPNext first puts its request in flight, and item_defaults waits for it.
		const item_code = frm.cscript.item_code;
		frm.cscript.item_code = function (doc, cdt, cdn) {
			const out = item_code.apply(this, arguments);
			item_defaults(frm, cdt, cdn);
			return out;
		};
		// Create menu: the depot ships no goods (Delivery Note), does no factoring (Invoice
		// Discounting) and runs no after-sales visits (Maintenance Schedule). ERPNext adds these
		// in its cscript refresh, which runs after ours, so they come off right behind it.
		// Same for Due Date's asterisk: left empty, the server fills it (the customer's Payment
		// Terms, else the Invoice Date: SalesInvoice.set_missing_values).
		const refresh = frm.cscript.refresh;
		frm.cscript.refresh = function () {
			const out = refresh.apply(this, arguments);
			frm.toggle_reqd("due_date", false);
			for (const label of ["Delivery Note", "Invoice Discounting", "Maintenance Schedule"]) {
				frm.remove_custom_button(label, "Create");
			}
			return out;
		};
		// Ending an invoice is ONE red "Cancel", as on every depot form (cancel_button.js, user
		// 2026-09-29): see refresh. So the "…" menu loses Discard and Delete, Frappe's grey Cancel
		// goes, and so do the editor conveniences. Filtered where Frappe adds them, so their
		// shortcuts go as well; the menu is rebuilt on every refresh_header. Duplicate is off
		// natively (allow_copy).
		const hidden_menu = new Set([
			...["Discard", "Delete", "Toggle Sidebar", "Jump to field", "Show Links", "Copy to Clipboard",
				"Remind Me", "Undo", "Redo", "Customize", "Edit DocType"].map((l) => __(l)),
			__("New {0}", [__(frm.doctype)]),
		]);
		const add_menu_item = frm.page.add_menu_item;
		frm.page.add_menu_item = function (label, ...rest) {
			if (!hidden_menu.has(label)) return add_menu_item.call(this, label, ...rest);
		};
		if (frm.toolbar) frm.toolbar.can_cancel = () => false;
		// Cancel must not offer to cancel the orders too ("Cancel All"): our on_cancel hooks
		// unlink them (resync_booking_on_invoice_cancel, rollback_billed_sources) before
		// Frappe's back-link check. Merged on every assignment: ERPNext's onload replaces the
		// list and, on a cold open, lands after our refresh.
		const keep = (list) => [...new Set([...(list || []), "Container Booking", "Cleaning Order"])];
		let ignored = keep(frm.ignore_doctypes_on_cancel_all);
		Object.defineProperty(frm, "ignore_doctypes_on_cancel_all", {
			configurable: true,
			get: () => ignored,
			set: (list) => (ignored = keep(list)),
		});
	},

	refresh(frm) {
		lock_billed_lines(frm);
		charge_hints(frm);
		render_sources(frm);
		render_attachments(frm);
		// Required on the form; the picker only offers the user's own branches (User
		// Permission on Branch). System drafts may still lack one — submit refuses them.
		frm.toggle_reqd("branch", true);
		// ponytail: required on the form only. Drafts the system raises for a customer with no
		// Address still insert; add a before_submit check (like check_branch) if API submits matter.
		frm.toggle_reqd("customer_address", true);
		// Picked first; fixed once orders of that type are on the invoice (to change it: Cancel,
		// which gives the orders back). Old drafts may still pick.
		frm.toggle_reqd("depot_invoice_type", true);
		frm.toggle_enable("depot_invoice_type", !(frm.doc.depot_billed_sources && frm.doc.depot_invoice_type));
		// Like the M&R picker: the whole catalogue, most-used first.
		// Set on refresh because ERPNext's selling controller sets its own on onload.
		frm.set_query("item_code", "items", () => ({ query: "container_depot.invoicing.invoice_item_query" }));
		// One red Cancel, first in the toolbar like on every depot form: a draft is discarded
		// (kept, Cancelled), a submitted invoice cancelled. Both give the orders back
		// (on_discard / on_cancel: rollback_billed_sources); a paid one refuses (check_no_payments).
		if (!frm.is_new() && frm.doc.docstatus === 0 && frm.perm[0].write) {
			container_depot.cancel_button(frm, () => frm._discard());
		} else if (frm.doc.docstatus === 1 && frm.perm[0].cancel) {
			container_depot.cancel_button(frm, () => frm.savecancel());
		}
		// Pilih Order is a Button field under Invoice Type (install.py), not a toolbar button.
		frm.set_df_property("depot_get_bill", "label", frm.doc.depot_billed_sources ? __("Tambah / Lepas Order") : __("Pilih Order"));
		// Styled like the items grid's "Add row" (user, 2026-09-29); Frappe has no Button colour for it.
		frm.fields_dict.depot_get_bill?.$input?.removeClass("btn-default").addClass("btn-secondary");
	},

	depot_get_bill: preview_then_fill,
	// Print Rate is to IDR, like every kurs here; the print divides by it (OAK Invoice).
	depot_print_currency(frm) {
		const ccy = frm.doc.depot_print_currency;
		if (!ccy || ccy === frm.doc.currency) return frm.set_value("depot_print_rate", 0);
		frappe
			.call("container_depot.invoicing.kurs_idr", { currency: ccy, date: frm.doc.posting_date })
			.then((r) => frm.set_value("depot_print_rate", flt(r.message)));
	},
	depot_view_bill_group(frm) {
		frappe.set_route("List", "Sales Invoice", { depot_bill_group: frm.doc.depot_bill_group });
	},
	// Draft: discard, on_trash rolls the orders back. Submitted: cancel, on_cancel does.
});

// --- Charges: labour, discount, PPN / PPh / Materai -----------------------------------
// The server rebuilds all of this on save (invoicing.build_charges). This mirrors it so the
// totals move as the user types instead of only after Save:
//
//     Net Total -> Manhour (Actual) -> PPN / PPh on (Net Total + Manhour) -> Materai
//
// Each line carries its labour TARIFF per hour (never scaled by qty, never in its amount);
// the header totals them and, with Tagih Manhour ticked, charges them once × Total Jam.
const MANHOUR_CHARGE = "Manhour";
const MANAGED_CHARGES = [MANHOUR_CHARGE, "PPN", "PPh 23", "Materai"];

// Labour posts exactly where the item lines do — same revenue, charged once as a flat amount.
function item_posting(frm) {
	const item = (frm.doc.items || []).find((i) => i.income_account);
	return item ? { account: item.income_account, cost_center: item.cost_center } : null;
}

// Tax accounts come from Depot Finance Settings; fetched once per form.
function tax_accounts(frm) {
	if (frm.__oak_tax_accounts) return Promise.resolve(frm.__oak_tax_accounts);
	return frappe
		.call("container_depot.invoicing.tax_accounts", { company: frm.doc.company })
		.then((r) => (frm.__oak_tax_accounts = r.message || {}));
}

async function rebuild_charges(frm) {
	if (frm.doc.docstatus !== 0) return;
	const acc = await tax_accounts(frm);
	// Σ the lines' labour tariffs (each in its own currency, through its kurs) × Total Jam when
	// Tagih Manhour is ticked, as invoicing.apply_manhour_charge does on save.
	const conv = flt(frm.doc.conversion_rate) || 1;
	let tariff = 0;
	for (const row of frm.doc.items || []) tariff += (flt(row.manhour) * (flt(row.depot_kurs) || conv)) / conv;
	const labour = frm.doc.depot_bill_manhour ? tariff * flt(frm.doc.manhour_hour) : 0;
	frm.doc.total_manhour = tariff;
	frm.doc.manhour_amount = labour;

	const [dmode, dnum] = container_depot.parse_smart(frm.doc.discount_input);
	frm.doc.apply_discount_on = "Net Total";
	frm.doc.additional_discount_percentage = dmode === "pct" ? dnum : 0;
	frm.doc.discount_amount = dmode === "amt" ? dnum : 0;

	const managed_accounts = [acc.ppn, acc.pph, acc.materai].filter(Boolean);
	const kept = (frm.doc.taxes || []).filter(
		(t) => !MANAGED_CHARGES.includes((t.description || "").trim()) && !managed_accounts.includes(t.account_head)
	);
	const posting = item_posting(frm);
	const rows = [];
	if (labour && posting) {
		rows.push({
			charge_type: "Actual",
			description: MANHOUR_CHARGE,
			account_head: posting.account,
			cost_center: posting.cost_center,
			tax_amount: labour,
		});
	}
	// Percentages stand on Net Total + labour when there is labour: "running total after row 1".
	const basis = rows.length ? { charge_type: "On Previous Row Total", row_id: "1" } : { charge_type: "On Net Total" };
	const add = (desc, account, mode, num, sign) => {
		if (!num || !account) return;
		const row = { description: desc, account_head: account, cost_center: posting && posting.cost_center };
		if (mode === "pct") Object.assign(row, basis, { rate: sign * num });
		else Object.assign(row, { charge_type: "Actual", tax_amount: sign * num });
		rows.push(row);
	};
	if (!frm.doc.ignore_tax) add("PPN", acc.ppn, ...container_depot.parse_smart(frm.doc.tax_input), 1);
	add("PPh 23", acc.pph, ...container_depot.parse_smart(frm.doc.pph_input), -1);
	add("Materai", acc.materai, "amt", flt(frm.doc.materai), 1);

	const kept_rows = kept.map((t) => {
		const r = Object.assign({}, t);
		delete r.name;
		delete r.idx;
		if (r.charge_type === "On Net Total") Object.assign(r, basis);
		return r;
	});
	frm.clear_table("taxes");
	for (const r of rows.concat(kept_rows)) frm.add_child("taxes", r);
	frm.refresh_fields(["taxes", "total_manhour", "manhour_amount"]);
	if (frm.cscript.calculate_taxes_and_totals) await frm.cscript.calculate_taxes_and_totals();
	charge_hints(frm);
}

// The erp_cakra hint: what each box came to, "= Rp X", under it. Read off the (hidden) tax
// rows, so a saved or submitted invoice shows exactly what it charged.
function charge_hints(frm) {
	const charged = (match) =>
		(frm.doc.taxes || []).filter((t) => match((t.description || "").trim())).reduce((s, t) => s + flt(t.tax_amount), 0);
	const hint = (field, amount, filled) =>
		frm.set_df_property(
			field,
			"description",
			filled ? "= " + format_currency(amount, frm.doc.currency) : __('Ketik mis. "10%" atau "50000"')
		);
	hint("discount_input", frm.doc.discount_amount, frm.doc.discount_input);
	hint("pph_input", -charged((d) => d === "PPh 23"), frm.doc.pph_input);
	if (frm.doc.ignore_tax) frm.set_df_property("tax_input", "description", __("PPN tidak ditagih (Tanpa PPN)"));
	else hint("tax_input", charged((d) => d.startsWith("PPN")), frm.doc.tax_input); // "PPN 11%": old template rows
}

// --- Per-line currency -------------------------------------------------------------------
// rate = Harga × Kurs IDR baris / Kurs IDR invoice. A line in the invoice currency takes the
// invoice kurs and its price as-is. The server does the same on save (invoicing.build_charges).
function line_rate(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row) return;
	if (!row.depot_currency) row.depot_currency = frm.doc.currency;
	let rate;
	if (row.depot_currency === frm.doc.currency) {
		row.depot_kurs = flt(frm.doc.conversion_rate) || 1;
		rate = flt(row.depot_price);
	} else {
		rate = (flt(row.depot_price) * flt(row.depot_kurs)) / (flt(frm.doc.conversion_rate) || 1);
	}
	if (flt(row.rate) !== flt(rate)) frappe.model.set_value(cdt, cdn, "rate", rate);
	else frm.refresh_field("items");
}

function all_line_rates(frm) {
	for (const row of frm.doc.items || []) line_rate(frm, row.doctype, row.name);
}

function fetch_kurs(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row.depot_currency || row.depot_currency === frm.doc.currency) return line_rate(frm, cdt, cdn);
	// Same currency elsewhere on the invoice: reuse its kurs so one bill has one rate per currency.
	const twin = (frm.doc.items || []).find(
		(r) => r.name !== row.name && r.depot_currency === row.depot_currency && flt(r.depot_kurs)
	);
	if (twin) {
		row.depot_kurs = twin.depot_kurs;
		return line_rate(frm, cdt, cdn);
	}
	frappe
		.call("container_depot.invoicing.kurs_idr", { currency: row.depot_currency, date: frm.doc.posting_date })
		.then((r) => {
			row.depot_kurs = flt(r.message);
			line_rate(frm, cdt, cdn);
		});
}

// A hand-picked item starts at its contract price (in the contract's currency), with the labour
// tariff the contract row states. Only a starting point, like on the orders: edit freely. Waits for
// ERPNext's own item fetch so that one cannot land on top of it, and re-reads the row after
// it, since that fetch may have replaced the row object.
function item_defaults(frm, cdt, cdn) {
	const picked = locals[cdt][cdn];
	if (!picked.item_code || picked.depot_source) return;
	frappe.after_ajax(() =>
		frappe
			.call("container_depot.invoicing.item_defaults", {
				customer: frm.doc.customer,
				item_code: picked.item_code,
				currency: frm.doc.currency,
				posting_date: frm.doc.posting_date,
			})
			.then((r) => {
				const d = r.message || {};
				const row = locals[cdt][cdn];
				if (!row || row.item_code !== picked.item_code) return; // re-picked meanwhile
				Object.assign(row, {
					depot_currency: d.depot_currency || frm.doc.currency,
					depot_price: flt(d.depot_price),
					depot_kurs: flt(d.depot_kurs),
					manhour: flt(d.manhour),
				});
				line_rate(frm, cdt, cdn);
				rebuild_charges(frm);
			})
	);
}

// Lines billed from an order are locked server-side; show them read-only in the grid too.
const LOCKED_LINE_FIELDS = ["item_code", "qty", "depot_price", "depot_currency", "manhour"];
function lock_billed_lines(frm) {
	for (const row of frm.doc.items || []) {
		if (!row.depot_source) continue;
		for (const f of LOCKED_LINE_FIELDS) {
			const df = frappe.meta.get_docfield(row.doctype, f, row.name);
			if (df) df.read_only = 1;
		}
	}
}

frappe.ui.form.on("Sales Invoice", {
	// ERPNext fetches the new currency's conversion_rate itself; re-derive after it lands.
	currency: (frm) => frappe.after_ajax(() => all_line_rates(frm)),
	conversion_rate(frm) {
		all_line_rates(frm);
		rebuild_charges(frm);
	},
	manhour_hour: rebuild_charges,
	depot_bill_manhour: rebuild_charges,
	discount_input: rebuild_charges,
	tax_input: rebuild_charges,
	ignore_tax: rebuild_charges,
	pph_input: rebuild_charges,
	materai: rebuild_charges,
	// A line is filled in its own form, as on the M&R (editable_grid 0, install.py): labelled
	// "Tutup", no Insert Above / Below.
	items_on_form_rendered(frm) {
		container_depot.grid_row_form(frm, "items");
	},
});

frappe.ui.form.on("Sales Invoice Item", {
	depot_price: line_rate,
	depot_kurs: line_rate,
	depot_currency: fetch_kurs,
	// The set_value route to the same thing (apply_pricing_rule_on_item covers the rest).
	rate(frm, cdt, cdn) {
		line_rate(frm, cdt, cdn);
		rebuild_charges(frm);
	},
	manhour: (frm) => rebuild_charges(frm),
	qty: (frm) => rebuild_charges(frm),
	items_remove: (frm) => rebuild_charges(frm),
});
