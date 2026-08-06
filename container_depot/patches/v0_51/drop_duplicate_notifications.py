"""Delete the five built-in Notifications that duplicated our own depot events.

``install.setup_document_notifications`` used to seed one Frappe ``Notification`` per key
document event. Each of those events is ALSO raised by ``operations.notify``, so every
submit produced two bell rows for the same fact — three for an Order Muat, which raises
both the bon notification and the EIR-Out follow-up. People stop reading a bell that
repeats itself.

Routing moved to ``Depot Notification Rule`` (one row per event, editable in Desk without
a deploy), and the seeder is now a no-op. This removes the leftovers from sites that
already ran it.

Deliberately narrow: only a Notification whose ``document_type`` AND ``subject`` match a
seeded pair exactly is deleted, and only when ``is_standard = 0``. An admin who wrote
their own rule on the same doctype keeps it. Idempotent — a second run finds nothing.
"""

import frappe

# (document_type, subject) exactly as install.setup_document_notifications wrote them.
_SEEDED = [
	("Order Bongkar", "Bon Bongkar {{ doc.name }} diterbitkan"),
	("Order Muat", "Bon Muat {{ doc.name }} diterbitkan"),
	("Depot Contract", "Kontrak Depo {{ doc.name }} dibuat"),
	("Container Booking", "Booking {{ doc.name }} dikonfirmasi"),
	("Inspection", "EIR {{ doc.name }} disubmit"),
]


def execute():
	deleted = []
	for doctype, subject in _SEEDED:
		for name in frappe.get_all(
			"Notification",
			filters={"document_type": doctype, "subject": subject, "is_standard": 0},
			pluck="name",
		):
			frappe.delete_doc("Notification", name, force=True, ignore_permissions=True)
			deleted.append(f"{doctype}: {subject}")

	if deleted:
		frappe.db.commit()
		print(f"drop_duplicate_notifications: removed {len(deleted)} duplicate Notification(s)")
		for row in deleted:
			print(f"  - {row}")
	else:
		print("drop_duplicate_notifications: nothing to remove")
