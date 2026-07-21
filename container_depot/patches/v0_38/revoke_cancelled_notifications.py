"""Sweep the feed entries left behind by documents that were voided before
``notify.revoke`` existed.

Cancelling never cleared its notifications, so every cancelled booking / bon is
still sitting in the bell as work to do. Clear them once here; the ``on_cancel``
doc_events keep it clean from now on. Rows pointing at a document that no longer
exists go too — clicking one only leads to a 404.

Only ``Alert`` rows are touched: Assignment / Mention / Share belong to Frappe and
have their own lifecycle.
"""

import frappe

from container_depot.operations.notify import REVOCABLE_DOCTYPES


def execute():
	for doctype in REVOCABLE_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		flagged = frappe.get_all(
			"Notification Log",
			filters={"document_type": doctype, "type": "Alert"},
			pluck="document_name",
			distinct=True,
		)
		flagged = [n for n in flagged if n]
		if not flagged:
			continue
		live = set(
			frappe.get_all(
				doctype,
				filters={"name": ("in", flagged), "docstatus": ("<", 2)},
				pluck="name",
			)
		)
		# Anything the document table no longer vouches for: cancelled, or gone.
		stale = [n for n in flagged if n not in live]
		if stale:
			frappe.db.delete(
				"Notification Log",
				{"document_type": doctype, "document_name": ("in", stale), "type": "Alert"},
			)
			print(f"revoked {len(stale)} stale {doctype} notification(s)")
