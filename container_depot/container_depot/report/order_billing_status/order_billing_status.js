// Filters for the "Order Billing Status" report. To find TOP orders that still
// need to be billed, set Payment Type = TOP + Invoice Status = Not Invoiced.
//
// This report is a MONITOR, not a billing engine — it raises nothing by itself. Ticking
// rows and pressing "Buat Invoice" hands the chosen orders to the invoice, which is where
// every receivable in this app is actually built (consolidated_billing.fill_invoice*).
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
			options: [
				"",
				"Container Booking",
				"Cleaning Order",
				"Repair Order",
			].join("\n"),
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

	// Tick rows to bill them. Selection beats a filter sweep here because the operator bills
	// exactly what is on screen — no order they never saw can ride along.
	get_datatable_options(options) {
		return Object.assign(options, { checkboxColumn: true });
	},

	onload(report) {
		// Storage has no order document — it is derived from Container Movement — so it can
		// never appear as a row here. Say so, or an operator ticking every row would believe
		// storage was included and quietly under-bill.
		report.page.add_inner_message(
			__(
				"Storage tidak muncul di sini (bukan dokumen order). Tagih storage lewat section <b>Tagihan Depot</b> di Sales Invoice."
			)
		);

		report.page.add_inner_button(__("Buat Invoice"), () => {
			const rows = report.datatable?.rowmanager?.getCheckedRows?.() || [];
			if (!rows.length) {
				frappe.msgprint({
					title: __("Belum ada yang dipilih"),
					message: __("Centang dulu order yang mau ditagih."),
					indicator: "orange",
				});
				return;
			}

			const picked = rows.map((i) => report.data[i]).filter(Boolean);
			// One invoice, one bill-to party. Mixing customers would produce a receivable
			// nobody owes, so refuse rather than guess which one was meant.
			const customers = [...new Set(picked.map((r) => r.customer).filter(Boolean))];
			if (customers.length !== 1) {
				frappe.msgprint({
					title: __("Customer harus sama"),
					message: __(
						"Baris yang dipilih milik {0} customer berbeda ({1}). Satu invoice hanya untuk satu customer.",
						[customers.length, frappe.utils.escape_html(customers.join(", "))]
					),
					indicator: "red",
				});
				return;
			}

			// Already-invoiced rows have nothing left to bill; billing them again would either
			// double-charge or throw. Drop them here so the operator can tick a whole column.
			const billable = picked.filter((r) => r.invoice_status === "Not Invoiced");
			const skipped = picked.length - billable.length;
			if (!billable.length) {
				frappe.msgprint({
					title: __("Semua sudah ditagih"),
					message: __("Order yang dipilih sudah punya invoice."),
					indicator: "blue",
				});
				return;
			}

			const orders = billable.map((r) => ({ doctype: r.order_type, name: r.order }));
			frappe.confirm(
				__("Buat invoice untuk <b>{0}</b> dari {1} order terpilih{2}?", [
					frappe.utils.escape_html(customers[0]),
					orders.length,
					skipped ? __(" ({0} sudah ditagih, dilewati)", [skipped]) : "",
				]),
				() => {
					frappe.call({
						method: "container_depot.consolidated_billing.fill_invoice_from_orders",
						args: { customer: customers[0], orders: JSON.stringify(orders) },
						freeze: true,
						freeze_message: __("Membuat invoice…"),
						callback: (r) => {
							const out = r.message || {};
							const invoices = out.invoices || [];
							if (!invoices.length) {
								frappe.msgprint({ title: __("Tidak ada yang ditagih"), indicator: "blue" });
								return;
							}
							frappe.show_alert({
								message: __("{0} invoice dibuat · Nomor Tagihan {1}", [
									invoices.length,
									out.group,
								]),
								indicator: "green",
							});
							frappe.set_route("Form", "Sales Invoice", invoices[0]);
						},
					});
				}
			);
		});
	},
};
