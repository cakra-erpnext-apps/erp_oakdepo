"""Drop ``Cleaning Order.currency_locked``. Nothing locks the cleaning currency any more.

The flag said "this owner's currency comes from a binding rate card", and the row's Currency
column was read-only whenever it was on. That is the wrong rule for a depot: a rate card
states the currency an owner NORMALLY pays in, not the only one an invoice may be raised in,
and a one-off quoted in another currency then had to be corrected on the invoice instead of
typed where the work was recorded. The contract currency is now a SEED — filled in when a row
has none, never re-applied — so the flag drives nothing and has no reader left
(Container Booking and the M&R keep their own; this patch is only about cleaning).

Dropping a field from a doctype JSON leaves its column behind, and a Property Setter or
Custom Field on it would outlive the field and break form load with "Could not find Field".
"""

import frappe

DOCTYPE = "Cleaning Order"
FIELD = "currency_locked"


def execute():
	frappe.db.delete("Property Setter", {"doc_type": DOCTYPE, "field_name": FIELD})
	frappe.db.delete("Custom Field", {"dt": DOCTYPE, "fieldname": FIELD})
	if frappe.db.has_column(DOCTYPE, FIELD):
		frappe.db.sql_ddl(f"ALTER TABLE `tab{DOCTYPE}` DROP COLUMN `{FIELD}`")
	frappe.clear_cache(doctype=DOCTYPE)
