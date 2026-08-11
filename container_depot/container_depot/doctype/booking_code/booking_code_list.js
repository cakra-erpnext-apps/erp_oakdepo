// Booking Code — list view. The columns are deliberately thin: the code itself, the
// container it belongs to, and when it was issued. Booking and direction were dropped
// because the list is nearly always reached filtered by one booking, where both columns
// repeat the same value down every row.
//
// `state` still matters (an Active code opens a gate, a Used one does not), so it moves
// out of the columns and into the row pill — visible at a glance, costing no width.

frappe.listview_settings["Booking Code"] = {
	add_fields: ["state"],

	get_indicator(doc) {
		const colours = {
			Active: "green",
			Used: "blue",
			Reissued: "orange",
			Expired: "gray",
			Cancelled: "red",
		};
		return [__(doc.state), colours[doc.state] || "gray", `state,=,${doc.state}`];
	},
};
