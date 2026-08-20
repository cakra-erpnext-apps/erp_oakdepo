// Container list view.
//
// `Container.status` stores machine values (Booked / In_Depot / Available / Gate_Out) that
// the whole app branches on, so they are NOT renamed — they are only ever *rendered*
// differently. Left alone, Frappe prints them verbatim and the operator reads "In_Depot",
// which says where the tank is but not the thing they actually want to know: can it leave?
//
// So each status is badged with what it MEANS for the yard, in the same vocabulary the
// gate-out rules use (container_depot/container_status.py):
//
//   Booked     — reserved by an inbound booking, not physically here yet.
//   In_Depot   — here, but an order (EIR-In / Cleaning / M&R) is still open.
//   Available  — here with nothing open: free to be booked out.
//   Gate_Out   — has left.
//
// Clicking a badge filters the list to that status.
//
// A retired tank (Active off) overrides all of it: where it last stood stopped mattering
// the moment it left the fleet, and the one thing to know about the row is that it is out
// of service — otherwise a scrapped tank reads "Sudah Keluar", exactly like one that just
// drove off this morning.
frappe.listview_settings["Container"] = {
	// Pull both explicitly so the indicator still works when the columns are customised.
	add_fields: ["status", "is_active"],

	get_indicator(doc) {
		if (!doc.is_active) return [__("Non-Aktif"), "red", "is_active,=,0"];
		// Colour convention, shared by every Container Depot list: grey = draft,
		// red = dibatalkan / void (here: a retired tank), blue = the terminal state,
		// any other colour = a stage in between. A tank's life ends at Gate_Out, so
		// that is the blue one; grey is reserved for drafts and this doctype has none.
		const map = {
			Booked: [__("Dipesan"), "purple", "status,=,Booked"],
			// Deliberately not "In Depo": being here is not the point — the open work is.
			In_Depot: [__("Ada Pekerjaan"), "orange", "status,=,In_Depot"],
			Available: [__("Siap Keluar"), "green", "status,=,Available"],
			Gate_Out: [__("Sudah Keluar"), "blue", "status,=,Gate_Out"],
		};
		return map[doc.status] || [__(doc.status || "-"), "gray", `status,=,${doc.status || ""}`];
	},
};
