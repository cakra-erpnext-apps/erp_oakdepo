// Container Activity — unified action-history feed, newest first.
frappe.query_reports["Container Activity"] = {
	filters: [
		{ fieldname: "container", label: __("Container"), fieldtype: "Link", options: "Container" },
		{
			fieldname: "activity_type",
			label: __("Activity Type"),
			fieldtype: "Select",
			options: "\nBooking\nGate In\nInspection (EIR)\nCleaning\nRepair\nPeriodic Test\nOrder Bongkar\nOrder Muat\nRelease\nGate Out\nStatus Change",
		},
		{ fieldname: "principal", label: __("Principal"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "depot", label: __("Depot"), fieldtype: "Link", options: "Depot" },
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date" },
	],
};
