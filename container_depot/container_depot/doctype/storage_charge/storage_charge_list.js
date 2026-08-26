frappe.listview_settings["Storage Charge"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		return {
			Berjalan: [__("Berjalan"), "blue", "status,=,Berjalan"],
			Unpaid: [__("Unpaid"), "orange", "status,=,Unpaid"],
			"Partly Paid": [__("Partly Paid"), "yellow", "status,=,Partly Paid"],
			Paid: [__("Paid"), "green", "status,=,Paid"],
		}[doc.status];
	},
};
