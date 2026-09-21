"""Take the Amend flag off every Container Depot doctype that cannot be amended.

Frappe puts an **Amend** primary action on any cancelled document whose role holds the
`amend` permission. The action copies the document into a new draft stamped with
`amended_from` — and no Container Depot doctype has that field, so the button could only
ever answer `"amended_from" field must be present to do an amendment.` A cancelled booking
(`void_draft` marks drafts docstatus 2) was the everyday way to meet it.

The flag was seeded by `install.setup_permissions`, which now strips it for a doctype with
no `amended_from` (see `_ensure_docperm`). That seeder is add-only, so the rows already
written need this.

Undoing work in this app is each doctype's own reopen flow — Kembali ke Draft on a booking,
void + reissue on a bon — not a second document claiming to replace the first. Add an
`amended_from` field to a doctype and the next migrate hands its roles Amend back.
"""

from __future__ import annotations

import frappe


def execute():
	doctypes = frappe.get_all(
		"DocType", filters={"module": "Container Depot", "istable": 0}, pluck="name"
	)
	for doctype in doctypes:
		if frappe.get_meta(doctype).get_field("amended_from"):
			continue
		rows = frappe.get_all(
			"Custom DocPerm", filters={"parent": doctype, "amend": 1}, pluck="name"
		)
		for row in rows:
			frappe.db.set_value("Custom DocPerm", row, "amend", 0, update_modified=False)
		if rows:
			frappe.clear_cache(doctype=doctype)
