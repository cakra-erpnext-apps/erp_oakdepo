frappe.listview_settings["Pending Cash"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		return {
			Draft: [__("Draft"), "gray", "status,=,Draft"],
			Validated: [__("Validated"), "blue", "status,=,Validated"],
			Paid: [__("Paid"), "green", "status,=,Paid"],
			Void: [__("Void"), "red", "status,=,Void"],
		}[doc.status || "Draft"];
	},
	onload(listview) {
		const bulk = (label, action) =>
			listview.page.add_actions_menu_item(label, () => {
				const names = listview.get_checked_items(true);
				if (!names.length) return;
				container_depot.pending_cash.run(names, action, {}, () => listview.refresh());
			});
		bulk(__("Validate"), "validate");
		bulk(__("Invalidate"), "invalidate");
		bulk(__("Pay"), "pay");
		bulk(__("Unpaid"), "unpaid");
		bulk(__("Void"), "void");
		bulk(__("Unvoid"), "unvoid");
	},
};
