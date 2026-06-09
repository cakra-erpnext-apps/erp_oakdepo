import frappe
import json
import base64
from container_depot.api import (
	validate_qr,
	register_gate_entry,
	get_pending_lifts,
	update_container_location,
	upload_inspection_evidence
)
from container_depot.tests._booking_helpers import make_booking_code

def run_tests():
	print("🚀 Starting Container Depot Integration Tests...")

	# Clear any previous test data to keep it clean
	cleanup_test_data()

	try:
		# 1. Setup Test Data
		print("\n--- 1. Setting up test Container and Booking Code ---")
		container_no = "TSTU1234567"

		# Seed Customer used as Container.principal (now Link Customer).
		principal_customer = ensure_test_customer("Test Principal")
		print(f"✓ Test Customer: {principal_customer}")

		# Create test container
		container = frappe.get_doc({
			"doctype": "Container",
			"container_no": container_no,
			"container_type": "ISO Tank",
			"status": "Available",
			"principal": principal_customer
		})
		container.insert(ignore_permissions=True)
		print(f"✓ Created test Container: {container.name}")

		# Create an Active Booking Code for this container.
		code = make_booking_code(
			customer=principal_customer,
			container_no=container_no,
			direction="Tank In",
		)
		print(f"✓ Created test Booking Code: {code.name}")

		# 2. Test validate_qr API
		print("\n--- 2. Testing validate_qr API ---")
		qr_res = validate_qr(code.code)
		print(f"validate_qr result: {json.dumps(qr_res, indent=2)}")
		assert qr_res.get("valid") is True, "validate_qr failed"
		assert qr_res.get("booking_code") == code.name, "Booking Code mismatch"
		print("✓ validate_qr API verified successfully.")

		# 3. Test register_gate_entry API
		print("\n--- 3. Testing register_gate_entry API ---")
		entry_res = register_gate_entry(
			booking_code=code.code,
			container_no=container_no,
			security_guard="Administrator",
			truck_plate="B-1234-XYZ",
			driver_name="Test Driver"
		)
		print(f"register_gate_entry result: {json.dumps(entry_res, indent=2)}")
		assert entry_res.get("success") is True, f"register_gate_entry failed: {entry_res.get('error')}"
		gate_entry_id = entry_res.get("gate_entry_id")
		
		# Verify Gate Entry record was created and Container status updated
		gate_entry_doc = frappe.get_doc("Gate Entry", {"gate_entry_id": gate_entry_id})
		print(f"✓ Gate Entry doc name: {gate_entry_doc.name}")
		assert gate_entry_doc.status == "Gate_In_Completed", "Gate Entry status not updated on submit"
		
		# Verify CODECO Comment was created
		comments = frappe.get_all("Comment", {
			"reference_doctype": "Gate Entry",
			"reference_name": gate_entry_doc.name,
			"comment_type": "Comment"
		}, ["content"])
		assert len(comments) > 0, "No comment was created on Gate Entry submission"
		assert "Generated UN/EDIFACT CODECO EDI Message" in comments[0].content, "CODECO header missing from comment"
		assert "UNB+UNOA" in comments[0].content, "UNB segment missing from CODECO message"
		print("✓ Gate Entry submission CODECO EDI Comment generated successfully.")
		
		container.reload()
		print(f"Container status after Gate-In: {container.status}")
		assert container.status == "Gate_In", "Container status should be Gate_In"
		print("✓ register_gate_entry API verified successfully.")

		# 4. Test get_pending_lifts API
		print("\n--- 4. Testing get_pending_lifts API ---")
		lifts_res = get_pending_lifts(booking_code=code.code)
		print(f"get_pending_lifts result: {json.dumps(lifts_res, indent=2)}")
		assert lifts_res.get("success") is True, "get_pending_lifts failed"
		assert len(lifts_res.get("containers")) > 0, "No pending lifts returned"
		print("✓ get_pending_lifts API verified successfully.")

		# 5. Test update_container_location API
		print("\n--- 5. Testing update_container_location API ---")
		loc_res = update_container_location(
			container_no=container_no,
			yard_zone="Cleaning_Bay_C",
			lifted_by="Administrator"
		)
		print(f"update_container_location result: {json.dumps(loc_res, indent=2)}")
		assert loc_res.get("success") is True, "update_container_location failed"
		
		container.reload()
		assert container.yard_zone == "Cleaning_Bay_C", "Container yard zone not updated"
		assert container.current_location == "Cleaning_Bay_C", "Container location not updated"
		print("✓ update_container_location API verified successfully.")

		# 6. Test upload_inspection_evidence API
		print("\n--- 6. Testing upload_inspection_evidence API ---")
		mock_photo = base64.b64encode(b"dummy image data").decode("utf-8")
		photos = [
			{"view": "Front", "data": mock_photo},
			{"view": "Back", "data": mock_photo},
			{"view": "Left", "data": mock_photo},
			{"view": "Right", "data": mock_photo}
		]
		
		photo_res = upload_inspection_evidence(
			container_no=container_no,
			photos=photos,
			inspection_type="EIR-In",
			inspector="Administrator"
		)
		print(f"upload_inspection_evidence result: {json.dumps(photo_res, indent=2)}")
		assert photo_res.get("success") is True, f"upload_inspection_evidence failed: {photo_res.get('error')}"
		inspection_id = photo_res.get("inspection_id")
		
		inspection_doc = frappe.get_doc("Inspection", {"inspection_id": inspection_id})
		print(f"✓ Inspection doc status: {inspection_doc.status}")
		print("✓ upload_inspection_evidence API verified successfully.")

		# 7. Test Repair Order lifecycle (New DocType)
		print("\n--- 7. Testing Repair Order lifecycle ---")
		# Create a Repair Order in Draft status
		repair_order = frappe.get_doc({
			"doctype": "Repair Order",
			"container": container.name,
			"inspection": inspection_doc.name,
			"status": "Draft",
			"technician": frappe.db.get_value("Employee", {}, "name") or None,
			"estimation_items": [
				{
					"part_description": "Replace Gasket",
					"quantity": 1,
					"unit_price": 150.00,
					"labor_hours": 2,
					"labor_rate": 50.00
				},
				{
					"part_description": "Welding structural frame",
					"quantity": 1,
					"unit_price": 0.00,
					"labor_hours": 3,
					"labor_rate": 60.00
				}
			]
		})
		repair_order.insert(ignore_permissions=True)
		print(f"✓ Created Repair Order: {repair_order.repair_order_id}")
		
		# Verify totals calculations on before_save
		assert repair_order.estimation_items[0].total_price == 150.00, "Item 1 part cost calculation failed"
		assert repair_order.estimation_items[0].labor_total == 100.00, "Item 1 labor cost calculation failed"
		assert repair_order.estimation_items[1].total_price == 0.00, "Item 2 part cost calculation failed"
		assert repair_order.estimation_items[1].labor_total == 180.00, "Item 2 labor cost calculation failed"
		assert repair_order.total_cost == 430.00, f"Repair Order total cost calculation failed: expected 430, got {repair_order.total_cost}"
		assert repair_order.principal == principal_customer, "Principal not auto-fetched"
		
		container.reload()
		assert container.repair_status == "Pending_Estimate", "Container repair status should be Pending_Estimate for Draft RO"
		print("✓ Repair Order calculations and Draft state verified.")

		# Move Repair Order to In Progress
		print("Updating Repair Order to In Progress...")
		repair_order.status = "In Progress"
		repair_order.save(ignore_permissions=True)
		
		container.reload()
		assert container.repair_status == "In_Progress", "Container repair status should be In_Progress"
		assert container.status == "Repair_In_Progress", "Container status should be Repair_In_Progress"
		print("✓ Repair Order In Progress state verified.")

		# Complete the Repair Order
		print("Updating Repair Order to Completed...")
		repair_order.status = "Completed"
		repair_order.save(ignore_permissions=True)
		
		container.reload()
		assert container.repair_status == "Completed", "Container repair status should be Completed"
		assert container.status == "Ready_For_Service", "Container status should be Ready_For_Service"
		print("✓ Repair Order Completion state verified.")

		# 8. Test Fuel Log calculations (New DocType)
		print("\n--- 8. Testing Fuel Log calculations ---")
		# Create Equipment Maintenance record
		eq = frappe.get_doc({
			"doctype": "Equipment Maintenance",
			"equipment_name": "Reachstacker #1",
			"status": "Active"
		})
		eq.insert(ignore_permissions=True)
		print(f"✓ Created Equipment Maintenance: {eq.name}")

		fuel_log = frappe.get_doc({
			"doctype": "Fuel Log",
			"equipment": eq.name,
			"fuel_date": frappe.utils.today(),
			"liters": 45.5,
			"cost_per_liter": 1.20,
			"odometer_reading": 12500
		})
		fuel_log.insert(ignore_permissions=True)
		print(f"✓ Created Fuel Log: {fuel_log.name}")
		assert fuel_log.total_cost == 54.6, f"Fuel Log total cost calculation failed: expected 54.6, got {fuel_log.total_cost}"
		print("✓ Fuel Log calculations verified successfully.")

		# 9. Test Container Movement updates Container location & coordinates
		print("\n--- 9. Testing Container Movement ---")
		movement = frappe.get_doc({
			"doctype": "Container Movement",
			"container": container.name,
			"to_zone": "Storage_Yard_B",
			"to_row": "Row 04",
			"to_bay": "Bay B",
			"to_tier": 3
		})
		movement.insert(ignore_permissions=True)
		print(f"✓ Created Container Movement: {movement.name}")
		
		# Verify container was updated
		container.reload()
		assert container.yard_zone == "Storage_Yard_B", f"Expected Storage_Yard_B, got {container.yard_zone}"
		assert container.current_location == "Storage_Yard_B", f"Expected Storage_Yard_B, got {container.current_location}"
		assert container.row == "Row 04", f"Expected Row 04, got {container.row}"
		assert container.bay == "Bay B", f"Expected Bay B, got {container.bay}"
		assert container.tier == 3, f"Expected 3, got {container.tier}"
		print("✓ Container Movement updates verified successfully.")

		# 10. Test Cleaning Certificate workflow and container state change
		print("\n--- 10. Testing Cleaning Certificate ---")
		cert = frappe.get_doc({
			"doctype": "Cleaning Certificate",
			"container": container.name,
			"cleaning_method": "Chemical",
			"remarks": "Cleaned thoroughly"
		})
		cert.insert(ignore_permissions=True)
		print(f"✓ Created Cleaning Certificate Draft: {cert.name}")
		
		# Submit the certificate
		cert.submit()
		print(f"✓ Submitted Cleaning Certificate: {cert.name}")
		
		# Verify container was updated
		container.reload()
		assert container.certification_status == "Completed", f"Expected Completed, got {container.certification_status}"
		print("✓ Cleaning Certificate workflow verified successfully.")

		# 11. Test Gasket Inventory stock level reorder point trigger
		print("\n--- 11. Testing Gasket Inventory reorder point ---")
		gasket = frappe.get_doc({
			"doctype": "Gasket Inventory",
			"gasket_name": "Test Gasket",
			"gasket_type": "Viton",
			"current_stock": 5,
			"reorder_point": 10,
			"cost_price": 12.50,
			"unit_price": 20.00
		})
		gasket.insert(ignore_permissions=True)
		print(f"✓ Created Gasket Inventory: {gasket.name}")
		
		# Verify that ToDo was created
		todo_exists = frappe.db.exists("ToDo", {
			"reference_type": "Gasket Inventory",
			"reference_name": gasket.name,
			"status": "Open"
		})
		assert todo_exists, "Low stock ToDo alert not created"
		
		# Verify that Item was created
		item_code = "GASKET-TEST-GASKET"
		assert frappe.db.exists("Item", item_code), f"Item {item_code} was not created"
		
		# Verify that Material Request was created
		mr_item_exists = frappe.db.exists("Material Request Item", {"item_code": item_code})
		assert mr_item_exists, f"Material Request for item {item_code} was not created"
		print("✓ Gasket Inventory reorder point logic verified successfully.")

		print("\n🎉 ALL TESTS PASSED SUCCESSFULLY! 🎉")

	except Exception as e:
		print(f"\n❌ TEST FAILED: {str(e)}")
		import traceback
		traceback.print_exc()
	finally:
		# Cleanup
		cleanup_test_data()

def ensure_test_customer(name: str) -> str:
	"""Idempotently create (or fetch) a Customer used by the smoke test.

	Returns the Customer's ``name`` which is what Link fields store.
	"""
	if frappe.db.exists("Customer", name):
		return name
	hit = frappe.db.get_value("Customer", {"customer_name": name}, "name")
	if hit:
		return hit
	doc = frappe.get_doc({
		"doctype": "Customer",
		"customer_name": name,
		"customer_type": "Company",
		"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "All Customer Groups",
		"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name") or "All Territories",
	}).insert(ignore_permissions=True)
	return doc.name


def ensure_test_branch(name: str = "Test Branch") -> str:
	"""Idempotently create (or fetch) a Branch for tests. Returns its name (Depot.branch
	is mandatory, so depot fixtures need a real Branch to point at)."""
	if frappe.db.exists("Branch", name):
		return name
	frappe.get_doc({"doctype": "Branch", "branch": name}).insert(ignore_permissions=True)
	return name


def cleanup_test_data():
	print("\n--- Cleaning up test records ---")
	
	# Delete Comments for Gate Entry and Cleaning Certificate
	gate_entry_names = frappe.db.get_values("Gate Entry", {"container_no": "TSTU1234567"}, "name")
	if gate_entry_names:
		frappe.db.delete("Comment", {"reference_doctype": "Gate Entry", "reference_name": ["in", gate_entry_names]})
	
	# Delete Gate Entry
	frappe.db.delete("Gate Entry", {"container_no": "TSTU1234567"})
	
	# Delete Inspection Photo and Inspection
	inspection_names = frappe.db.get_values("Inspection", {"container_no": "TSTU1234567"}, "name")
	if inspection_names:
		frappe.db.delete("Inspection Photo", {"parent": ["in", inspection_names]})
	frappe.db.delete("Inspection", {"container_no": "TSTU1234567"})
	
	# Delete Repair Order
	frappe.db.delete("Repair Order", {"principal": "Test Principal"})
	
	# Delete Container Movement
	frappe.db.delete("Container Movement", {"container": "TSTU1234567"})
	
	# Delete Cleaning Certificate comments and documents
	cert_names = frappe.db.get_values("Cleaning Certificate", {"container": "TSTU1234567"}, "name")
	if cert_names:
		frappe.db.delete("Comment", {"reference_doctype": "Cleaning Certificate", "reference_name": ["in", cert_names]})
	frappe.db.delete("Cleaning Certificate", {"container": "TSTU1234567"})
	
	# Delete Container
	frappe.db.delete("Container", {"container_no": "TSTU1234567"})

	# Delete Booking Codes + their parent Bookings/Contracts for the test customer
	test_bookings = frappe.db.get_values("Container Booking", {"customer": "Test Principal"}, "name", pluck=True)
	if test_bookings:
		frappe.db.delete("Booking Code", {"booking": ["in", test_bookings]})
		frappe.db.delete("Container Booking Item", {"parent": ["in", test_bookings]})
		frappe.db.delete("Container Booking", {"name": ["in", test_bookings]})
	frappe.db.delete("Depot Contract", {"customer": "Test Principal"})

	# Delete Fuel Log & Equipment
	frappe.db.delete("Fuel Log", {"liters": 45.5, "cost_per_liter": 1.20})
	frappe.db.delete("Equipment Maintenance", {"equipment_name": "Reachstacker #1"})
	
	# Delete Gasket Inventory and material request / item
	frappe.db.delete("Gasket Inventory", {"gasket_name": "Test Gasket"})
	frappe.db.delete("ToDo", {"reference_type": "Gasket Inventory"})
	mr_names = frappe.db.get_values("Material Request Item", {"item_code": "GASKET-TEST-GASKET"}, "parent")
	if mr_names:
		frappe.db.delete("Material Request Item", {"parent": ["in", mr_names]})
		frappe.db.delete("Material Request", {"name": ["in", mr_names]})
	frappe.db.delete("Item", {"item_code": "GASKET-TEST-GASKET"})
	
	frappe.db.commit()
	print("✓ Cleanup completed.")
