frappe.listview_settings["Storage Charge"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		return {
			Berjalan: [__("Berjalan"), "yellow", "status,=,Berjalan"],
			Unpaid: [__("Belum Dibayar"), "orange", "status,=,Unpaid"],
			"Partly Paid": [__("Dibayar Sebagian"), "purple", "status,=,Partly Paid"],
			Paid: [__("Lunas"), "blue", "status,=,Paid"],
		}[doc.status];
	},
};
