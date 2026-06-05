frappe.query_reports["Container Status Report"] = {
	"filters": [
		{
			"fieldname": "status",
			"label": __("Status"),
			"fieldtype": "Select",
			"options": "\nAvailable\nGate_In\nInspecting\nEmpty_Clean\nNeeds_Cleaning\nPending_Cleaning\nCleaning_In_Progress\nCleaning_Completed\nPending_Survey\nSurvey_In_Progress\nAwaiting_MR_Approval\nRepair_In_Progress\nAwaiting_Recleaning_Approval\nRecleaning_In_Progress\nCleaning_Cert_Issued\nReady_For_Release\nReleased_Pending_Pickup\nGate_Out\nReady_For_Service"
		},
		{
			"fieldname": "container_type",
			"label": __("Container Type"),
			"fieldtype": "Select",
			"options": "\nISO Tank\n20ft Dry\n40ft HC\n20ft Reefer\n40ft Reefer\nOpen Top\nFlat Rack"
		},
		{
			"fieldname": "yard_zone",
			"label": __("Yard Zone"),
			"fieldtype": "Select",
			"options": "\nStorage_Yard_A\nStorage_Yard_B\nCleaning_Bay_C\nWorkshop_D\nSurvey_Lane_E\nGate_F\nPreClean_Buffer"
		}
	]
};
