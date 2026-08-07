import frappe
from frappe import _
from frappe.model.document import Document

# Fields that may never change once a Container Activity row is written (append-only).
_FROZEN_FIELDS = (
	"container", "activity_time", "activity_type", "reference_doctype",
	"reference_name", "from_status", "to_status", "performed_by", "summary",
)


class ContainerActivity(Document):
	def on_trash(self):
		# Append-only: only System Manager can delete.
		if "System Manager" not in frappe.get_roles(frappe.session.user):
			frappe.throw(_("Container Activity is append-only and cannot be deleted."))

	def on_update(self):
		# Disallow edits after creation (except by System Manager).
		if self.is_new():
			return
		if "System Manager" in frappe.get_roles(frappe.session.user):
			return
		previous = self.get_doc_before_save()
		if previous and any(
			getattr(previous, k, None) != getattr(self, k, None) for k in _FROZEN_FIELDS
		):
			frappe.throw(_("Container Activity entries are append-only."))
