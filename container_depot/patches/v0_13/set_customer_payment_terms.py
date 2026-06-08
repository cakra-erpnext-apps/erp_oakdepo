"""Backfill each Customer's default Payment Terms Template from the Cash-vs-Termin
mode already recorded on their Active Depot Contract.

The mode source of truth that exists today is ``Depot Contract.payment_type``
(``Cash`` / ``TOP``). We map it onto the ERPNext-native ``Customer.payment_terms``
default so new Sales Invoices inherit the right terms automatically — and remain
overridable per invoice.

Idempotent + non-destructive: only customers whose ``payment_terms`` is still
empty are touched, so manual owner edits and re-runs are preserved. New customers
onboarded later get their default set the ERPNext-native way (on the Customer
form), or by re-running this patch.

Depends on container_depot.install.ensure_payment_terms_templates having created
the templates (runs in after_migrate before patches via the standard migrate
order; we also guard on template existence).
"""

from __future__ import annotations

import frappe

# Owner-editable mapping: Depot Contract payment_type -> Payment Terms Template.
# Adjust here (one place) if a principal's basis changes.
CONTRACT_TYPE_TO_TERMS = {
	"TOP": "End of Following Month",
	"Cash": "Immediate",
}


def backfill() -> int:
	"""Set ``Customer.payment_terms`` from the Active Depot Contract mode.

	Returns the number of customers updated. Does NOT commit — callers decide
	(``execute`` commits; tests run inside the test transaction). Non-destructive:
	skips customers that already have a default set.
	"""
	updated = 0
	for payment_type, template in CONTRACT_TYPE_TO_TERMS.items():
		if not frappe.db.exists("Payment Terms Template", template):
			print(f"[container_depot] set_customer_payment_terms: missing template '{template}'; skipped {payment_type}.")
			continue
		customers = frappe.get_all(
			"Depot Contract",
			filters={"status": "Active", "payment_type": payment_type},
			pluck="customer",
		)
		for customer in {c for c in customers if c}:
			# Never clobber an existing choice (manual override or earlier run).
			if frappe.db.get_value("Customer", customer, "payment_terms"):
				continue
			frappe.db.set_value(
				"Customer", customer, "payment_terms", template, update_modified=False
			)
			updated += 1
	return updated


def execute():
	# Patches run before after_migrate hooks, so don't rely on the hook having
	# seeded the templates yet — ensure them here (idempotent).
	from container_depot.install import ensure_payment_terms_templates

	ensure_payment_terms_templates()
	backfill()
	frappe.db.commit()
