import frappe
from frappe.utils import now_datetime, add_days, today
import datetime
import random

def seed():
	print("🌱 Seeding rich dummy data for Container Depot module...")
	
	# 1. Cleanup existing mock data (so it's clean and repeatable)
	cleanup_data()

	# 1b. Reference masters the demo rows link to (idempotent; also seeded by
	# the v0_6 patches, but kept here so `seed()` works on a fresh test DB).
	_ensure_reference_masters()

	# 2. Seed Gasket Inventory
	print("Creating Gasket Inventory...")
	gaskets = [
		{"gasket_name": "3 inch PTFE Gasket", "type": "PTFE", "current_stock": 45, "reorder_point": 10, "unit_price": 15.00},
		{"gasket_name": "2 inch EPDM Gasket", "type": "EPDM", "current_stock": 8, "reorder_point": 12, "unit_price": 10.00}, # Low stock test
		{"gasket_name": "3 inch Viton Envelope Gasket", "type": "FKM (Viton)", "current_stock": 20, "reorder_point": 5, "unit_price": 35.00},
		{"gasket_name": "4 inch EPDM SuperSeal", "type": "EPDM", "current_stock": 15, "reorder_point": 5, "unit_price": 18.50}
	]
	
	for g in gaskets:
		doc = frappe.get_doc({
			"doctype": "Gasket Inventory",
			"gasket_name": g["gasket_name"],
			"type": g["type"],
			"current_stock": g["current_stock"],
			"reorder_point": g["reorder_point"],
			"unit_price": g["unit_price"]
		})
		doc.insert(ignore_permissions=True)
	
	# 3. Seed Yard Equipment & Maintenance
	print("Creating Yard Equipment...")
	equipment = [
		{"equipment_name": "Reachstacker RS-A1", "status": "Active", "notes": "Primary reachstacker for Zone A & B"},
		{"equipment_name": "Reachstacker RS-B2", "status": "Under Maintenance", "notes": "Hydraulic seal replacement in progress"},
		{"equipment_name": "Heavy Forklift FL-03", "status": "Active", "notes": "Assigned to Workshop & Cleaning Bay"}
	]
	
	eq_docs = []
	for eq in equipment:
		doc = frappe.get_doc({
			"doctype": "Equipment Maintenance",
			"equipment_name": eq["equipment_name"],
			"status": eq["status"],
			"maintenance_notes": eq["notes"],
			"last_service_date": add_days(today(), -15),
			"next_service_date": add_days(today(), 45)
		})
		doc.insert(ignore_permissions=True)
		eq_docs.append(doc)
		
	# 4. Seed Fuel Logs
	print("Creating Fuel Logs...")
	fuel_entries = [
		{"equipment": eq_docs[0].name, "liters": 120.5, "cost_per_liter": 1.25, "odometer": 12850.2},
		{"equipment": eq_docs[0].name, "liters": 95.0, "cost_per_liter": 1.28, "odometer": 13120.6},
		{"equipment": eq_docs[2].name, "liters": 45.2, "cost_per_liter": 1.24, "odometer": 5420.0}
	]
	for fe in fuel_entries:
		doc = frappe.get_doc({
			"doctype": "Fuel Log",
			"equipment": fe["equipment"],
			"fuel_date": add_days(today(), -random.randint(1, 10)),
			"liters": fe["liters"],
			"cost_per_liter": fe["cost_per_liter"],
			"odometer_reading": fe["odometer"]
		})
		doc.insert(ignore_permissions=True)

	# 5. Create active Container records
	print("Creating Containers...")
	containers = [
		{"container_no": "OAKU9812734", "container_type": "ISO Tank", "size": "20'", "status": "Gate_In", "principal": "Oak Depot Principal", "yard_zone": "PreClean_Buffer", "depot": "SUB"},
		{"container_no": "MSCU1122334", "container_type": "ISO Tank", "size": "20'", "status": "Available", "principal": "MSC Shipping", "yard_zone": "Storage_Yard_A", "depot": "SUB"},
		{"container_no": "TEXU4455667", "container_type": "20ft Dry", "size": "20'", "status": "Repair_In_Progress", "principal": "TexTainer", "yard_zone": "Workshop_D", "repair_status": "In_Progress", "depot": "SUB"},
		{"container_no": "GLOU8877665", "container_type": "ISO Tank", "size": "20'", "status": "Needs_Cleaning", "principal": "Global Tanks Co", "yard_zone": "Cleaning_Bay_C", "cleaning_status": "Pending", "depot": "KIM11"},
		{"container_no": "TRLU5566778", "container_type": "40ft HC", "size": "40'", "status": "Available", "principal": "Triton Containers", "yard_zone": "Storage_Yard_B", "depot": "KIM11"}
	]

	cont_docs = {}
	for c in containers:
		doc = frappe.get_doc({
			"doctype": "Container",
			"container_no": c["container_no"],
			"container_type": c["container_type"],
			"size": c["size"],
			"status": c["status"],
			"principal": c["principal"],
			"depot": c.get("depot"),
			"yard_zone": c["yard_zone"],
			"cleaning_status": c.get("cleaning_status", "Not_Required"),
			"repair_status": c.get("repair_status", "Not_Required")
		})
		doc.insert(ignore_permissions=True)
		cont_docs[c["container_no"]] = doc
		
	# 6. Create Gate Entries
	print("Creating Gate Entries...")
	gate_entries = [
		{
			"container_no": "OAKU9812734",
			"security_guard": "Administrator",
			"truck_plate": "B-1234-OAK",
			"driver_name": "Robert Smith",
			"status": "Gate_In_Completed"
		},
		{
			"container_no": "TEXU4455667",
			"security_guard": "Administrator",
			"truck_plate": "B-5566-TEX",
			"driver_name": "Daniel Carter",
			"status": "Gate_In_Completed"
		}
	]
	for ge in gate_entries:
		doc = frappe.get_doc({
			"doctype": "Gate Entry",
			"container_no": ge["container_no"],
			"security_guard": ge["security_guard"],
			"truck_plate": ge["truck_plate"],
			"driver_name": ge["driver_name"],
			"gate_in_timestamp": add_days(now_datetime(), -1),
			"status": ge["status"]
		})
		doc.insert(ignore_permissions=True)
		
	# 7. Create Inspections
	print("Creating EIR Inspections...")
	inspections = [
		{
			"container": cont_docs["OAKU9812734"].name,
			"container_no": "OAKU9812734",
			"inspection_type": "EIR-In",
			"inspector": "Administrator",
			"has_damage": 1,
			"damages": [{"component": "Manlid Gasket", "code": "11", "severity": "Moderate", "description": "Blown gasket on outlet valve"}]
		},
		{
			"container": cont_docs["TEXU4455667"].name,
			"container_no": "TEXU4455667",
			"inspection_type": "EIR-In",
			"inspector": "Administrator",
			"has_damage": 1,
			"damages": [{"component": "Frame", "code": "11", "severity": "Moderate", "description": "Dent on left side frame"}]
		}
	]
	
	insp_docs = {}
	for insp in inspections:
		doc = frappe.get_doc({
			"doctype": "Inspection",
			"container": insp["container"],
			"container_no": insp["container_no"],
			"inspection_type": insp["inspection_type"],
			"inspector": insp["inspector"],
			"status": "Completed",
			"has_damage": insp["has_damage"],
			"damage_log": [
				{
					"component": d["component"],
					"damage_type": d["code"],
					"severity": d["severity"],
					"damage_description": d["description"]
				}
				for d in insp["damages"]
			]
		})
		doc.insert(ignore_permissions=True)
		insp_docs[insp["container_no"]] = doc

	# 8. Create Repair Orders
	print("Creating Repair Orders...")
	repair_orders = [
		{
			"container": cont_docs["TEXU4455667"].name,
			"inspection": insp_docs["TEXU4455667"].name,
			"status": "In Progress",
			"billing_status": "Principal Billed",
			"items": [
				{
					"part_description": "Frame structural welding",
					"quantity": 1,
					"unit_price": 0.00,
					"labor_hours": 4,
					"labor_rate": 60.00
				}
			]
		},
		{
			"container": cont_docs["OAKU9812734"].name,
			"inspection": insp_docs["OAKU9812734"].name,
			"status": "Draft",
			"billing_status": "Unbilled",
			"items": [
				{
					"part_description": "Replacement 3 inch PTFE Gasket",
					"quantity": 1,
					"unit_price": 15.00,
					"labor_hours": 1.5,
					"labor_rate": 50.00
				}
			]
		}
	]
	
	for ro in repair_orders:
		doc = frappe.get_doc({
			"doctype": "Repair Order",
			"container": ro["container"],
			"inspection": ro["inspection"],
			"status": ro["status"],
			"billing_status": ro["billing_status"],
			"estimation_items": [
				{
					"part_description": item["part_description"],
					"quantity": item["quantity"],
					"unit_price": item["unit_price"],
					"labor_hours": item["labor_hours"],
					"labor_rate": item["labor_rate"]
				}
				for item in ro["items"]
			]
		})
		doc.insert(ignore_permissions=True)

	# 10. Seed Container Movements
	print("Creating Container Movements...")
	movements = [
		{"container": cont_docs["OAKU9812734"].name, "to_zone": "Storage_Yard_B", "to_row": "Row 04", "to_bay": "Bay B", "to_tier": 3},
		{"container": cont_docs["MSCU1122334"].name, "to_zone": "Storage_Yard_A", "to_row": "Row 02", "to_bay": "Bay A", "to_tier": 2}
	]
	for m in movements:
		doc = frappe.get_doc({
			"doctype": "Container Movement",
			"container": m["container"],
			"to_zone": m["to_zone"],
			"to_row": m["to_row"],
			"to_bay": m["to_bay"],
			"to_tier": m["to_tier"]
		})
		doc.insert(ignore_permissions=True)

	# 11. Seed Cleaning Certificates
	print("Creating Cleaning Certificates...")
	certs = [
		{"container": cont_docs["OAKU9812734"].name, "cleaning_method": "Chemical", "remarks": "Approved after inspections"},
		{"container": cont_docs["MSCU1122334"].name, "cleaning_method": "Steam Wash", "remarks": "Regular periodic cleanup"}
	]
	for c in certs:
		doc = frappe.get_doc({
			"doctype": "Cleaning Certificate",
			"container": c["container"],
			"cleaning_method": c["cleaning_method"],
			"remarks": c["remarks"]
		})
		doc.insert(ignore_permissions=True)
		doc.submit()

	frappe.db.commit()
	print("🎉 Seeding completed successfully! Check the ERPNext UI.")

def _ensure_reference_masters():
	"""Create the v0.2 reference masters the demo rows link to, if missing."""
	depots = [("SUB", "Surabaya", "Surabaya"), ("KIM11", "OAK Medan (KIM 11)", "Medan")]
	for code, name, city in depots:
		if not frappe.db.exists("Depot", code):
			frappe.get_doc({
				"doctype": "Depot",
				"depot_code": code,
				"depot_name": name,
				"city": city,
				"is_active": 1,
			}).insert(ignore_permissions=True)

	# Official damage code referenced by the seeded EIR damage logs.
	if not frappe.db.exists("EIR Damage Code", "11"):
		frappe.get_doc({
			"doctype": "EIR Damage Code",
			"code": "11",
			"category": "Damage",
			"description": "Dented",
			"is_active": 1,
		}).insert(ignore_permissions=True)


def cleanup_data():
	print("Cleaning up previous data...")
	frappe.db.delete("Gate Entry", {"container_no": ["in", ["OAKU9812734", "MSCU1122334", "TEXU4455667", "GLOU8877665", "TRLU5566778"]]})
	frappe.db.delete("Inspection Photo", {"parent": ["in", frappe.db.get_values("Inspection", {"container_no": ["in", ["OAKU9812734", "MSCU1122334", "TEXU4455667", "GLOU8877665", "TRLU5566778"]]}, "name")]})
	frappe.db.delete("Damage Entry", {"parent": ["in", frappe.db.get_values("Inspection", {"container_no": ["in", ["OAKU9812734", "MSCU1122334", "TEXU4455667", "GLOU8877665", "TRLU5566778"]]}, "name")]})
	frappe.db.delete("Inspection", {"container_no": ["in", ["OAKU9812734", "MSCU1122334", "TEXU4455667", "GLOU8877665", "TRLU5566778"]]})
	frappe.db.delete("Repair Order", {"container": ["in", ["OAKU9812734", "MSCU1122334", "TEXU4455667", "GLOU8877665", "TRLU5566778"]]})
	
	# Delete comments on Gate Entry and Cleaning Certificate
	gate_entry_names = frappe.db.get_values("Gate Entry", {"container_no": ["in", ["OAKU9812734", "MSCU1122334", "TEXU4455667", "GLOU8877665", "TRLU5566778"]]}, "name")
	if gate_entry_names:
		frappe.db.delete("Comment", {"reference_doctype": "Gate Entry", "reference_name": ["in", gate_entry_names]})
	cert_names = frappe.db.get_values("Cleaning Certificate", {"container": ["in", ["OAKU9812734", "MSCU1122334", "TEXU4455667", "GLOU8877665", "TRLU5566778"]]}, "name")
	if cert_names:
		frappe.db.delete("Comment", {"reference_doctype": "Cleaning Certificate", "reference_name": ["in", cert_names]})
	
	frappe.db.delete("Container Movement", {"container": ["in", ["OAKU9812734", "MSCU1122334", "TEXU4455667", "GLOU8877665", "TRLU5566778"]]})
	frappe.db.delete("Cleaning Certificate", {"container": ["in", ["OAKU9812734", "MSCU1122334", "TEXU4455667", "GLOU8877665", "TRLU5566778"]]})
	frappe.db.delete("Container", {"container_no": ["in", ["OAKU9812734", "MSCU1122334", "TEXU4455667", "GLOU8877665", "TRLU5566778"]]})
	frappe.db.delete("Fuel Log", {"cost_per_liter": ["in", [1.25, 1.28, 1.24]]})
	frappe.db.delete("Equipment Maintenance", {"equipment_name": ["in", ["Reachstacker RS-A1", "Reachstacker RS-B2", "Heavy Forklift FL-03"]]})
	frappe.db.delete("Gasket Inventory", {"gasket_name": ["in", ["3 inch PTFE Gasket", "2 inch EPDM Gasket", "3 inch Viton Envelope Gasket", "4 inch EPDM SuperSeal"]]})
	
	# Delete items and material requests generated by gasket low stock test during seeding
	mr_names = frappe.db.get_values("Material Request Item", {"item_code": ["in", ["GASKET-2-INCH-EPDM-GASKET", "GASKET-3-INCH-PTFE-GASKET"]]}, "parent")
	if mr_names:
		frappe.db.delete("Material Request Item", {"parent": ["in", mr_names]})
		frappe.db.delete("Material Request", {"name": ["in", mr_names]})
	frappe.db.delete("Item", {"item_code": ["in", ["GASKET-2-INCH-EPDM-GASKET", "GASKET-3-INCH-PTFE-GASKET"]]})
	
	frappe.db.commit()
