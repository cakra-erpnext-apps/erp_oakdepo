// Purchase Receipt is the "Barang Masuk" menu of the Sparepart & Stock section.
// The depot only receives physical spare parts into a warehouse here — no freight,
// no service lines — so the item picker is narrowed to stockable items.
//
// ERPNext leaves the picker open on purpose (buying.js filters only for
// subcontracting), which in this catalog means 145 service items crowd out the one
// item that can actually be stocked. We keep ERPNext's own filters and just add
// is_stock_item, because dropping `supplier` would lose the Party Specific Item
// restriction. Set in refresh so it wins over BuyingController.setup()'s query.
frappe.ui.form.on("Purchase Receipt", {
	refresh(frm) {
		// Subcontracting deliberately wants NON-stock items — leave that path alone.
		if (frm.doc.is_subcontracted) return;
		frm.set_query("item_code", "items", () => ({
			query: "erpnext.controllers.queries.item_query",
			filters: {
				supplier: frm.doc.supplier,
				is_purchase_item: 1,
				has_variants: 0,
				is_stock_item: 1,
			},
		}));
	},
});
