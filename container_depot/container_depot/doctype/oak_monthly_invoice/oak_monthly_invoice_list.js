// Copyright (c) 2026, Oak Depot Team and contributors
// For license information, please see license.txt

// Oak Monthly Invoice list view. Submittable with its own Unpaid/Paid/Cancelled status, so
// without this every unsubmitted row showed the stock red "Draft" and a Paid one looked the
// same as an Unpaid one.
//
// Colour convention, shared by every Container Depot list:
//   grey — Draf (docstatus 0, belum diterbitkan) · red — dibatalkan
//   blue — Lunas, the terminal state · others — the stages in between
frappe.listview_settings["OAK Monthly Invoice"] = {
	add_fields: ["status"],
	has_indicator_for_draft: 1,
	has_indicator_for_cancelled: 1,

	get_indicator(doc) {
		if (doc.docstatus === 2 || doc.status === "Cancelled") {
			return [__("Dibatalkan"), "red", "status,=,Cancelled"];
		}
		if (doc.docstatus === 0) return [__("Draf"), "gray", "docstatus,=,0"];
		if (doc.status === "Paid") return [__("Lunas"), "blue", "status,=,Paid"];
		return [__("Belum Dibayar"), "orange", "status,=,Unpaid"];
	},
};
