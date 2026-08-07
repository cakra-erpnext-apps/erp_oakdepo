import frappe
from frappe.model.document import Document

from container_depot import finance


class DepotFinanceSettings(Document):
	def on_update(self):
		# The switch is read on nearly every operational save, so it is cached. Drop the
		# cache here or the site keeps running on the old setting until the next restart.
		finance.clear_cache()
