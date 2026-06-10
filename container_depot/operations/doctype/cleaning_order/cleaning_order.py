import frappe
from frappe.model.document import Document
import datetime
import hashlib

class CleaningOrder(Document):
	def before_insert(self):
		"""Generate cleaning order ID"""
		self.order_id = self.generate_order_id()
		self.order_created = datetime.datetime.now()
		self.created_by = frappe.session.user

	def generate_order_id(self):
		"""Generate unique cleaning order ID"""
		timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
		unique = hashlib.md5(f"{timestamp}{frappe.generate_hash()[:10]}".encode()).hexdigest()[:8].upper()
		return f"CO-{unique}"

	def before_save(self):
		"""Auto-populate container info"""
		if self.container:
			container = frappe.get_doc("Container", self.container)
			self.container_no = container.container_no
			self.last_cargo = container.last_cargo
			self.zone = container.yard_zone

	def calculate_priority_score(self):
		"""
		Calculate priority score for cleaning queue.
		Higher score = higher priority.
		"""
		score = 0

		# Factor 1: Release date urgency (if known)
		# This would need integration with release orders

		# Factor 2: Time in queue (older = higher priority)
		if self.order_created:
			hours_in_queue = (datetime.datetime.now() - self.order_created).total_seconds() / 3600
			score += hours_in_queue * 0.5

		# Factor 3: Last cargo type (hazardous = higher priority)
		hazardous_cargos = ["Chemical", "Toxic", "Corrosive", "Flammable"]
		if self.last_cargo:
			for cargo in hazardous_cargos:
				if cargo.lower() in self.last_cargo.lower():
					score += 50
					break

		# Factor 4: Customer tier (premium customers get priority)
		# This would need integration with customer master

		self.priority_score = score
		return score

	def on_submit(self):
		"""Update container status when cleaning order is submitted."""
		self._propagate_to_container(log_always=True)

	def on_update_after_submit(self):
		"""Status / approval edits after submit also drive the container so a
		re-clean can progress Pending -> In_Progress -> Completed over time."""
		self._propagate_to_container()

	def _propagate_to_container(self, log_always=False):
		"""Mirror the cleaning order's progress onto its container.

		Re-cleaning (post-survey) uses the portal lifecycle states; a normal
		first clean keeps the original behaviour (-> Available).
		"""
		if not self.container:
			return
		before = self.get_doc_before_save()
		prev_status = before.status if before else None
		container = frappe.get_doc("Container", self.container)

		if self.is_recleaning:
			if self.status == "In_Progress":
				container.cleaning_status = "In_Progress"
				container.status = "Recleaning_In_Progress"
			elif self.status == "Completed":
				container.cleaning_status = "Completed"
				container.status = "Cleaning_Completed"
		else:
			if self.status == "In_Progress":
				container.cleaning_status = "In_Progress"
			elif self.status == "Completed":
				container.cleaning_status = "Completed"
				container.status = "Available"

		# Controller-driven status change: bypass the manual-transition guard.
		frappe.flags.in_status_automation = True
		try:
			container.save(ignore_permissions=True)
		finally:
			frappe.flags.in_status_automation = False

		# Log a Cleaning milestone on start / completion (deduped against unrelated
		# after-submit edits).
		if self.status in ("In_Progress", "Completed") and (log_always or self.status != prev_status):
			from container_depot.operations.container_activity import log_container_activity

			label = "re-clean" if self.is_recleaning else "clean"
			log_container_activity(
				self.container, "Cleaning",
				reference_doctype=self.doctype, reference_name=self.name,
				to_status=container.status,
				performed_by=self.get("completed_by") or self.get("assigned_to"),
				summary=f"Cleaning {self.status.lower().replace('_', ' ')} ({label})",
			)
