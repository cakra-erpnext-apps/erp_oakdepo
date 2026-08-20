// Booking Code — list view. The columns are deliberately thin: the code itself, the
// container it belongs to, and when it was issued. Booking and direction were dropped
// because the list is nearly always reached filtered by one booking, where both columns
// repeat the same value down every row.
//
// `state` still matters (an Active code opens a gate, a Used one does not), so it moves
// out of the columns and into the row pill — visible at a glance, costing no width.

frappe.listview_settings["Booking Code"] = {
	add_fields: ["state"],

	// Colour convention, shared by every Container Depot list (see also
	// cleaning_order_list.js, inspection_list.js, …):
	//   grey = draft / belum jalan · red = dibatalkan or void · blue = the terminal
	//   "done" state · everything in between takes any other colour.
	// A code is issued Active (usable), so its terminal state is Used — that is the one
	// that gets blue. Expired/Reissued are neither done nor cancelled, so they take the
	// warning colours; grey is left to mean draft and nothing else.
	get_indicator(doc) {
		const colours = {
			Active: "green",
			Used: "blue",
			Reissued: "purple",
			Expired: "orange",
			Cancelled: "red",
		};
		return [__(doc.state), colours[doc.state] || "gray", `state,=,${doc.state}`];
	},
};
