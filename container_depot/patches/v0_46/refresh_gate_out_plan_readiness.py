"""Re-derive the stored Kesiapan of every Open Gate Out Plan.

The readiness figures (``is_ready`` / ``readiness`` / ``readiness_summary``) were only ever
written when the plan document itself was saved, so a plan went stale the moment one of its
tanks finished cleaning or repair — GOP-2026-00026 read "Belum: Cleaning, M&R" while its
cleaning order had already been Completed. ``hooks.doc_events`` keeps them current from now
on; this repairs the plans that were already wrong.

Only Open plans: a closed plan's numbers are a record of how it closed.
"""

import frappe


def execute():
	if not frappe.db.table_exists("Gate Out Plan"):
		return

	from container_depot.operations.doctype.gate_out_plan.gate_out_plan import (
		ACTIVE_STATUS,
		refresh_plan_readiness,
	)

	for plan in frappe.get_all("Gate Out Plan", filters={"status": ACTIVE_STATUS}, pluck="name"):
		refresh_plan_readiness(plan)
