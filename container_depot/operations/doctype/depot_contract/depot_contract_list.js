// Depot Contract list view — one colour per status. Without this every status
// falls back to Frappe's guessed colour, which gave Draft and Void near-identical
// pills even though one is "belum berlaku" and the other "dibatalkan".
//
// Draft    grey   — not in force yet, still editable (and the only deletable state)
// Active   green  — the contract in force; its Price List is the live one
// Expired  orange — ran past valid_to
// Void     red    — cancelled / invalidated, never to be used again
// Amended  blue   — replaced by a newer contract (see Amendment Of on the successor)
frappe.listview_settings["Depot Contract"] = {
	add_fields: ["status", "valid_to"],

	get_indicator(doc) {
		const COLOURS = {
			Draft: "grey",
			Active: "green",
			Expired: "orange",
			Void: "red",
			Amended: "blue",
		};
		const colour = COLOURS[doc.status] || "grey";
		return [__(doc.status), colour, `status,=,${doc.status}`];
	},
};
