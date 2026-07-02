// Filters for the "Order Billing Status" report. To find TOP orders that still
// need to be billed, set Payment Type = TOP + Invoice Status = Not Invoiced.
frappe.query_reports["Order Billing Status"] = {
	filters: [
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "order_type",
			label: __("Order Type"),
			fieldtype: "Select",
			options: ["", "Container Booking", "Cleaning Order", "Repair Order", "Survey Order"].join("\n"),
		},
		{
			fieldname: "payment_type",
			label: __("Payment Type"),
			fieldtype: "Select",
			options: "\nCash\nTOP",
		},
		{
			fieldname: "invoice_status",
			label: __("Invoice Status"),
			fieldtype: "Select",
			options: "\nNot Invoiced\nDraft\nUnpaid\nPartly Paid\nOverdue\nPaid\nBilled",
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
		},
	],

	// Phase 2: sweep a customer's unbilled TOP orders into ONE draft Sales Invoice.
	// Reuses the whitelisted (role-guarded) consolidated_billing.bill_customer engine.
	onload(report) {
		report.page.add_inner_button(__("Generate Invoice"), () => {
			const customer = report.get_filter_value("customer");
			if (!customer) {
				frappe.msgprint({
					title: __("Pilih Customer"),
					message: __("Set filter <b>Customer</b> dulu — invoice penagihan dibuat per customer."),
					indicator: "orange",
				});
				return;
			}
			const from_date = report.get_filter_value("from_date");
			const to_date = report.get_filter_value("to_date");
			frappe.confirm(
				__(
					"Generate SATU draft Sales Invoice untuk <b>{0}</b> dari semua order TOP yang belum ditagih{1}?",
					[
						frappe.utils.escape_html(customer),
						from_date || to_date
							? __(" ({0} → {1})", [from_date || "…", to_date || __("today")])
							: "",
					]
				),
				() => {
					frappe.call({
						method: "container_depot.consolidated_billing.bill_customer",
						args: { customer, from_date, to_date },
						freeze: true,
						freeze_message: __("Generating invoice…"),
						callback: (r) => {
							// One draft invoice per currency, so the result is a list.
							const sis = r.message || [];
							if (!sis.length) {
								frappe.msgprint({
									title: __("Tidak ada yang ditagih"),
									message: __(
										"Tidak ada order TOP yang belum ditagih untuk {0} di rentang ini.",
										[frappe.utils.escape_html(customer)]
									),
									indicator: "blue",
								});
								return;
							}
							const links = sis
								.map((si) => `<a href='/app/sales-invoice/${encodeURIComponent(si)}'>${frappe.utils.escape_html(si)}</a>`)
								.join(", ");
							frappe.msgprint({
								title: __("Draft Sales Invoice dibuat"),
								message: __(
									"{0} draft Sales Invoice dibuat (satu per mata uang): {1} — review lalu submit.",
									[sis.length, links]
								),
								indicator: "green",
							});
							report.refresh();
						},
					});
				}
			);
		});
	},
};
