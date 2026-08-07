import frappe
from frappe.model.document import Document


class CustomerPortalUser(Document):
	"""A user belonging to a customer company, with an intra-company role.

	The provisioning side-effect (granting the Customer role + a scoped User
	Permission when approval_status becomes Active) is wired in B3 via a
	``doc_events`` handler so Desk-created rows get scoped automatically.
	"""

	def before_insert(self):
		if not self.added_on:
			self.added_on = frappe.utils.today()
