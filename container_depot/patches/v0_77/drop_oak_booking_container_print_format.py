"""Remove the ``OAK Booking Container`` print format.

It was the single booking print: booking detail *and* the per-container Booking Code
gate pass on one sheet. That is two documents with two audiences, so it was split —
``OAK Booking Confirmation`` (the customer's copy, no gate pass) and ``OAK Booking
Voucher`` (one page per container, QR large enough to scan across a gatehouse counter).
Keeping the old format alongside them only offers an operator a third choice that
prints a customer the driver's credentials.

The on-disk folder is gone, and that alone is what makes this a patch: for a standard
print format Frappe renders from the file and only falls back to the ``html`` field,
which is empty here. So a leftover DB record does not merely linger in the dropdown —
picking it throws ``TemplateNotFoundError``.

Idempotent: a no-op once the record is gone.
"""

from __future__ import annotations

import frappe

PRINT_FORMAT = "OAK Booking Container"
REPLACEMENT = "OAK Booking Confirmation"


def execute():
	if not frappe.db.exists("Print Format", PRINT_FORMAT):
		return

	# Anything still pointing at it would break on its next print, so move those over
	# to the confirmation rather than leaving a dangling link behind.
	if frappe.db.get_value("Property Setter", {"doc_type": "Container Booking", "property": "default_print_format"}, "value") == PRINT_FORMAT:
		frappe.db.set_value(
			"Property Setter",
			{"doc_type": "Container Booking", "property": "default_print_format"},
			"value",
			REPLACEMENT,
		)
	frappe.db.set_value("DocType", "Container Booking", "default_print_format", REPLACEMENT, update_modified=False)

	frappe.delete_doc("Print Format", PRINT_FORMAT, force=True, ignore_permissions=True)
	frappe.clear_cache(doctype="Container Booking")
