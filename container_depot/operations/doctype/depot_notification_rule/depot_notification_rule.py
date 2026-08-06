import frappe
from frappe import _
from frappe.model.document import Document

from container_depot.operations import notify


class DepotNotificationRule(Document):
	def validate(self):
		# An enabled rule with nobody on it sends into the void, and nothing surfaces the
		# mistake — the event just stops arriving and someone notices weeks later that
		# they never heard about a pending approval. Refuse it at save time instead.
		if self.enabled and not self.roles:
			frappe.throw(
				_("Rule aktif wajib punya minimal satu role penerima. Matikan 'Aktif' untuk menonaktifkan event ini.")
			)

	def on_update(self):
		notify.clear_rule_cache()

	def on_trash(self):
		notify.clear_rule_cache()
