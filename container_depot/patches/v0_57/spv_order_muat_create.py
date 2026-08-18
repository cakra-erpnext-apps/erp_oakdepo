"""Give SPV Lapangan `create` on Order Muat so the yard can issue a bon Muat.

`install.FIELD_ROLE_MATRIX` now grants it, but `setup_permissions` is add-only per
(doctype, role) — an existing row belongs to the admin — so a site that already carries the
old `rw` row would never pick the change up. This flips that one flag once.

The companion grant (SPV read on Container Booking) needs no patch: no row exists for that
pair, so the seeder inserts it on this same migrate.

Narrow on purpose: one role, one doctype, one flag. Security's read-only Order Muat is the
deliberate half of the asymmetry (see api._require_order_create) and is left alone.
"""

import frappe

ROLE = "SPV Lapangan"
DOCTYPE = "Order Muat"


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		return
	name = frappe.db.get_value("Custom DocPerm", {"parent": DOCTYPE, "role": ROLE})
	if not name:
		return  # fresh site: setup_permissions seeds it with create already set
	if frappe.db.get_value("Custom DocPerm", name, "create"):
		return
	frappe.db.set_value("Custom DocPerm", name, "create", 1, update_modified=False)
	frappe.clear_cache()
	print(f"Granted create on {DOCTYPE} to {ROLE}")
