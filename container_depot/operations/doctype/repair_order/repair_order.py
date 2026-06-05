import frappe
from frappe.model.document import Document
import datetime
import hashlib

class RepairOrder(Document):
	def before_insert(self):
		"""Generate unique repair order ID"""
		self.repair_order_id = self.generate_repair_order_id()

	def generate_repair_order_id(self):
		"""Generate unique repair order ID"""
		timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
		unique = hashlib.md5(f"{timestamp}{frappe.generate_hash()[:10]}".encode()).hexdigest()[:8].upper()
		return f"RO-{unique}"

	def before_save(self):
		"""Auto-fetch principal, calculate costs, and update container status"""
		self.fetch_principal_from_container()
		self.calculate_totals()
		self.update_container_status()

	def fetch_principal_from_container(self):
		"""Fetch principal from Container master record"""
		if self.container:
			principal = frappe.db.get_value("Container", self.container, "principal")
			if principal:
				self.principal = principal

	def calculate_totals(self):
		"""Calculate line totals and overall total cost"""
		total_cost = 0.0
		for item in self.get("estimation_items") or []:
			quantity = float(item.quantity or 0.0)
			unit_price = float(item.unit_price or 0.0)
			item.total_price = quantity * unit_price

			labor_hours = float(item.labor_hours or 0.0)
			labor_rate = float(item.labor_rate or 0.0)
			item.labor_total = labor_hours * labor_rate

			total_cost += item.total_price + item.labor_total
		
		self.total_cost = total_cost

	def update_container_status(self):
		"""Update container's status and repair_status based on this Repair Order"""
		if not self.container:
			return

		container_doc = frappe.get_doc("Container", self.container)
		
		# Map Repair Order status to Container status and repair_status
		if self.status == "Draft":
			container_doc.repair_status = "Pending_Estimate"
		elif self.status == "Pending Approval":
			container_doc.repair_status = "Awaiting_Approval"
		elif self.status in ["Approved", "In Progress"]:
			container_doc.repair_status = "In_Progress"
			container_doc.status = "Repair_In_Progress"
		elif self.status == "Completed":
			container_doc.repair_status = "Completed"
			# Move container back to Ready_For_Service (or Available) if repair is finished
			container_doc.status = "Ready_For_Service"
		elif self.status == "Cancelled":
			container_doc.repair_status = "Not_Required"

		# Controller-driven status change: bypass the manual-transition guard.
		frappe.flags.in_status_automation = True
		try:
			container_doc.save(ignore_permissions=True)
		finally:
			frappe.flags.in_status_automation = False
