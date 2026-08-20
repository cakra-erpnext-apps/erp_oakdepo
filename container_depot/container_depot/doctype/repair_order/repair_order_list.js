// Repair Order list view.
//
// Kolom paling kiri (the "Subject") is always the doctype's `title_field`, and that is
// `container_no`: an M&R is looked up by the tank it is for, never by its own id. Frappe
// still appends the RO series name as an "ID" column on the far right, so nothing is lost.
//
// Filters above the list are trimmed to the five the depot actually uses:
//   Container No — comes free, Frappe always offers the title_field as a standard filter
//   Status / Principal (Owner) / Depot — in_standard_filter in repair_order.json
//   Order Created — the from→to range added below
// `hide_name_filter` drops Frappe's default "ID" (RO-series) box, which nobody searches by
// now that the container number is the subject.
frappe.listview_settings["Repair Order"] = {
	hide_name_filter: 1,

	// A Datetime field with in_standard_filter would only give an "=" box, which is useless
	// for a created-on search. Add a DateRange control instead: its value is a [from, to]
	// pair and its `between` condition is what get_standard_filters passes to the server,
	// which widens the two dates to 00:00:00 / 23:59:59 for the Datetime column.
	// Added in onload (not via custom_filter_configs) so it lands AFTER the doctype's own
	// standard filters rather than ahead of them.
	onload(listview) {
		const filter_area = listview.filter_area;
		listview.page.add_field(
			{
				fieldtype: "DateRange",
				fieldname: "order_created",
				label: __("Order Created"),
				condition: "between",
				onchange: () => filter_area.debounced_refresh_list_view(),
			},
			filter_area.standard_filters_wrapper
		);
	},
};
