import frappe
from frappe.model.document import Document
import datetime
import hashlib

class Inspection(Document):
	def before_insert(self):
		"""Generate inspection ID"""
		self.inspection_id = self.generate_inspection_id()

	def generate_inspection_id(self):
		"""Generate unique inspection ID"""
		timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
		unique = hashlib.md5(f"{timestamp}{frappe.generate_hash()[:10]}".encode()).hexdigest()[:8].upper()
		return f"EIR-{unique}"

	def before_save(self):
		"""Auto-populate container number"""
		if self.container:
			container = frappe.get_doc("Container", self.container)
			self.container_no = container.container_no

	def validate(self):
		"""Validate inspection data"""
		# Validate that 4 exterior photos are uploaded for EIR-In
		if self.inspection_type == "EIR-In":
			exterior_views = [p.photo_view for p in self.exterior_photos if p.photo_view in ["Front", "Back", "Left", "Right"]]
			if len(exterior_views) < 4:
				frappe.msgprint(f"Warning: Only {len(exterior_views)} exterior photos uploaded. 4 views (Front, Back, Left, Right) recommended for EIR-In.")

	SEAL_FIELDS = (
		"seal_manhole",
		"seal_airline",
		"seal_bottom_outlet",
		"seal_top_discharge",
		"seal_vapour_valve",
	)

	def on_submit(self):
		"""Update container status when inspection is submitted"""
		container = frappe.get_doc("Container", self.container)

		if self.inspection_type == "EIR-In":
			container.status = "Inspecting"
			container.eir_in_date = datetime.datetime.now()
			self._save_container(container)
		elif self.inspection_type == "Detailed Survey":
			self._apply_survey_result(container)

	def _save_container(self, container):
		# Controller-driven status change: bypass the manual-transition guard.
		frappe.flags.in_status_automation = True
		try:
			container.save(ignore_permissions=True)
		finally:
			frappe.flags.in_status_automation = False

	def _apply_survey_result(self, container):
		"""Route the container based on the survey outcome (PRO-OPS survey loop):

		* damage         -> Awaiting_MR_Approval (+ a Pending-Approval Repair Order)
		* dirty (no dmg) -> Awaiting_Recleaning_Approval
		* clean          -> Cleaning_Cert_Issued
		"""
		# Carry the surveyor's seal readings onto the container.
		for f in self.SEAL_FIELDS:
			val = self.get(f)
			if val:
				container.set(f, val)

		if self.has_damage:
			container.status = "Awaiting_MR_Approval"
			container.repair_status = "Awaiting_Approval"
			self._save_container(container)
			self._ensure_repair_order()
		elif self.tank_status == "Empty Dirty":
			container.status = "Awaiting_Recleaning_Approval"
			self._save_container(container)
		else:
			container.status = "Cleaning_Cert_Issued"
			container.certification_status = "Completed"
			self._save_container(container)

		self._complete_survey_request()

	def _ensure_repair_order(self):
		"""Create a Pending-Approval Repair Order from this survey's estimate so
		the Tank Owner can approve M&R. Idempotent per inspection."""
		if frappe.db.exists("Repair Order", {"inspection": self.name}):
			return
		ro = frappe.new_doc("Repair Order")
		ro.container = self.container
		ro.inspection = self.name
		ro.status = "Pending Approval"
		ro.billing_status = "Unbilled"
		exclude = {
			"name", "parent", "parentfield", "parenttype", "idx",
			"owner", "creation", "modified", "modified_by", "docstatus", "doctype",
		}
		for row in (self.repair_estimate or []):
			ro.append("estimation_items", {k: v for k, v in row.as_dict().items() if k not in exclude})
		ro.insert(ignore_permissions=True)

	def _complete_survey_request(self):
		"""Mark a linked Survey Request as Completed and back-link this EIR."""
		reqs = frappe.get_all(
			"Survey Request",
			filters={"container": self.container, "status": ["in", ["Pending Survey", "In Progress"]], "docstatus": ["<", 2]},
			pluck="name",
		)
		for name in reqs:
			frappe.db.set_value("Survey Request", name, {"status": "Completed", "inspection": self.name}, update_modified=False)
