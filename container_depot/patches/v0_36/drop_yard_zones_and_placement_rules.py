"""Phase 2 status/zone refactor — remove the orphaned yard-placement DocTypes.

The depot no longer maps tanks to yard zones (presence-based status only). The
``Yard Zone`` / ``Yard Placement Rule`` / ``Yard Placement Rule Category`` DocTypes
and the ``yard_utilization_location`` Report were deleted from the app; this patch
drops the leftover DocType definitions + data tables so migrate leaves no orphans.

The Container position columns (``yard_zone`` / ``current_location`` / ``row`` /
``bay`` / ``tier``) are intentionally KEPT as unused columns — old Container
Movement rows still reference them and dropping them is a separate, riskier step.

Idempotent + best-effort: each target is guarded by an existence check and a
try/except, so a partial prior run or a fresh install (nothing to drop) both pass.
"""

from __future__ import annotations

import frappe

# Child tables first (Yard Placement Rule Category is a child of Yard Placement Rule).
_DOCTYPES = [
	"Yard Placement Rule Category",
	"Yard Placement Rule",
	"Yard Zone",
]
_REPORTS = ["Yard Utilization Location"]
# Desk chart (seeded by install.py) that grouped containers by yard_zone.
_CHARTS = ["Tanks by Yard Zone"]


def execute():
	for report in _REPORTS:
		if frappe.db.exists("Report", report):
			try:
				frappe.delete_doc("Report", report, force=True, ignore_permissions=True)
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"drop report {report}")

	for chart in _CHARTS:
		if frappe.db.exists("Dashboard Chart", chart):
			try:
				frappe.delete_doc("Dashboard Chart", chart, force=True, ignore_permissions=True)
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"drop chart {chart}")

	for dt in _DOCTYPES:
		if not frappe.db.exists("DocType", dt):
			continue
		try:
			# Remove the DocType definition; force + delete the physical table too.
			frappe.delete_doc("DocType", dt, force=True, ignore_permissions=True)
			frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{dt}`")
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"drop doctype {dt}")

	frappe.db.commit()
	print("[container_depot] v0_36: dropped yard zone / placement-rule doctypes + report.")
