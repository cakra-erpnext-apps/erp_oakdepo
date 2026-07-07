import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class ContainerMovement(Document):
	"""Append-only status-audit ledger. One row is logged by ``Container.on_update``
	whenever a container's ``status`` changes (event_type ``Status``). The depot no
	longer maps tanks to yard zones, so this doc only records status transitions.
	Legacy ``Yard`` rows (with from/to zone coordinates) may still exist in the DB.
	"""

	def before_insert(self):
		if not self.movement_timestamp:
			self.movement_timestamp = now_datetime()
		if not self.moved_by:
			self.moved_by = frappe.session.user or "Administrator"
		if not self.event_type:
			self.event_type = "Status"
		if self.container and not self.from_status:
			self.from_status = frappe.db.get_value("Container", self.container, "status")
