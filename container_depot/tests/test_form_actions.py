"""Duplicate is off on every order.

An order is not a template. Each one records a job that some OTHER document raised: a bon
spends single-use Booking Codes, a Cleaning / Repair Order is opened by an EIR follow-up, a
Survey Order by an outbound booking. So a copy is never the same kind of thing as the
original — what Duplicate actually produces is an orphan, a second draft carrying the
first one's links, sitting outside the flow that should have created it and looking exactly
like real work to every worklist that counts it.

Frappe's switch is the DocType flag ``allow_copy``, and its name reads backwards: the field
is LABELLED "Hide Copy", and 1 means the menu item is never added at all (see
``add_duplicate`` in ``frappe/public/js/frappe/form/toolbar.js`` — the only place in Frappe
that reads the flag). One flag is the whole mechanism, so this test is the whole guard: it
is what catches the day a doctype is re-exported, or customised through Customize Form,
with the box quietly cleared.

``frappe.get_meta`` is deliberate — it applies Property Setters, so a Customize Form
override that re-enables Duplicate fails here too, which reading the JSON would not catch.

Read-only: doctype configuration, not fixtures. Nothing here creates or deletes a row.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

# Every doctype in this app that IS an order. Container Booking is deliberately absent: a
# booking is the REQUEST, not the job, and repeating one for the same customer next month is
# ordinary work rather than an orphan.
ORDER_DOCTYPES = (
	"Order Bongkar",
	"Order Muat",
	"Cleaning Order",
	"Repair Order",
	"Survey Order",
)


class TestOrdersCannotBeDuplicated(FrappeTestCase):
	def test_every_order_hides_the_duplicate_action(self):
		offenders = [dt for dt in ORDER_DOCTYPES if not frappe.get_meta(dt).allow_copy]
		self.assertEqual(
			offenders,
			[],
			"Duplicate is still offered on: "
			+ ", ".join(offenders)
			+ " — set `allow_copy: 1` (Frappe's 'Hide Copy') in the doctype JSON.",
		)
