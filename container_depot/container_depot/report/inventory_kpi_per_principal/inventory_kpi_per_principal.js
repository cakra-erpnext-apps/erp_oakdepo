// Inventory KPI per Principal — per-principal inventory & activity rollup,
// optionally scoped to a single depot (PRD v0.2 §6).
frappe.query_reports["Inventory KPI per Principal"] = {
	filters: [
		{
			fieldname: "depot",
			label: __("Depot"),
			fieldtype: "Link",
			options: "Depot",
		},
	],
};
