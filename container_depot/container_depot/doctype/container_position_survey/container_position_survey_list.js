// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

// Container Position Survey list view.
//
// WHY THIS FILE EXISTS: the doctype is submittable and only reaches docstatus 1 at the very
// end (position_survey.approve_position calls doc.submit()), so every open survey — the
// whole worklist — was painted with Frappe's stock red "Draft" and its real status never
// showed. `has_indicator_for_draft` / `_cancelled` turn that default off (see the note in
// cleaning_order_list.js for the mechanism).
//
// Colour convention, shared by every Container Depot list:
//   grey   — draft / belum jalan (a survey with no status yet)
//   red    — dibatalkan
//   blue   — the terminal state: Confirmed ("udah turun", survey submitted)
//   others — the stages in between
frappe.listview_settings["Container Position Survey"] = {
	add_fields: ["status"],
	has_indicator_for_draft: 1,
	has_indicator_for_cancelled: 1,

	get_indicator(doc) {
		// A cancelled survey is cancelled whatever stage its status was left at.
		if (doc.docstatus === 2 || doc.status === "Cancelled") {
			return [__("Dibatalkan"), "red", "status,=,Cancelled"];
		}
		const map = {
			// Menunggu Surveyor mencatat posisi tank di yard.
			"Pending Survey": [__("Menunggu Survei"), "orange", "status,=,Pending Survey"],
			// Posisi sudah dicatat, menunggu Operator Kalmar mengonfirmasi.
			Surveyed: [__("Sudah Disurvei"), "yellow", "status,=,Surveyed"],
			Confirmed: [__("Dikonfirmasi"), "blue", "status,=,Confirmed"],
		};
		return map[doc.status] || [__(doc.status || "Draf"), "gray", `status,=,${doc.status || ""}`];
	},
};
