import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class ContainerMovement(Document):
	def before_insert(self):
		"""Set defaults and capture previous container coordinates / status."""
		if not self.movement_timestamp:
			self.movement_timestamp = now_datetime()
		if not self.moved_by:
			self.moved_by = frappe.session.user or "Administrator"
		if not self.event_type:
			self.event_type = "Yard"

		if self.container:
			container_doc = frappe.get_doc("Container", self.container)
			if not self.from_zone:
				self.from_zone = container_doc.yard_zone
				self.from_row = container_doc.row
				self.from_bay = container_doc.bay
				self.from_tier = container_doc.tier
			if not self.from_status:
				self.from_status = container_doc.status

	def after_insert(self):
		"""Push the destination coordinates back to the Container.

		Skipped for Status-only events (no to_zone) so the audit row doesn't
		clear the container's existing yard location.
		"""
		if not self.container:
			return
		if self.event_type == "Status":
			return
		container_doc = frappe.get_doc("Container", self.container)
		# Guard so Container.on_update doesn't spawn another Movement.
		frappe.flags.in_container_movement = True
		try:
			container_doc.yard_zone = self.to_zone
			container_doc.current_location = self.to_zone
			container_doc.row = self.to_row
			container_doc.bay = self.to_bay
			container_doc.tier = self.to_tier
			container_doc.save(ignore_permissions=True)
		finally:
			frappe.flags.in_container_movement = False
