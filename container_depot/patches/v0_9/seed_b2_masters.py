"""Seed B2 reference masters and keep the shipping_line Data->Link conversion safe.

* Seeds the common shipping lines OAK works with.
* Backfills Shipping Line records for any distinct value already stored in
  ``Isotank Booking.shipping_line`` (which was a free-text Data field before B2),
  so the field's new Link target is always valid.

Idempotent: existing rows are skipped.
"""

from __future__ import annotations

import frappe

SHIPPING_LINES = [
	"Maersk",
	"MSC",
	"CMA CGM",
	"Evergreen",
	"COSCO",
	"ONE",
	"Hapag-Lloyd",
	"PIL",
	"Yang Ming",
]


def execute():
	seeded = 0

	def ensure(name):
		nonlocal seeded
		name = (name or "").strip()
		if not name or frappe.db.exists("Shipping Line", name):
			return
		frappe.get_doc({
			"doctype": "Shipping Line",
			"shipping_line_name": name,
			"is_active": 1,
		}).insert(ignore_permissions=True)
		seeded += 1

	for name in SHIPPING_LINES:
		ensure(name)

	# Backfill any distinct value already present on bookings.
	if frappe.db.has_column("Isotank Booking", "shipping_line"):
		existing = frappe.db.sql(
			"SELECT DISTINCT shipping_line FROM `tabIsotank Booking` "
			"WHERE shipping_line IS NOT NULL AND shipping_line != ''"
		)
		for (val,) in existing:
			ensure(val)

	frappe.db.commit()
	print(f"[container_depot] seed_b2_masters: ensured {seeded} Shipping Line(s).")
