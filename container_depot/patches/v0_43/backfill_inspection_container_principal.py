import frappe


def execute():
	"""Populate the new ``container_principal`` (Owner) fetch field on existing EIRs.

	``fetch_from`` only fires on save, so records created before the field existed carry a
	blank owner and would show "—" in the Desk list. Copy it straight from the linked
	Container once; new/edited EIRs fetch it themselves.
	"""
	if not (frappe.db.table_exists("Inspection") and frappe.db.table_exists("Container")):
		return
	if not frappe.db.has_column("Inspection", "container_principal"):
		return
	frappe.db.sql(
		"""UPDATE `tabInspection` i
		   JOIN `tabContainer` c ON i.container = c.name
		   SET i.container_principal = c.principal
		   WHERE (i.container_principal IS NULL OR i.container_principal = '')
		     AND c.principal IS NOT NULL AND c.principal != ''"""
	)
