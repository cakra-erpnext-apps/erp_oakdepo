# Copyright (c) 2026, Oak Depot Team and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class RepairCostTotal(Document):
	"""One per-currency subtotal of a Repair Order's Service & Parts Used lines. A Repair
	Order can mix currencies (each Item Price carries its own), so totals are grouped by
	currency rather than summed into a single figure."""

	pass
