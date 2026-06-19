// Depot Contract — the Price List lines are negotiated from a Base Price List.
//
// The Item picker on each line is filtered to Items priced in the contract's
// Base Price List. Picking an Item seeds the line from that Item Price: UoM
// (read-only), Rate and Manhour (editable defaults) which are then negotiated.
// "Get Items from Base Price List" (re)populates the lines from the whole list.
// On Active the contract publishes these lines as a customer Price List named
// after the contract (handled server-side). Each line's currency follows the
// contract currency so Rate / Manhour format in the Base Price List currency.
//
// Status is driven by workflow buttons (set_status), not picked from a dropdown.

function container_depot_transition(frm, target) {
	const go = () =>
		frappe.call({
			method: "container_depot.operations.doctype.depot_contract.depot_contract.set_status",
			args: { contract: frm.doc.name, target },
			freeze: true,
			freeze_message: __("Updating status…"),
			callback: () => frm.reload_doc(),
		});
	frappe.confirm(__("Move this contract to {0}?", [__(target)]), () => {
		// Persist any in-progress edits (e.g. negotiated lines) before transitioning.
		if (frm.is_dirty()) frm.save().then(go);
		else go();
	});
}

frappe.ui.form.on("Depot Contract", {
	onload(frm) {
		frm.trigger("_set_tariff_item_query");
	},
	refresh(frm) {
		frm.trigger("_set_tariff_item_query");
		frm.trigger("_set_status_actions");
		frm.trigger("_set_bulk_buttons");
		frm.trigger("_apply_edit_lock");
	},
	_set_status_actions(frm) {
		if (frm.is_new()) return;
		// Status is set by these buttons (the field is read-only), following the flow
		// Draft -> Negotiation -> Active -> Expired, with Void to cancel.
		const ACTIONS = {
			Draft: [["Start Negotiation", "Negotiation", "primary"], ["Cancel", "Void"]],
			Negotiation: [["Activate", "Active", "primary"], ["Back to Draft", "Draft"], ["Cancel", "Void"]],
			Active: [["Expire", "Expired"], ["Void", "Void"]],
		};
		(ACTIONS[frm.doc.status] || []).forEach(([label, target, type]) => {
			const btn = frm.add_custom_button(__(label), () => container_depot_transition(frm, target));
			if (type === "primary") btn.removeClass("btn-default").addClass("btn-primary");
		});
	},
	_set_bulk_buttons(frm) {
		// Fast ways to fill the Price List lines: by menu (filter) or pasted from Excel.
		// Only while the contract is still editable.
		const editable = frm.is_new() || ["Draft", "Negotiation"].includes(frm.doc.status);
		if (!editable) return;
		const group = __("Price List");

		// "Add Items" — multi-select Items; each picked item becomes its own line
		// (UoM defaults from the item; rate + manhour rate are always 0 for manual
		// pricing). Already-added items are skipped so saving never hits a duplicate.
		frm.add_custom_button(
			__("Add Items"),
			() => {
				new frappe.ui.form.MultiSelectDialog({
					doctype: "Item",
					target: frm,
					setters: { item_group: null },
					add_filters_group: 1,
					get_query() {
						return { filters: { disabled: 0, is_sales_item: 1 } };
					},
					action(selections) {
						if (!selections || !selections.length) return;
						const existing = new Set((frm.doc.tariff_lines || []).map((r) => r.item));
						const fresh = selections.filter((i) => !existing.has(i));
						if (!fresh.length) {
							frappe.show_alert({
								message: __("All selected items are already added."),
								indicator: "orange",
							});
							return;
						}
						frappe.db
							.get_list("Item", {
								filters: { name: ["in", fresh] },
								fields: ["name", "stock_uom"],
								limit: 0,
							})
							.then((items) => {
								const uom = {};
								items.forEach((it) => (uom[it.name] = it.stock_uom));
								fresh.forEach((code) => {
									const row = frm.add_child("tariff_lines");
									row.item = code;
									row.uom = uom[code] || null;
									row.rate = 0;
									row.manhour_rate = 0;
									row.currency = frm.doc.currency;
								});
								frm.refresh_field("tariff_lines");
								frappe.show_alert({
									message: __("Added {0} item(s).", [fresh.length]),
									indicator: "green",
								});
							});
					},
				});
			},
			group
		);

		// "Add from Menu" — bulk-add the Base Price List items of a chosen Depot
		// Service Menu (e.g. all Maintenance items). Client-side; no save needed.
		frm.add_custom_button(
			__("Add from Menu"),
			() => {
				if (!frm.doc.base_price_list) {
					frappe.msgprint(__("Select a Base Price List first."));
					return;
				}
				const d = new frappe.ui.Dialog({
					title: __("Add items from menu"),
					fields: [
						{
							fieldname: "menu",
							fieldtype: "Link",
							options: "Depot Service Menu",
							label: __("Service Menu"),
							reqd: 1,
							get_query: () => ({ filters: { is_active: 1 } }),
						},
						{ fieldname: "replace", fieldtype: "Check", label: __("Replace existing lines") },
					],
					primary_action_label: __("Add"),
					primary_action(values) {
						frappe.call({
							method: "container_depot.operations.doctype.depot_contract.depot_contract.base_price_list_lines_for_menu",
							args: { base_price_list: frm.doc.base_price_list, menu: values.menu },
							callback(r) {
								const rows = r.message || [];
								if (values.replace) frm.clear_table("tariff_lines");
								rows.forEach((ln) => {
									const row = frm.add_child("tariff_lines");
									row.item = ln.item;
									row.uom = ln.uom;
									row.rate = ln.rate;
									row.manhour_rate = ln.manhour_rate;
									row.currency = frm.doc.currency;
								});
								frm.refresh_field("tariff_lines");
								d.hide();
								frappe.show_alert({
									message: __("Added {0} line(s) from {1}.", [rows.length, values.menu]),
									indicator: "green",
								});
							},
						});
					},
				});
				d.show();
			},
			group
		);

		// "Paste from Excel" — server-side import (needs a saved contract).
		frm.add_custom_button(
			__("Paste from Excel"),
			() => {
				if (frm.is_new()) {
					frappe.msgprint(__("Save the contract once before pasting lines."));
					return;
				}
				if (!frm.doc.base_price_list) {
					frappe.msgprint(__("Select a Base Price List first (it fills missing rate / UoM)."));
					return;
				}
				const d = new frappe.ui.Dialog({
					title: __("Paste from Excel"),
					fields: [
						{
							fieldname: "hint",
							fieldtype: "HTML",
							options: `<p class="text-muted small">${__(
								"One item per line. Columns (tab or comma): Item, Rate, Manhour Rate, UoM. Only Item is required — the rest default from the Base Price List."
							)}</p>`,
						},
						{ fieldname: "text", fieldtype: "Small Text", label: __("Rows"), reqd: 1 },
						{ fieldname: "replace", fieldtype: "Check", label: __("Replace existing lines") },
					],
					primary_action_label: __("Import"),
					primary_action(values) {
						frappe.call({
							method: "container_depot.operations.doctype.depot_contract.depot_contract.import_tariff_lines",
							args: { contract: frm.doc.name, text: values.text, replace: values.replace ? 1 : 0 },
							freeze: true,
							freeze_message: __("Importing…"),
							callback(r) {
								const m = r.message || {};
								d.hide();
								frm.reload_doc();
								let msg = __("Added {0}, skipped {1}. Total {2} line(s).", [
									m.added || 0,
									m.skipped || 0,
									m.total_lines || 0,
								]);
								if ((m.errors || []).length) {
									msg += "<br><b>" + __("Not imported:") + "</b><br>" + m.errors.join("<br>");
									frappe.msgprint({
										title: __("Import finished with warnings"),
										message: msg,
										indicator: "orange",
									});
								} else {
									frappe.show_alert({ message: msg, indicator: "green" });
								}
							},
						});
					},
				});
				d.show();
			},
			group
		);
	},
	_apply_edit_lock(frm) {
		// Editable only in Draft / Negotiation; Active and terminal states are locked.
		const locked = !frm.is_new() && !["Draft", "Negotiation"].includes(frm.doc.status);
		[
			"customer", "currency", "base_price_list", "payment_type", "payment_terms",
			"credit_limit", "valid_from", "valid_to", "tariff_lines", "generate_lines",
			"company_docs", "esign_status", "signed_pdf",
		].forEach((f) => frm.set_df_property(f, "read_only", locked ? 1 : 0));
		if (frm.fields_dict.tariff_lines) {
			frm.fields_dict.tariff_lines.grid.cannot_add_rows = locked;
			frm.fields_dict.tariff_lines.grid.cannot_delete_rows = locked;
		}
	},
	currency(frm) {
		frm.trigger("_sync_line_currency");
	},
	base_price_list(frm) {
		frm.trigger("_set_tariff_item_query");
		if (!frm.doc.base_price_list) return;
		// Bind currency to the base rate card (published Item Prices inherit the
		// Price List currency). Lines are generated only on the button.
		frappe.db.get_value("Price List", frm.doc.base_price_list, "currency").then((r) => {
			if (r.message && r.message.currency) frm.set_value("currency", r.message.currency);
		});
	},
	generate_lines(frm) {
		frm.trigger("_generate_lines_from_base");
	},
	_set_tariff_item_query(frm) {
		// Base Price List picker: only customer-less rate cards that have Item Prices.
		frm.set_query("base_price_list", () => ({
			query: "container_depot.operations.doctype.depot_contract.depot_contract.base_price_list_query",
		}));
		frm.set_query("item", "tariff_lines", () => ({
			query: "container_depot.operations.doctype.depot_contract.depot_contract.tariff_item_query",
			filters: { base_price_list: frm.doc.base_price_list },
		}));
	},
	_sync_line_currency(frm) {
		(frm.doc.tariff_lines || []).forEach((row) => {
			row.currency = frm.doc.currency;
		});
		frm.refresh_field("tariff_lines");
	},
	_generate_lines_from_base(frm) {
		if (!frm.doc.base_price_list) {
			frappe.msgprint(__("Select a Base Price List first."));
			return;
		}
		frappe.call({
			method: "container_depot.operations.doctype.depot_contract.depot_contract.base_price_list_lines",
			args: { base_price_list: frm.doc.base_price_list },
			callback(r) {
				const rows = r.message || [];
				// Reset first so repeated clicks always mirror the base list.
				frm.clear_table("tariff_lines");
				if (!rows.length) {
					frm.refresh_field("tariff_lines");
					frappe.msgprint(
						__("No selling Item Prices found in {0}. Lines cleared.", [frm.doc.base_price_list])
					);
					return;
				}
				rows.forEach((d) => {
					const row = frm.add_child("tariff_lines");
					row.item = d.item;
					row.uom = d.uom;
					row.rate = d.rate;
					row.manhour_rate = d.manhour_rate;
					row.currency = frm.doc.currency;
				});
				frm.refresh_field("tariff_lines");
				frappe.show_alert({
					message: __("Added {0} line(s) from {1}.", [rows.length, frm.doc.base_price_list]),
					indicator: "green",
				});
			},
		});
	},
});

frappe.ui.form.on("Tariff Rate", {
	item(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item) return;
		if (!frm.doc.base_price_list) {
			// No Base Price List: allow any service item. Default the UoM from the
			// item itself; the rate is entered manually (no base list to copy from).
			frappe.db.get_value("Item", row.item, "stock_uom", (r) => {
				if (r && r.stock_uom) frappe.model.set_value(cdt, cdn, "uom", r.stock_uom);
				frappe.model.set_value(cdt, cdn, "currency", frm.doc.currency || null);
			});
			return;
		}
		frappe.call({
			method: "container_depot.operations.doctype.depot_contract.depot_contract.item_price_defaults",
			args: { base_price_list: frm.doc.base_price_list, item: row.item },
			callback(r) {
				const d = r.message;
				if (!d) return;
				frappe.model.set_value(cdt, cdn, "uom", d.uom || null);
				frappe.model.set_value(cdt, cdn, "rate", d.rate || 0);
				frappe.model.set_value(cdt, cdn, "manhour_rate", d.manhour_rate || 0);
				frappe.model.set_value(cdt, cdn, "currency", frm.doc.currency || null);
			},
		});
	},
});
