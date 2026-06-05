"""Backfill the new ``containers`` child table on existing Orders.

Order Bongkar / Order Muat now carry 1..3 containers in a child table
(``Order Container Item``) with the legacy singular header fields kept as a
read-only row-1 mirror. This patch, for each legacy Order that has a header
``booking_code`` but no child rows yet:

1. sets the header ``booking`` link (resolved via the Booking Code), and
2. inserts ONE child row mirroring the legacy single container.

Child rows + ``booking`` are written directly (no parent re-save) so submitted
Orders stay valid. Idempotent: an Order that already has rows is skipped. The
controllers also fall back to a synthesized row for any un-backfilled Order, so
this patch is corrective rather than load-bearing.
"""

from __future__ import annotations

import frappe


def execute():
	for doctype in ("Order Bongkar", "Order Muat"):
		# Legacy single-container header fields. On a fresh install these columns
		# never existed, so there is nothing to backfill — skip safely.
		cols = frappe.db.get_table_columns(doctype)
		if "booking_code" not in cols:
			continue
		names = frappe.get_all(
			doctype,
			filters={"booking_code": ["is", "set"]},
			pluck="name",
		)
		for name in names:
			if frappe.db.count(
				"Order Container Item", {"parent": name, "parenttype": doctype}
			):
				continue
			row = frappe.db.get_value(
				doctype,
				name,
				["booking", "booking_code", "container", "container_no"],
				as_dict=True,
			)
			if not row or not row.booking_code:
				continue

			booking = row.booking or frappe.db.get_value(
				"Booking Code", row.booking_code, "booking"
			)
			if booking and not row.booking:
				frappe.db.set_value(doctype, name, "booking", booking, update_modified=False)

			child = {
				"doctype": "Order Container Item",
				"parent": name,
				"parenttype": doctype,
				"parentfield": "containers",
				"booking_code": row.booking_code,
				"container": row.container,
				"container_no": row.container_no,
			}
			if doctype == "Order Muat":
				child["cleaning_certificate"] = frappe.db.get_value(
					doctype, name, "cleaning_certificate"
				)
			frappe.get_doc(child).insert(ignore_permissions=True)

	frappe.db.commit()
