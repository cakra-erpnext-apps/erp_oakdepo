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

	def owner_price_list(self):
		"""The selling Price List for this M&R's owner/principal — drives every rate
		(harga ikut Item Price per principal). None when the owner has no price list."""
		from container_depot.pricing_model import price_list_for_customer

		principal = self.principal or frappe.db.get_value("Container", self.container, "principal")
		return price_list_for_customer(principal) if principal else None

	def calculate_totals(self):
		"""Price every Used Item line from the owner's Item Price and roll up ``total_cost``
		(the price is hidden in the PWA but still drives owner billing). Rates are NEVER
		taken from the client — they always follow the Item Price (repair services:
		manhour × manhour_rate + material_cost; parts: the flat price_list_rate). The copied
		``damages`` carry no cost; legacy ``estimation_items`` keep their manual totals."""
		from container_depot.pricing_model import resolve_price

		price_list = self.owner_price_list()
		total_cost = 0.0

		for row in self.get("used_items") or []:
			row.is_stock_item = (
				1 if row.item and frappe.db.get_value("Item", row.item, "is_stock_item") else 0
			)
			row.rate = resolve_price(row.item, price_list) if row.item else 0.0
			row.amount = float(row.quantity or 0.0) * float(row.rate or 0.0)
			total_cost += row.amount

		# Legacy estimate lines (pre-split) — manual qty × price + labour.
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

		before = self.get_doc_before_save()
		prev_status = before.status if before else None
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
			# Repair finished → back to the ready pool.
			container_doc.status = "Available"
		elif self.status == "Cancelled":
			container_doc.repair_status = "Not_Required"

		# Controller-driven status change: bypass the manual-transition guard.
		frappe.flags.in_status_automation = True
		try:
			container_doc.save(ignore_permissions=True)
		finally:
			frappe.flags.in_status_automation = False

		# Log a Repair milestone when the order is approved / progressed / finished.
		if self.status in ("Approved", "In Progress", "Completed") and self.status != prev_status:
			from container_depot.operations.container_activity import log_container_activity

			log_container_activity(
				self.container, "Repair",
				reference_doctype=self.doctype, reference_name=self.name,
				to_status=container_doc.status,
				performed_by=self.get("technician"),
				summary=f"Repair {self.status}" + (f" (cost {self.total_cost})" if self.get("total_cost") else ""),
			)
