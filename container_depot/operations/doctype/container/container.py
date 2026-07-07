import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from container_depot.state_machine import assert_transition, stage_for_status


class Container(Document):
	def validate(self):
		# Container number is required (enforced by the field) but not length-checked —
		# real depot data carries non-ISO / short numbers, so only presence is required.

		# Guard manual status transitions against the canonical state machine.
		# Internal automation (Repair/Cleaning/Inspection controllers) and
		# migrations bypass via frappe.flags.in_status_automation.
		if not self.is_new() and self.has_value_changed("status"):
			previous = self.get_doc_before_save()
			assert_transition(previous.status if previous else None, self.status)

	def before_save(self):
		"""Auto-format container number + keep the monitoring stage in step with the
		raw status (every ORM save: gate entry, inspection, cleaning, repair, release)."""
		if self.container_no:
			self.container_no = self.container_no.upper()
		self.inventory_stage = stage_for_status(self.status)

	def on_update(self):
		"""Audit-trail: log a Container Movement row whenever ``status`` changes.

		Skipped when the save was *caused* by a Container Movement (avoids the
		Movement -> Container -> Movement loop), and when the new value is the
		same as the previous one (no-op save).
		"""
		if getattr(frappe.flags, "in_container_movement", False):
			return
		if not self.has_value_changed("status"):
			return
		previous = self.get_doc_before_save()
		from_status = previous.status if previous else None
		frappe.get_doc({
			"doctype": "Container Movement",
			"container": self.name,
			"event_type": "Status",
			"movement_timestamp": now_datetime(),
			"moved_by": frappe.session.user or "Administrator",
			"from_status": from_status,
			"to_status": self.status,
		}).insert(ignore_permissions=True)
