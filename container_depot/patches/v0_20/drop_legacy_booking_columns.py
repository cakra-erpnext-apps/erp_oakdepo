"""Drop legacy / orphan columns from Container Booking and its item table.

These columns are no longer declared on either DocType. Frappe never auto-drops a
removed field's column, so they linger as orphans in the database:

* ``tabContainer Booking``: ``tank_principal``, ``shipping_line``, ``ownership`` —
  superseded by ``principal`` (Tank Owner) in the Tank In / Lift Off reshape.
* ``tabContainer Booking Item``: ``status_tag`` — the Clean/Dirty gate tag is now
  derived from ``condition`` at booking-code issuance (``status_tag_for_condition``)
  rather than stored on the line.

Runs pre_model_sync, after ``v0_19.reshape_container_booking`` (whose condition
migration still reads ``status_tag``). Idempotent — DROP COLUMN IF EXISTS.

NOTE: ``docstatus`` and ``idx`` are Frappe framework columns present on every table
(submit state and row order) — intentionally NOT touched.
"""

import frappe

PARENT = "tabContainer Booking"
ITEM = "tabContainer Booking Item"
PARENT_DROP = ("tank_principal", "shipping_line", "ownership")
ITEM_DROP = ("status_tag",)


def execute():
	if frappe.db.table_exists("Container Booking"):
		for col in PARENT_DROP:
			frappe.db.sql_ddl(f"ALTER TABLE `{PARENT}` DROP COLUMN IF EXISTS `{col}`")
	if frappe.db.table_exists("Container Booking Item"):
		for col in ITEM_DROP:
			frappe.db.sql_ddl(f"ALTER TABLE `{ITEM}` DROP COLUMN IF EXISTS `{col}`")
	frappe.db.commit()
