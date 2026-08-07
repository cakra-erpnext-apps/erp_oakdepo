// Container Inventory — live per-tank monitoring list. Defaults to tanks
// physically in the depo; toggle "In Depo Only" off to include reserved /
// gated-out tanks.
frappe.query_reports["Container Inventory"] = {
	filters: [
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
			fieldname: "inventory_stage",
			label: __("Inventory Stage"),
			fieldtype: "Select",
			options: "\nPre-Arrival\nIn Depot\nReady\nDeparted",
		},
		{
			fieldname: "in_depo_only",
			label: __("In Depo Only"),
			fieldtype: "Check",
			default: 1,
		},
	],
};
