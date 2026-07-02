// Survey Order — third-party survey charges billed to a customer (Paid To).
// One charge row per container; currency & total live on the header.
frappe.ui.form.on("Survey Order", {
	setup(frm) {
		// Item picker on the charge grid follows the header price list (re-read each open).
		frm.set_query("item", "charges", () => {
			if (!frm.doc.price_list) {
				return { filters: { is_sales_item: 1 } }; // no price list → any sellable item
			}
			return {
				query: "container_depot.operations.doctype.survey_order.survey_order.item_price_query",
				filters: { price_list: frm.doc.price_list },
			};
		});
	},

	refresh(frm) {
		if (frm.doc.sales_invoice) {
			frm.add_custom_button(__("Sales Invoice"), () =>
				frappe.set_route("Form", "Sales Invoice", frm.doc.sales_invoice), __("View"));
		}
	},

	paid_to(frm) {
		if (!frm.doc.paid_to) {
			frm.set_value("price_list", null);
			return;
		}
		frappe.call({
			method: "container_depot.operations.doctype.survey_order.survey_order.get_pricing_context",
			args: { customer: frm.doc.paid_to },
			callback(r) {
				const ctx = r.message || {};
				frm.set_value("price_list", ctx.price_list || null);
				if (ctx.currency) frm.set_value("currency", ctx.currency);
				sync_charge_currency(frm);
				if (!ctx.price_list) {
					frappe.show_alert({
						message: __("Paid To ini belum punya default Price List — harga charge diisi manual."),
						indicator: "orange",
					});
				}
			},
		});
	},

	// Currency is header-level; push it into every charge row so the grid's Price
	// column formats with the chosen currency. The child `currency` field drives
	// the Price field's `options`, and its fetch_from only fills on save — so we
	// sync it live here.
	currency(frm) {
		sync_charge_currency(frm);
	},
});

// Charge grid: item picker filtered by the header price list; auto-price; header total.
frappe.ui.form.on("Survey Order Charge", {
	charges_add(frm, cdt, cdn) {
		// New row inherits the header currency so its Price cell formats correctly.
		if (frm.doc.currency) frappe.model.set_value(cdt, cdn, "currency", frm.doc.currency);
		compute_total(frm);
	},
	charges_remove: (frm) => compute_total(frm),

	item(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item || !frm.doc.price_list) return;
		frappe.call({
			method: "container_depot.operations.doctype.survey_order.survey_order.get_item_price",
			args: { item: row.item, price_list: frm.doc.price_list },
			callback(r) {
				if (r.message !== undefined && r.message !== null) {
					frappe.model.set_value(cdt, cdn, "price", r.message);
				}
			},
		});
	},

	price: (frm) => compute_total(frm),
});

function compute_total(frm) {
	const total = (frm.doc.charges || []).reduce((s, c) => s + flt(c.price), 0);
	frm.set_value("total", total);
}

// Copy the header currency onto every charge row and re-render the grid so the
// Price column shows the selected currency's symbol/format immediately.
function sync_charge_currency(frm) {
	(frm.doc.charges || []).forEach((row) => {
		if (frm.doc.currency && row.currency !== frm.doc.currency) {
			frappe.model.set_value(row.doctype, row.name, "currency", frm.doc.currency);
		}
	});
	frm.refresh_field("charges");
}
