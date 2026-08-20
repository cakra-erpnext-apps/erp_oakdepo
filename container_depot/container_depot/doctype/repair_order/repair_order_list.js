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

	// status is not a column here, so the list query would not fetch it and get_indicator
	// would read undefined on every row.
	add_fields: ["status"],

	// Ten statuses, and without this map Frappe falls back to `guess_colour`, which paints
	// most of them the same grey and gives "Rejected" the same red as "Cancelled" but also
	// hands red to plain drafts. Colour convention, shared by every Container Depot list:
	//   grey   — Draft: belum diajukan ke owner, masih bisa diubah
	//   red    — Cancelled / Rejected: mati, tidak diteruskan
	//   blue   — Completed: the terminal "done" state (M&R selesai dan ditutup)
	//   others — the stages in between; Approved is green rather than blue because the
	//            owner's approval only STARTS the work, it does not finish the order.
	// Labels mirror frontend/src/utils/labels.js (repairStatusLabels) so Desk and the PWA
	// name the same status the same way.
	get_indicator(doc) {
		const map = {
			Draft: [__("Draf"), "gray", "status,=,Draft"],
			"Pending Approval": [__("Menunggu Persetujuan"), "orange", "status,=,Pending Approval"],
			Approved: [__("Disetujui"), "green", "status,=,Approved"],
			Rejected: [__("Ditolak"), "red", "status,=,Rejected"],
			"Revision Requested": [__("Minta Revisi"), "pink", "status,=,Revision Requested"],
			Pending: [__("Siap Dikerjakan"), "orange", "status,=,Pending"],
			"In Progress": [__("Dikerjakan"), "yellow", "status,=,In Progress"],
			"Pending Review": [__("Menunggu Review"), "purple", "status,=,Pending Review"],
			Completed: [__("Selesai"), "blue", "status,=,Completed"],
			Cancelled: [__("Dibatalkan"), "red", "status,=,Cancelled"],
		};
		return map[doc.status] || [__(doc.status || "-"), "gray", `status,=,${doc.status || ""}`];
	},

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
