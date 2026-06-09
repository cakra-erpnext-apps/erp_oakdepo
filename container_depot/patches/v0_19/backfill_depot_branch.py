"""Post-sync backfills for the Tank In booking reshape.

* Default each Container Booking Item's new ``cargo`` to "Empty Clean".
* Fill the now-required ``Depot.branch`` from the sole Branch when unambiguous (a
  single Branch lets us assign every depot automatically; otherwise leave it for
  manual entry — a required field only blocks on the next save, not existing rows).

Runs post_model_sync so the new columns exist. Idempotent.
"""

import frappe


def execute():
	if frappe.db.has_column("Container Booking Item", "cargo") and frappe.db.exists("Cargo", "Empty Clean"):
		frappe.db.sql("UPDATE `tabContainer Booking Item` SET `cargo`='Empty Clean' WHERE `cargo` IS NULL OR `cargo`=''")

	if frappe.db.has_column("Depot", "branch"):
		branches = frappe.get_all("Branch", pluck="name", limit=2)
		if len(branches) == 1:
			frappe.db.sql("UPDATE `tabDepot` SET `branch`=%s WHERE `branch` IS NULL OR `branch`=''", branches[0])

	frappe.db.commit()
