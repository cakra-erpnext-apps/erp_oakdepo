frappe.listview_settings["Leak Check"] = {
	add_fields: ["status", "has_leak"],
	get_indicator(doc) {
		if (doc.status === "Open") return [__("Open"), "orange", "status,=,Open"];
		return doc.has_leak
			? [__("Bocor"), "red", "has_leak,=,1"]
			: [__("Aman"), "green", "has_leak,=,0"];
	},
};
