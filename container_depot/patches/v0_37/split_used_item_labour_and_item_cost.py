"""Repair Used Item: split a line's cost into labour + item.

The old model priced a line as ``rate = manhour_amount + material_cost`` and
``amount = qty × rate`` — so labour was multiplied by the quantity. The new model keeps them
separate and read-only:

    manhour_amount (Amount Cost Manhour) = manhour × manhour_rate
    item_amount    (Amount Item Rate)    = quantity × item_rate
    amount         (Total Cost)          = manhour_amount + item_amount

``material_cost`` (already a per-unit figure) becomes ``item_rate``; ``rate`` is dropped.
This patch carries the data over and recomputes the three derived amounts, then refreshes each
Repair Order's ``total_cost`` (the per-currency ``totals`` table rebuilds on the next save).
"""

import frappe

TABLE = "tabRepair Used Item"


def execute():
	frappe.reload_doc("operations", "doctype", "repair_used_item")
	frappe.reload_doc("operations", "doctype", "repair_order")

	if not frappe.db.has_column("Repair Used Item", "item_rate"):
		return  # doctype not synced yet — nothing to carry over

	# Carry the per-unit material cost over to the new item_rate column.
	if frappe.db.has_column("Repair Used Item", "material_cost"):
		frappe.db.sql(
			f"UPDATE `{TABLE}` SET item_rate = material_cost WHERE IFNULL(item_rate, 0) = 0"
		)

	# Recompute the derived amounts under the new (labour + item) model.
	frappe.db.sql(
		f"""UPDATE `{TABLE}` SET
			manhour_amount = IFNULL(manhour, 0) * IFNULL(manhour_rate, 0),
			item_amount    = IFNULL(quantity, 0) * IFNULL(item_rate, 0)"""
	)
	frappe.db.sql(
		f"UPDATE `{TABLE}` SET amount = IFNULL(manhour_amount, 0) + IFNULL(item_amount, 0)"
	)

	# Refresh each Repair Order's numeric total from its non-rejected lines.
	frappe.db.sql(
		"""UPDATE `tabRepair Order` ro SET ro.total_cost = IFNULL((
			SELECT SUM(ui.amount) FROM `tabRepair Used Item` ui
			WHERE ui.parent = ro.name AND ui.parenttype = 'Repair Order'
			  AND IFNULL(ui.decision, 'Pending') != 'Rejected'
		), 0)"""
	)
