"""Retire the ``Part (Beli Langsung)`` Jenis on Repair Used Item.

The label meant "a physical part bought for this job and never stocked". Nothing in
ERPNext can tell such an item from a plain service — both are ``is_stock_item = 0`` —
so the choice between the two identical-looking labels rested entirely on the operator,
changed nothing about how the line was priced, issued or billed, and only made the
Service & Parts grid harder to fill. Anything not drawn from a gudang is now "Jasa".

Two leftovers to clear:

* the rows already written under the old label — the option is gone from the Select, so
  they would render blank and fail validation on the next save of their order;
* ``Item Group.is_depot_part_group`` — the Check that existed ONLY to split the two
  non-stock labels apart in the item picker (``mr.mr_item_search``). With one non-stock
  label left it has no consumer, and a custom field left on the form invites someone to
  keep classifying groups for a rule that no longer reads them.

Idempotent: both steps are no-ops on a site that has already been through it.
"""

from __future__ import annotations

import frappe


def execute():
	frappe.reload_doc("container_depot", "doctype", "repair_used_item")
	frappe.db.sql(
		"""UPDATE `tabRepair Used Item`
		   SET line_type = 'Jasa'
		   WHERE line_type = 'Part (Beli Langsung)'"""
	)
	if frappe.db.exists("Custom Field", "Item Group-is_depot_part_group"):
		frappe.delete_doc("Custom Field", "Item Group-is_depot_part_group", ignore_permissions=True)
		frappe.clear_cache(doctype="Item Group")
