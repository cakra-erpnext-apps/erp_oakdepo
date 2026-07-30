"""Drop the legacy 'Release DO' doctype (+ its child + print format).

The standalone Release DO path — issue → mark "Picked Up" → flip Container to Gate_Out
directly — bypassed the whole outbound gate (EIR-Out "Ready To Load", Booking Code,
Order Muat, mark_gate_out). It is removed now; a new release concept will replace it later.
OAK keeps referencing the customer's OWN delivery order (Gate Out Plan.customer_do,
Container Booking.do_reference) — that is unaffected by this drop.

hapus total: no migration of old records. Runs on migrate so any site with the old table
is cleaned up too.
"""

import frappe


def execute():
	if frappe.db.exists("Print Format", "Release DO"):
		frappe.delete_doc("Print Format", "Release DO", force=True, ignore_missing=True)
	for dt in ("Release DO", "Release DO Item"):
		if frappe.db.exists("DocType", dt):
			# force: skip the link-integrity scan (nothing links to it — do_reference on the
			# booking is a free-form Data field, not a Link).
			frappe.delete_doc("DocType", dt, force=True, ignore_missing=True)
	# Drop the tables directly too: on a site where the on-disk sync already removed the
	# orphan DocType (folder gone), the guards above are skipped but the tables — with every
	# old record — would otherwise linger. DROP IF EXISTS is a no-op when clean.
	frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabRelease DO`")
	frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabRelease DO Item`")
	frappe.db.commit()
