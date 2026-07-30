// Periodic Test Order — Desk form behaviour.
//
// The Used-Items picker is scoped exactly like M&R's: the "Periodic Test" Depot Service Menu
// ∩ the owner's price list (resolved server-side in used_item_query). Without this the field
// offered the entire Item catalogue, so a test could be billed with an item the owner has no
// contract rate for.
frappe.ui.form.on("Periodic Test Order", {
	setup(frm) {
		frm.trigger("_set_queries");
	},
	onload(frm) {
		frm.trigger("_set_queries");
	},
	refresh(frm) {
		frm.trigger("_set_queries");
	},
	_set_queries(frm) {
		frm.set_query("item", "used_items", () => ({
			query:
				"container_depot.operations.doctype.periodic_test_order.periodic_test_order.used_item_query",
			// Read off the saved doc: the price list follows the container's owner, which is
			// fetched on save, so an unsaved order simply falls back to the open catalogue.
			filters: { periodic_test_order: frm.doc.name || "" },
		}));
		// Only real (non-group) warehouses can issue a part.
		frm.set_query("warehouse", "used_items", () => ({ filters: { is_group: 0 } }));
	},
});
