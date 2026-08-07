import frappe
from frappe import _
from frappe.model.document import Document


class DepotServiceMenu(Document):
	def validate(self):
		self._dedupe_child_rows()

	def _dedupe_child_rows(self):
		"""Drop duplicate group / item rows so the menu stays a clean set."""
		seen_groups = set()
		kept_groups = []
		for row in self.get("item_groups") or []:
			if row.item_group and row.item_group not in seen_groups:
				seen_groups.add(row.item_group)
				kept_groups.append(row)
		self.set("item_groups", kept_groups)

		seen_items = set()
		kept_items = []
		for row in self.get("extra_items") or []:
			if row.item and row.item not in seen_items:
				seen_items.add(row.item)
				kept_items.append(row)
		self.set("extra_items", kept_items)
