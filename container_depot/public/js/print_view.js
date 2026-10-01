// Print view (/desk/print/Sales Invoice/...): the invoice fields the OAK Invoice print reads —
// Invoice Title, Print Currency, Print Rate, the optional Ref Cust. / No. Tank columns, Merge
// Same Lines — editable beside the preview, as in erp_cakra (user, 2026-10-01). Print Language
// is Frappe's own selector above them; Letter Head and ERPNext's item/tax print settings are
// gone (DepotSalesInvoice.get_print_settings), the OAK Invoice reads none of them.
//
// Each change is saved on the invoice (all are allow_on_submit) and redrawn at once:
// the preview renders the doc in memory, but PDF and Full Page render it from the database.
// Loaded through hooks page_js["print"], after Frappe's print page defines PrintView.
(function () {
	const PV = frappe.ui.form.PrintView;
	if (!PV || PV.prototype._depot_print_fields) return;
	PV.prototype._depot_print_fields = true;

	const FIELDS = ["depot_invoice_title", "depot_print_currency", "depot_print_rate", "depot_print_cust_ref", "depot_print_tank", "depot_print_merge"];

	const setup = PV.prototype.setup_additional_settings;
	PV.prototype.setup_additional_settings = function () {
		setup.apply(this, arguments);
		this.$depot_fields && this.$depot_fields.remove();
		const doc = this.frm.doc;
		// The OAK Invoice draws its own letterhead: Frappe's Letter Head pick does nothing there.
		this.letterhead_selector.closest(".frappe-control").toggle(doc.doctype !== "Sales Invoice");
		if (doc.doctype !== "Sales Invoice") return;
		this.$depot_fields = $('<div class="depot-print-fields"></div>').insertAfter(this.sidebar_dynamic_section);
		// A cancelled invoice takes no change, not even an allow_on_submit one.
		const editable = doc.docstatus < 2 && frappe.perm.has_perm(doc.doctype, 0, "write");
		const controls = {};
		const show_rate = () =>
			controls.depot_print_rate.$wrapper.toggle(!!doc.depot_print_currency && doc.depot_print_currency !== doc.currency);

		const save = async (fieldname) => {
			const value = controls[fieldname].get_value();
			if ((value || "") == (doc[fieldname] || "")) return;
			const values = { [fieldname]: value };
			// Print Rate follows the currency, like on the form: its kurs to IDR that day.
			if (fieldname === "depot_print_currency") {
				values.depot_print_rate =
					!value || value === doc.currency
						? 0
						: flt(await frappe.xcall("container_depot.invoicing.kurs_idr", { currency: value, date: doc.posting_date }));
				controls.depot_print_rate.set_input(values.depot_print_rate);
			}
			const r = await frappe.call({
				method: "frappe.client.set_value",
				args: { doctype: doc.doctype, name: doc.name, fieldname: values },
				freeze: true,
			});
			frappe.model.sync(r.message); // updates this.frm.doc in place
			show_rate();
			this.preview();
		};

		for (const fieldname of FIELDS) {
			const df = frappe.meta.get_docfield(doc.doctype, fieldname, doc.name);
			controls[fieldname] = frappe.ui.form.make_control({
				df: {
					fieldname,
					fieldtype: df.fieldtype,
					label: __(df.label),
					options: df.options,
					description: df.description,
					read_only: editable ? 0 : 1,
					change: () => save(fieldname),
				},
				parent: this.$depot_fields,
				render_input: 1,
			});
			controls[fieldname].set_input(doc[fieldname]);
		}
		show_rate();
	};
})();
