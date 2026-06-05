"""Canonicalise Container.status after the state-machine normalisation.

The `Container.status` Select dropped three legacy values (and the duplicated
`In_Workshop`) and gained the portal lifecycle states. This patch remaps any
existing rows that still hold a retired value, on BOTH the `Container` master
and the `Container Movement` audit trail (`from_status` / `to_status` are Data
columns, so they hold whatever string was written at the time).

Idempotent: rows already on a canonical value don't match the map and are
skipped. Uses raw SQL (no ORM save) so the transition guard and the
status-change audit hook are not triggered during migration.
"""

from __future__ import annotations

import frappe

# retired raw value -> canonical replacement
STATUS_MAP = {
	"Needs_Repair": "Awaiting_MR_Approval",
	"Pending_Repair": "Awaiting_MR_Approval",
	"In_Workshop": "Repair_In_Progress",
}


def execute():
	total = 0

	for old, new in STATUS_MAP.items():
		# Container master
		frappe.db.sql(
			"UPDATE `tabContainer` SET status=%s WHERE status=%s",
			(new, old),
		)
		# Container Movement audit trail (both ends)
		frappe.db.sql(
			"UPDATE `tabContainer Movement` SET to_status=%s WHERE to_status=%s",
			(new, old),
		)
		frappe.db.sql(
			"UPDATE `tabContainer Movement` SET from_status=%s WHERE from_status=%s",
			(new, old),
		)
		total += 1

	frappe.db.commit()
	print(f"[container_depot] canonicalize_container_status: remapped {total} retired status value(s).")
