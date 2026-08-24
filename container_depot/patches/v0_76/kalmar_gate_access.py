"""Give Team Kalmar `create` (and write) on Order Bongkar so the Gate tile opens for them.

`install.FIELD_ROLE_MATRIX` now grants rwc, but `setup_permissions` is add-only per
(doctype, role) — an existing row belongs to the admin — so a site carrying the old `r` row
would never pick the change up. Same shape as `v0_57.spv_order_muat_create`.

Why it matters beyond the tile: Kalmar is routed the two gate events (`order_gate_out`,
`gate_out`) and the PWA menu gate keys on create over Order Bongkar (`ess.context._MENU`),
so without this they received bells that answered "Anda tidak punya akses ke menu ini".
"""

import frappe

ROLE = "Team Kalmar"
DOCTYPE = "Order Bongkar"


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		return
	name = frappe.db.get_value("Custom DocPerm", {"parent": DOCTYPE, "role": ROLE})
	if not name:
		return  # fresh site: setup_permissions seeds it with create already set
	missing = {
		flag: 1
		for flag in ("write", "create")
		if not frappe.db.get_value("Custom DocPerm", name, flag)
	}
	if not missing:
		return
	frappe.db.set_value("Custom DocPerm", name, missing, update_modified=False)
	frappe.clear_cache()
	print(f"Granted {'/'.join(missing)} on {DOCTYPE} to {ROLE}")
