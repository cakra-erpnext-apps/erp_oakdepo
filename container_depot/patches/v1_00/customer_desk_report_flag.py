"""Strip the `report` flag from the Customer Desk role's permissions.

The role shipped with the `v` grammar when it still carried `report`. That flag is what
`frappe.desk.query_report.run` checks before running a Query Report — and a Query Report
runs raw SQL, so none of the customer filtering in `container_depot/customer_scope.py`
applies to its rows. A customer holding it could read the whole depot's billing register.

The permission seeder is add-only (an existing row belongs to the admin), so the flag has
to be cleared here.
"""

import frappe

from container_depot.install import CUSTOMER_DESK_ROLE


def execute():
	rows = frappe.get_all(
		"Custom DocPerm", filters={"role": CUSTOMER_DESK_ROLE, "report": 1}, pluck="name"
	)
	for name in rows:
		frappe.db.set_value("Custom DocPerm", name, "report", 0, update_modified=False)
	if rows:
		frappe.clear_cache()
