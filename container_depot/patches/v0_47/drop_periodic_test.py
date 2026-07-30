"""Drop the legacy 'Periodic Test' doctype.

The periodic-test flow was consolidated into two places (see operations/periodic.py):
  * Container.next_pt_due  — the scheduling state / single source of truth (reminder cron
    + dashboard KPI read it here now);
  * Periodic Test Order    — the M&R-style work / billing / history record.

Per the consolidation decision the old records are dropped entirely (no migration): the menu
was new and carried no history worth keeping. This runs on migrate, so it also cleans up any
site that still has the old table.
"""

import frappe


def execute():
	# ToDos the old reminder opened against the deleted doctype would dangle otherwise.
	if frappe.db.table_exists("ToDo"):
		frappe.db.delete("ToDo", {"reference_type": "Periodic Test"})
	if frappe.db.exists("DocType", "Periodic Test"):
		# force: skip the link-integrity scan (nothing references it anymore).
		frappe.delete_doc("DocType", "Periodic Test", force=True, ignore_missing=True)
	# Drop the table directly too: on a site where the on-disk sync already removed the
	# orphan DocType (its folder is gone), the guard above is skipped but `tabPeriodic Test`
	# — with every old record — would otherwise linger. DROP IF EXISTS is a no-op when clean.
	frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabPeriodic Test`")
	frappe.db.commit()
