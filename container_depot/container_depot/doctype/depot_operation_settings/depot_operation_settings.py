from frappe.model.document import Document

from container_depot.container_depot import order_policy


class DepotOperationSettings(Document):
	def on_update(self):
		# Read on every bon muat / EIR-Out / gate-out, so it is cached per request.
		order_policy.clear_cache()
