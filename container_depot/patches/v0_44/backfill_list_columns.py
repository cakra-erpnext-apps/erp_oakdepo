import frappe


def execute():
	"""Populate the new Desk list-view columns on existing rows.

	``fetch_from`` / ``before_insert`` only fire on new writes, so older records carry blank
	values and would show "—" in the list. Backfill them once from the source:
	  • Cleaning Order.container_principal ← Container.principal (Owner column)
	  • Repair Order.order_created         ← the row's own creation timestamp (Created column)
	  • Repair Order.principal             ← Container.principal (Owner column; usually already
	    set by the controller, filled here only when blank)
	"""
	if frappe.db.table_exists("Cleaning Order") and frappe.db.has_column("Cleaning Order", "container_principal"):
		frappe.db.sql(
			"""UPDATE `tabCleaning Order` co
			   JOIN `tabContainer` c ON co.container = c.name
			   SET co.container_principal = c.principal
			   WHERE (co.container_principal IS NULL OR co.container_principal = '')
			     AND c.principal IS NOT NULL AND c.principal != ''"""
		)

	if frappe.db.table_exists("Repair Order"):
		if frappe.db.has_column("Repair Order", "order_created"):
			frappe.db.sql(
				"""UPDATE `tabRepair Order`
				   SET order_created = creation
				   WHERE order_created IS NULL"""
			)
		frappe.db.sql(
			"""UPDATE `tabRepair Order` ro
			   JOIN `tabContainer` c ON ro.container = c.name
			   SET ro.principal = c.principal
			   WHERE (ro.principal IS NULL OR ro.principal = '')
			     AND c.principal IS NOT NULL AND c.principal != ''"""
		)
