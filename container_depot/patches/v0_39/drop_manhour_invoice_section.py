"""Sales Invoice: retire the standalone Manhour section.

Labour first shipped as its own section on the invoice, which meant hunting for it and
reading it apart from the price it belongs to. The three fields now sit in the standard
Totals block, directly under Total / Net Total, so labour is read beside the price. The
section and column breaks that framed the old block are dead — ``create_custom_fields``
only creates and updates, it never removes, so they are dropped here.
"""

import frappe

_OBSOLETE = ["depot_manhour_section", "depot_manhour_column"]


def execute():
	for fieldname in _OBSOLETE:
		name = frappe.db.get_value("Custom Field", {"dt": "Sales Invoice", "fieldname": fieldname})
		if name:
			frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)
			print(f"[container_depot] dropped Sales Invoice custom field {fieldname}")
	frappe.clear_cache(doctype="Sales Invoice")
