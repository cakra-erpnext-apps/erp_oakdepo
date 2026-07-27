"""Remove doctypes that were built but never wired into any active flow.

Menu cleanup (2026-07-27): these carried no active code path, no PWA surface,
and no real data — leftovers from abandoned/demo features:

  * Container Leasing / Container Leasing History — leasing feature never built out.
  * Equipment Maintenance / Fuel Log — yard-equipment demo, only ever in seed/tests.
  * Survey Request — thin duplicate of the (kept) Survey Order billing flow.

Also drops the now-orphan ``equipment`` column on Container Movement (its Link
pointed at the removed Equipment Maintenance). ``Container Position Survey`` is
deliberately KEPT — it is the next feature to be developed.

Idempotent. Mirrors v0_40: migrate's orphan-removal deletes the DocType record
before this patch runs, so we drop the tables by name too.
"""

from __future__ import annotations

import frappe

DOCTYPES = [
	"Container Leasing History",  # child/history first
	"Container Leasing",
	"Equipment Maintenance",
	"Fuel Log",
	"Survey Request",
]


def execute():
	for dt in DOCTYPES:
		for name in frappe.get_all("Custom DocPerm", filters={"parent": dt}, pluck="name"):
			frappe.delete_doc("Custom DocPerm", name, force=True, ignore_permissions=True)
		if frappe.db.exists("DocType", dt):
			frappe.delete_doc("DocType", dt, force=True, ignore_permissions=True)
		if frappe.db.table_exists(dt):
			frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{dt}`")

	# Orphan column left behind after the Container Movement.equipment Link was removed.
	if frappe.db.table_exists("Container Movement") and "equipment" in frappe.db.get_table_columns(
		"Container Movement"
	):
		frappe.db.sql_ddl("ALTER TABLE `tabContainer Movement` DROP COLUMN `equipment`")

	frappe.db.commit()
