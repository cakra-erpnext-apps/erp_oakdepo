"""Make the gate + audit doctypes read/write-only: no create, no submit, no delete.

The seeder is add-only, so tightening ``install.NO_MANUAL_CREATE`` changes nothing on a site
that already has the Custom DocPerm rows — including the System Manager blanket grant, which
is what actually put the "+ Add" button on Riwayat Gate. This clears those flags once.

Deliberately blunt: every role on those doctypes, not just the seeded ones. A hand-granted
create on an append-only ledger is the same mistake whoever granted it.
"""

import frappe

from container_depot.install import NO_MANUAL_CREATE

_STRIPPED = {"create": 0, "submit": 0, "cancel": 0, "amend": 0, "delete": 0}


def execute():
	doctypes = sorted(dt for dt in NO_MANUAL_CREATE if frappe.db.exists("DocType", dt))
	if not doctypes:
		return
	rows = frappe.get_all("Custom DocPerm", filters={"parent": ["in", doctypes]}, pluck="name")
	for name in rows:
		frappe.db.set_value("Custom DocPerm", name, _STRIPPED, update_modified=False)
	if rows:
		frappe.clear_cache()
	print(f"Locked {len(rows)} Custom DocPerm rows on {', '.join(doctypes)}")
