from frappe.model.document import Document

from container_depot.container_depot import notify


class DepotNotificationSettings(Document):
	def on_update(self):
		# The master switch and the fallback list are read on every notified event, so
		# they are cached. Drop the cache here or the site keeps notifying on the old
		# setting until the next restart.
		notify.clear_rule_cache()
