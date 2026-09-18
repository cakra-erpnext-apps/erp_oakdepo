"""Open the customer role's menu: the two reports it is owed, and four masters.

The seeder is add-only — it skips a (doctype, role) pair the moment a Custom DocPerm row
exists — so the matrix changes in `install.py` reach a site that has already migrated only
through a patch. Two kinds of change here:

* rows that do not exist yet (Cargo, Storage Charge, Customer, Item, Item Group) — a plain
  `setup_permissions()` picks those up, masters included;
* one flag on a row that DOES exist: `report` on `Container Booking`, which
  `v1_00.customer_desk_report_flag` stripped when the rule was "a customer runs no report
  at all". That rule has been narrowed rather than reversed: the gate is now the report
  NAME (`customer_scope.CUSTOMER_REPORTS`), enforced on the menu by a query condition and
  on the run path by `boot.patch_query_report_customer_scope`, so the two reports that read
  through a customer filter can be reached and the two that build raw SQL still cannot.
"""

import frappe

from container_depot.install import CUSTOMER_DESK_ROLE, setup_permissions


def execute():
	setup_permissions()

	row = frappe.db.get_value(
		"Custom DocPerm", {"parent": "Container Booking", "role": CUSTOMER_DESK_ROLE}, "name"
	)
	if row:
		frappe.db.set_value("Custom DocPerm", row, "report", 1, update_modified=False)

	frappe.clear_cache()
