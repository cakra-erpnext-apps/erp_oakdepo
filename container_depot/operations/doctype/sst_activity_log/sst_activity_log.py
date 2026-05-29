import frappe
from frappe import _
from frappe.model.document import Document


class SSTActivityLog(Document):
	def on_trash(self):
		# Append-only: only System Manager can delete (see permissions block).
		if "System Manager" not in frappe.get_roles(frappe.session.user):
			frappe.throw(_("SST Activity Log is append-only and cannot be deleted."))

	def on_update(self):
		# Disallow edits after creation (except by System Manager).
		if self.is_new():
			return
		if "System Manager" in frappe.get_roles(frappe.session.user):
			return
		previous = self.get_doc_before_save()
		if previous and any(
			getattr(previous, k, None) != getattr(self, k, None)
			for k in ("sst", "action", "result", "booking_code", "timestamp", "payload_json")
		):
			frappe.throw(_("SST Activity Log entries are append-only."))
