"""Let a customer account raise its own Container Booking.

The customer role was read-only everywhere (`install.OFFICE_ROLE_MATRIX`). It now holds
create / write / cancel on `Container Booking` — the one thing a portal account DOES rather
than reads — and read on `Depot`, the master it has to pick while doing it.

The flags alone grant nothing loose: `customer_scope.container_booking_permission` holds all
three to a booking the account owns, still at `Draft`, still unsubmitted. `submit` is not
among them; confirming a booking stays OAK's decision.

The permission seeder is add-only — an existing (doctype, role) row belongs to the admin —
so the flags on a row that already exists have to be set here. Idempotent.
"""

from __future__ import annotations

import frappe

from container_depot.install import CUSTOMER_DESK_ROLE, setup_permissions

SET = {
	# `cancel` reaches `container_booking.void_draft`, which is the only undo a draft has
	# (a booking is never deleted — `on_trash` refuses).
	"Container Booking": {"create": 1, "write": 1, "cancel": 1},
}


def execute():
	# Picks up (Depot, Customer Desk), which has no row yet.
	setup_permissions()

	for doctype, flags in SET.items():
		name = frappe.db.get_value(
			"Custom DocPerm", {"parent": doctype, "role": CUSTOMER_DESK_ROLE}, "name"
		)
		if name:
			frappe.db.set_value("Custom DocPerm", name, flags, update_modified=False)

	frappe.clear_cache()
	frappe.db.commit()
