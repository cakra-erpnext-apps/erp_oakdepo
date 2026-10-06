frappe.query_reports["Gate Report"] = {
	filters: [
		...container_depot.report_kit.filters([
			["gate_in", "Gate In"],
			["gate_out", "Gate Out"],
		]),
		{ fieldname: "depot", label: __("Depot"), fieldtype: "Link", options: "Depot" },
		{ fieldname: "only_inside", label: __("Hanya yang masih di depo"), fieldtype: "Check", default: 0 },
	],

	onload: container_depot.report_kit.onload,
};
