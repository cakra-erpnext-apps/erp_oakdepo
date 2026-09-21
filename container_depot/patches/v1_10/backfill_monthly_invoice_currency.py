"""Stamp the currency on OAK Monthly Invoices raised before they had one.

The monthly scheduler now raises one invoice per (customer, period, category, CURRENCY) —
an order prices each of its rows in the currency that row's tariff line states, and a Sales
Invoice can only be raised in one. Every invoice written before that ran in the company
default by implication, and its ``subtotal`` / ``ppn`` / ``total`` are now formatted against
the new field: left NULL they would render with no currency at all, and the uniqueness guard
(which counts currency as part of the key) would let a duplicate through for the same period.

Backfilled to the company default rather than to each customer's contract currency: that is
what these documents were actually billed in, whatever the contract says today.
"""

import frappe


def execute():
	default = (
		frappe.defaults.get_global_default("currency")
		or frappe.db.get_default("currency")
		or "IDR"
	)
	frappe.db.sql(
		"UPDATE `tabOAK Monthly Invoice` SET currency = %s WHERE currency IS NULL OR currency = ''",
		default,
	)
