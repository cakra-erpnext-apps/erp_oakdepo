"""Repair Order's revision request now uses the same fields as every other menu.

``reopen_requested`` / ``reopen_note`` become ``revision_requested`` / ``revision_note`` (see
``container_depot/revision.py``), so a request raised before the rename is still on the
order — and still on the Desk list as "Revisi Diminta" — after it.
"""

import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	for old, new in (("reopen_requested", "revision_requested"), ("reopen_note", "revision_note")):
		if frappe.db.has_column("Repair Order", old):
			rename_field("Repair Order", old, new)
