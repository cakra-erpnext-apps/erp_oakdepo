frappe.query_reports["Container Status Report"] = {
	"filters": [
		{
			"fieldname": "status",
			"label": __("Status"),
			"fieldtype": "Select",
			"options": "\nBooked\nIn_Depot\nAvailable\nGate_Out"
		},
		{
			"fieldname": "container_type",
			"label": __("Container Type"),
			"fieldtype": "Select",
			"options": "\nISO Tank\n20ft Dry\n40ft HC\n20ft Reefer\n40ft Reefer\nOpen Top\nFlat Rack"
		}
	]
};
