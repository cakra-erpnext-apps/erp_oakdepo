// The depot's Item pickers only PICK — they never create.
//
// A Frappe Link dropdown ends with "Create a new Item", which drops a bare Item into the
// catalogue from inside an order: no item group, no UOM, and above all no Item Price. Such
// an item bills at zero and then hides forever among the ~145 service items. Items belong to
// Pricing -> Item, where the tariff is set next to them.
//
// `only_select` is the framework's own flag for this (see link.js). It also drops the
// dropdown's "Advanced Search" link, which is acceptable here: each picker runs a server
// query that already searches the whole catalogue by code and name, with the most-used
// items first (container_depot.item_catalog) — Advanced Search only adds a second, worse
// way to reach the same rows.
//
// This file is loaded per doctype via hooks.doctype_js, so it binds once for all of them.
frappe.provide("oak");

// doctype -> [[grid fieldname or null for a header field, link fieldname], ...]
const ITEM_PICKERS = {
	"Container Booking": [[null, "lift_item"]], // Lift Service
	"Cleaning Order": [["cleaning_services", "cleaning_item"]], // Metode Cleaning (Service)
	"Repair Order": [["used_items", "item"]], // Item (Service / Part)
	"Sales Invoice": [["items", "item_code"]],
};

function lock_picker(frm, [parentfield, fieldname]) {
	if (!parentfield) {
		frm.set_df_property(fieldname, "only_select", 1);
		return;
	}
	// Grid docfields are a per-document cache, so the flag survives grid re-renders and is
	// inherited by rows added later; re-applying on refresh covers a doc that was just saved
	// (its docname, hence its cache entry, changes).
	const grid = frm.fields_dict[parentfield] && frm.fields_dict[parentfield].grid;
	if (grid) grid.update_docfield_property(fieldname, "only_select", 1);
}

if (!oak._item_pickers_locked) {
	oak._item_pickers_locked = true;
	for (const [doctype, pickers] of Object.entries(ITEM_PICKERS)) {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				pickers.forEach((picker) => lock_picker(frm, picker));
			},
		});
	}
}
