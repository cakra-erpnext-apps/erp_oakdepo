import frappe

def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	return columns, data

def get_columns():
	return [
		{
			"fieldname": "container_no",
			"label": "Container Number",
			"fieldtype": "Link",
			"options": "Container",
			"width": 150
		},
		{
			"fieldname": "container_type",
			"label": "Container Type",
			"fieldtype": "Data",
			"width": 120
		},
		{
			"fieldname": "size",
			"label": "Size",
			"fieldtype": "Data",
			"width": 80
		},
		{
			"fieldname": "status",
			"label": "Status",
			"fieldtype": "Data",
			"width": 120
		},
		{
			"fieldname": "principal",
			"label": "Principal",
			"fieldtype": "Data",
			"width": 150
		},
		{
			"fieldname": "cleaning_status",
			"label": "Cleaning Status",
			"fieldtype": "Data",
			"width": 120
		},
		{
			"fieldname": "repair_status",
			"label": "Repair Status",
			"fieldtype": "Data",
			"width": 120
		}
	]

def get_data(filters):
	query_filters = {}
	if filters:
		if filters.get("status"):
			query_filters["status"] = filters.get("status")
		if filters.get("container_type"):
			query_filters["container_type"] = filters.get("container_type")

	return frappe.get_all(
		"Container",
		filters=query_filters,
		fields=["container_no", "container_type", "size", "status", "principal", "cleaning_status", "repair_status"]
	)
