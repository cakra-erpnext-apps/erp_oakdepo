"""Swap the customer role's Audit section for the Container Inventory section.

The customer sidebar used to end in "Audit": three raw lists — Gate Entry, Container
Movement, Container Activity — because those were the only shape the tank's history came
in. They are a poor answer. A doctype list cannot carry a storage age, an order column or
a per-principal rollup, and two of the three are OAK's own internal movement records.

The same facts now arrive as the three reports in the "Container Inventory" section
(`customer_scope.CUSTOMER_REPORTS`), each filtering by customer in its own query:

* Container Inventory          — the tanks, their stage, age and open orders
* Container Activity           — the history, same ledger, filtered
* Inventory KPI per Principal  — the rollup

So the DocPerm matrix loses Gate Entry and Container Movement outright, and Container
Activity keeps `report` while losing `read`: a Workspace Sidebar Item has no role field,
so `can_read` is the only lever that takes a doctype off the rail, and
`frappe.desk.query_report` asks for `report` on the ref doctype alone. `Container` gains
`report` for the two reports that hang off it.

The permission seeder is add-only — an existing (doctype, role) row belongs to the admin —
so every change to a row that already exists has to be made here.

Idempotent: every step is a no-op on a site that has already run it.
"""

from __future__ import annotations

import frappe

from container_depot.install import CUSTOMER_DESK_ROLE, setup_permissions

# Gone from the customer's Desk entirely.
DROP = ("Gate Entry", "Container Movement")
# {doctype: flags to force}, for rows the add-only seeder will not revisit.
SET = {
	# Report-only: the history is read through the report, the ledger itself stays shut.
	"Container Activity": {"read": 0, "export": 0, "print": 0, "report": 1},
	# The two reports hanging off Container become reachable.
	"Container": {"report": 1},
}


def execute():
	# Picks up any (doctype, role) pair that has no row yet.
	setup_permissions()

	for doctype in DROP:
		frappe.db.delete("Custom DocPerm", {"parent": doctype, "role": CUSTOMER_DESK_ROLE})
	for doctype, flags in SET.items():
		name = frappe.db.get_value(
			"Custom DocPerm", {"parent": doctype, "role": CUSTOMER_DESK_ROLE}, "name"
		)
		if name:
			frappe.db.set_value("Custom DocPerm", name, flags, update_modified=False)

	frappe.clear_cache()
	frappe.db.commit()
