// Filters mirror the report's own arguments — see container_status_report.py.
// Status/Type stay Select (the Container Selects), Principal/Depot are Links so the
// list comes from the data rather than a hand-kept copy of it.
frappe.query_reports["Container Status Report"] = {
	filters: [
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "\nBooked\nIn_Depot\nAvailable\nGate_Out",
		},
		{
			fieldname: "container_type",
			label: __("Container Type"),
			fieldtype: "Select",
			options: "\nISO Tank\n20ft Dry\n40ft HC\n20ft Reefer\n40ft Reefer\nOpen Top\nFlat Rack",
		},
		{
			fieldname: "principal",
			label: __("Principal"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "depot",
			label: __("Depot"),
			fieldtype: "Link",
			options: "Depot",
		},
		{
			fieldname: "with_open_work",
			label: __("Hanya yang ada order terbuka"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "include_retired",
			label: __("Termasuk tank non-aktif"),
			fieldtype: "Check",
			default: 0,
		},
	],

	// A tank nobody is waiting on should not read the same as one with work stuck on it.
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "readiness" && data && data.readiness) {
			const colour = data.readiness === "Siap" ? "green" : "orange";
			value = `<span class="indicator-pill ${colour}">${data.readiness}</span>`;
		}
		return value;
	},
};
