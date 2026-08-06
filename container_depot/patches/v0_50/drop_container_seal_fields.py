"""Container: drop the five seal Data fields, replaced by the live EIR-Out seal history.

Seals are fitted at release and recorded on the EIR-Out (``out_seals``); a tank is sealed
once per release, so a single set of numbers on the master could only ever show the last one
— and would keep reading as current after the tank came back and was unsealed. Nothing in the
app ever wrote these five columns anyway. The Seals section now renders
``container.seal_history`` instead.

Removing a field from the doctype JSON does not drop its DB column, so this cleans up the
leftovers. Any value that WAS in there (only reachable via data import — Container has
``allow_import``) is reported before the drop, so it shows up in the migrate log rather than
disappearing quietly.
"""

import frappe

_COLUMNS = [
	"seal_manhole",
	"seal_airline",
	"seal_bottom_outlet",
	"seal_top_discharge",
	"seal_vapour_valve",
]


def execute():
	frappe.reload_doc("operations", "doctype", "container")
	existing = [
		c
		for c in _COLUMNS
		if c in {col.get("name") for col in frappe.db.get_table_columns_description("tabContainer")}
	]
	if not existing:
		return
	_report_data(existing)
	for column in existing:
		frappe.db.sql_ddl(f"ALTER TABLE `tabContainer` DROP COLUMN `{column}`")
		print(f"[container_depot] dropped tabContainer.{column}")


def _report_data(columns: list) -> None:
	"""Say out loud how many tanks carried a value, so a surprise is visible, not silent."""
	where = " OR ".join(f"COALESCE(`{c}`, '') <> ''" for c in columns)
	count = frappe.db.sql(f"SELECT COUNT(*) FROM `tabContainer` WHERE {where}")[0][0]
	if count:
		print(
			f"[container_depot] WARNING: {count} Container row(s) had seal values in the "
			"dropped columns — seals live on the EIR-Out from now on."
		)
