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
//   In_Depot   — here, but an order (EIR-In / Cleaning / M&R / Periodic Test) is still open.
//   Available  — here with nothing open: free to be booked out.
//   Gate_Out   — has left.
//
// Clicking a badge filters the list to that status.
frappe.listview_settings["Container"] = {
	// Pull status explicitly so the indicator still works when the columns are customised.
	add_fields: ["status"],

	get_indicator(doc) {
		const map = {
			Booked: [__("Dipesan"), "blue", "status,=,Booked"],
			// Deliberately not "In Depo": being here is not the point — the open work is.
			In_Depot: [__("Ada Pekerjaan"), "orange", "status,=,In_Depot"],
			Available: [__("Siap Keluar"), "green", "status,=,Available"],
			Gate_Out: [__("Sudah Keluar"), "gray", "status,=,Gate_Out"],
		};
		return map[doc.status] || [__(doc.status || "-"), "gray", `status,=,${doc.status || ""}`];
	},
};
