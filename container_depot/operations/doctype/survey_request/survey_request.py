import frappe
from frappe.model.document import Document


class SurveyRequest(Document):
	"""Customer-initiated survey request, assigned to a Surveyor Company.

	The container status transition (-> Pending_Survey / Survey_In_Progress) and
	the result feedback loop are wired in B3.
	"""

	def before_insert(self):
		if not self.requested_date:
			self.requested_date = frappe.utils.today()
