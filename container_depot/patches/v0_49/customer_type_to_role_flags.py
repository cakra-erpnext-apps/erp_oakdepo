import frappe

# Old exclusive Select value -> the independent role flag(s) it becomes.
_MAP = {
	"Tank Owner": ("is_tank_owner",),
	"Transporter": ("is_transporter",),
	"Both": ("is_tank_owner", "is_transporter"),
	"Agent": ("is_agent",),
}


def execute():
	"""Retire ``Customer.oak_customer_type`` (Select) for three independent role checks.

	A customer routinely wears more than one hat — an EMKL that also owns tanks, an agent
	that also trucks — which one exclusive Select could only express with a "Both" value
	that never scaled past two roles. ``is_tank_owner`` / ``is_transporter`` / ``is_agent``
	are free to combine.

	Migrates every existing value (Both -> owner + transporter), then deletes the old
	Custom Field and drops its column. Idempotent: once the column is gone the mapping is
	skipped and only the (no-op) delete/drop run.
	"""
	if not frappe.db.table_exists("Customer"):
		return

	# The new fields are created by the after_migrate hook, which runs AFTER patches — do
	# it here (idempotently, same definitions) so this patch has columns to write into.
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	from container_depot.install import CUSTOM_FIELDS

	create_custom_fields({"Customer": CUSTOM_FIELDS["Customer"]}, ignore_validate=True)

	if frappe.db.has_column("Customer", "oak_customer_type"):
		for value, flags in _MAP.items():
			frappe.db.sql(
				"UPDATE `tabCustomer` SET {sets} WHERE oak_customer_type = %s".format(
					sets=", ".join("`{0}` = 1".format(f) for f in flags)
				),
				value,
			)

	frappe.delete_doc_if_exists("Custom Field", "Customer-oak_customer_type")
	frappe.db.sql_ddl("ALTER TABLE `tabCustomer` DROP COLUMN IF EXISTS `oak_customer_type`")
	frappe.db.commit()
