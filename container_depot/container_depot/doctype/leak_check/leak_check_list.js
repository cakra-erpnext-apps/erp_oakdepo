frappe.listview_settings["Leak Check"] = {
	add_fields: ["status", "has_leak", "closed_by_admin"],
	// Submittable since 2026-10-02: without these Frappe paints its own red "Draft" /
	// "Cancelled" and never asks get_indicator below.
	has_indicator_for_draft: 1,
	has_indicator_for_cancelled: 1,
	get_indicator(doc) {
		if (doc.docstatus === 2) return container_depot.status_pill("cancelled", "docstatus,=,2");
		if (doc.docstatus === 1 && doc.closed_by_admin) return container_depot.status_pill("closed", "closed_by_admin,=,1");
		if (doc.status === "Open") return container_depot.status_pill("ready", "status,=,Open");
		return doc.has_leak
			? [__("Bocor"), "red", "has_leak,=,1"]
			: [__("Aman"), "green", "has_leak,=,0"];
	},
};
