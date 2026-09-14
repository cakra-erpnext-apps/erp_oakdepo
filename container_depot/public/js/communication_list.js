// "Tarik Email" — desk mirror of the Email Account "Pull Emails" button, on the
// Communication list so operators can fetch new mail where they read it. Scoped to the
// incoming Email Accounts set on the user, and to a date window of at most a week — one
// unbounded pull files hundreds of Communications and buries the booking mail somebody was
// actually looking for (see container_depot/mail_to_order.pull_my_emails).

frappe.listview_settings["Communication"] = frappe.listview_settings["Communication"] || {};

const CD_MAX_PULL_DAYS = 7;

const _cd_onload = frappe.listview_settings["Communication"].onload;
frappe.listview_settings["Communication"].onload = function (listview) {
	if (typeof _cd_onload === "function") _cd_onload(listview);

	listview.page.add_inner_button(__("Tarik Email"), () => {
		const today = frappe.datetime.get_today();
		const dialog = new frappe.ui.Dialog({
			title: __("Tarik Email"),
			fields: [
				{
					fieldname: "start_date",
					fieldtype: "Date",
					label: __("Dari Tanggal"),
					reqd: 1,
					default: frappe.datetime.add_days(today, -(CD_MAX_PULL_DAYS - 1)),
				},
				{
					fieldname: "end_date",
					fieldtype: "Date",
					label: __("Sampai Tanggal"),
					reqd: 1,
					default: today,
				},
				{
					fieldtype: "HTML",
					options: `<p class="text-muted small">${__(
						"Rentang maksimal {0} hari. Tarik per minggu agar tidak terlalu banyak email masuk sekaligus.",
						[CD_MAX_PULL_DAYS]
					)}</p>`,
				},
			],
			primary_action_label: __("Tarik"),
			primary_action(values) {
				// Same rule as the server, checked here only so a mistyped range costs a
				// dialog and not a round trip. mail_to_order._pull_window is the real gate.
				const span =
					frappe.datetime.get_day_diff(values.end_date, values.start_date) + 1;
				if (span < 1) {
					frappe.msgprint({
						title: __("Tarik Email"),
						message: __("Tanggal awal tidak boleh melewati tanggal akhir."),
						indicator: "orange",
					});
					return;
				}
				if (span > CD_MAX_PULL_DAYS) {
					frappe.msgprint({
						title: __("Tarik Email"),
						message: __("Rentang maksimal {0} hari, diminta {1} hari.", [
							CD_MAX_PULL_DAYS,
							span,
						]),
						indicator: "orange",
					});
					return;
				}
				dialog.hide();
				frappe.dom.freeze(__("Menarik email…"));
				frappe
					.call({
						method: "container_depot.container_depot.mail_to_order.pull_my_emails",
						args: { start_date: values.start_date, end_date: values.end_date },
					})
					.then(() => {
						frappe.dom.unfreeze();
						listview.refresh();
					})
					.catch(() => frappe.dom.unfreeze());
			},
		});
		dialog.show();
	});
};
