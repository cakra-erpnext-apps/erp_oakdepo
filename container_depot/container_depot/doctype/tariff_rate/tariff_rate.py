import frappe
from frappe.model.document import Document


class TariffRate(Document):
	def validate(self):
		if self.rate is not None and self.rate < 0:
			frappe.throw("Tariff rate cannot be negative.")
