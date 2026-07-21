// "Tarik Email" — desk mirror of the Email Account "Pull Emails" button, on the
// Communication list so operators can fetch new mail where they read it. Scoped to the
// incoming Email Accounts set on the user (see operations/mail_to_order.pull_my_emails).

frappe.listview_settings["Communication"] = frappe.listview_settings["Communication"] || {};

const _cd_onload = frappe.listview_settings["Communication"].onload;
frappe.listview_settings["Communication"].onload = function (listview) {
	if (typeof _cd_onload === "function") _cd_onload(listview);

	listview.page.add_inner_button(__("Tarik Email"), () => {
		frappe.dom.freeze(__("Menarik email…"));
		frappe.call({ method: "container_depot.operations.mail_to_order.pull_my_emails" })
			.then(() => {
				frappe.dom.unfreeze();
				listview.refresh();
			})
			.catch(() => frappe.dom.unfreeze());
	});
};
