"""Retire the Cleaning Certificate entirely — the flow no longer issues one.

The finished **Cleaning Order** is now the single cleanliness record (checklist, gas free,
seals, surveyor signature) AND the TANK OUT proof: ``Order Muat._validate_cleaning_done``
refuses any container without a submitted, Completed Cleaning Order.

This drops the doctype, its print format, the notification rows that point at it, and the
link fields other doctypes carried (``Order Container Item.cleaning_certificate``,
``Cleaning Order.cleaning_certificate``, ``Inspection.cleaning_cert`` /
``cleaning_cert_valid_until``). Irreversible by design — the user asked for a full removal.
"""

import frappe

_DOCTYPE = "Cleaning Certificate"
# (parent doctype, fieldname) pairs whose columns go with the certificate.
_ORPHANED_COLUMNS = [
	("Order Container Item", "cleaning_certificate"),
	("Cleaning Order", "cleaning_certificate"),
	("Inspection", "cleaning_cert"),
	("Inspection", "cleaning_cert_valid_until"),
]


def execute():
	_drop_orphaned_columns()
	_drop_dependents()
	_drop_doctype()


def _drop_orphaned_columns() -> None:
	"""Drop the leftover DB columns — removing a field from the JSON does not drop it."""
	for doctype, fieldname in _ORPHANED_COLUMNS:
		table = f"tab{doctype}"
		if not frappe.db.table_exists(doctype):
			continue
		if fieldname not in [c.get("name") for c in frappe.db.get_table_columns_description(table)]:
			continue
		frappe.db.sql_ddl(f"ALTER TABLE `{table}` DROP COLUMN `{fieldname}`")
		print(f"[container_depot] dropped {table}.{fieldname}")


def _drop_dependents() -> None:
	"""Clear rows that reference the doctype so deleting it doesn't trip link checks."""
	for dt, field in (
		("Notification Log", "document_type"),
		("Custom DocPerm", "parent"),
		("Property Setter", "doc_type"),
		("Custom Field", "dt"),
	):
		if frappe.db.table_exists(dt):
			frappe.db.delete(dt, {field: _DOCTYPE})
	if frappe.db.exists("Print Format", "Cleaning Certificate Format"):
		frappe.delete_doc("Print Format", "Cleaning Certificate Format", force=True, ignore_permissions=True)


def _drop_doctype() -> None:
	if not frappe.db.exists("DocType", _DOCTYPE):
		print(f"[container_depot] {_DOCTYPE} already gone.")
		return
	# force=True: the doctype is submittable, so ordinary delete would refuse.
	frappe.delete_doc("DocType", _DOCTYPE, force=True, ignore_permissions=True)
	frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{_DOCTYPE}`")
	print(f"[container_depot] dropped {_DOCTYPE} + its table.")
