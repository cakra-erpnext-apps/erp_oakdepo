frappe.listview_settings["Leak Check"] = {
	add_fields: ["status", "has_leak"],
	get_indicator(doc) {
		if (doc.status === "Open") return container_depot.status_pill("ready", "status,=,Open");
		return doc.has_leak
			? [__("Bocor"), "red", "has_leak,=,1"]
			: [__("Aman"), "green", "has_leak,=,0"];
	},
};
