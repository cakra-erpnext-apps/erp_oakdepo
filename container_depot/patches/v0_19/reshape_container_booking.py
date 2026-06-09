"""Reshape Container Booking for the Tank In / Lift Off flow.

Drops the columns retired from the booking and its item table (Frappe never
auto-drops a removed field's column), migrates the item ``condition`` from the old
Empty/Laden + ``status_tag`` pair to the new EMPTY CLEAN / EMPTY DIRTY / LADEN value,
and defaults legacy rows' ``direction`` to Tank In.

Runs pre_model_sync so the drops happen before the schema reconcile; the condition
rewrite reads ``status_tag`` (a kept column) and only touches existing columns. The
new columns (``cargo``, ``branch`` …) are backfilled post-sync in
``v0_19.backfill_depot_branch``. Idempotent.
"""

import frappe

ITEM = "tabContainer Booking Item"
PARENT = "tabContainer Booking"
ITEM_DROP = ("container_type", "item_status", "shipper", "ex_vessel", "angkutan", "gate_in", "gate_out", "eir")
PARENT_DROP = ("job_reference_no", "agent")


def execute():
	if frappe.db.table_exists("Container Booking Item"):
		# Condition migration first — it depends on status_tag (kept) and condition (kept).
		frappe.db.sql(f"UPDATE `{ITEM}` SET `condition`='LADEN' WHERE `condition`='Laden'")
		frappe.db.sql(f"UPDATE `{ITEM}` SET `condition`='EMPTY CLEAN' WHERE `condition`='Empty' AND `status_tag`='Clean'")
		frappe.db.sql(f"UPDATE `{ITEM}` SET `condition`='EMPTY DIRTY' WHERE `condition`='Empty'")
		frappe.db.sql(f"UPDATE `{ITEM}` SET `condition`='EMPTY CLEAN' WHERE `condition` IS NULL OR `condition`=''")
		for col in ITEM_DROP:
			frappe.db.sql_ddl(f"ALTER TABLE `{ITEM}` DROP COLUMN IF EXISTS `{col}`")

	if frappe.db.table_exists("Container Booking"):
		frappe.db.sql(f"UPDATE `{PARENT}` SET `direction`='Tank In' WHERE `direction` IS NULL OR `direction`=''")
		for col in PARENT_DROP:
			frappe.db.sql_ddl(f"ALTER TABLE `{PARENT}` DROP COLUMN IF EXISTS `{col}`")

	frappe.db.commit()
