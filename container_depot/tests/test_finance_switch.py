"""The finance master switch: the depot runs with invoicing off.

Two halves are asserted here, and they are the whole point of the switch:

1. **Nothing financial is created or blocks anything.** No Sales Invoice is raised on any
   path, and the three places money can stop an operation — a Cash booking's submit, the
   gate's ``cash_unpaid``, generating a bon — step aside. A Cash booking goes straight to
   Confirmed and its gate codes are issued.
2. **Everything else is untouched.** Charges are still priced and stored, so the work can
   be billed later; invoices raised while finance was on keep their links and keep syncing.
   Switching finance off is not a way to void receivables.

See ``container_depot.finance``.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, cint, flt, today

from container_depot import finance, invoicing
from container_depot.api import _booking_gate_detail
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_cash_gate import _ensure_test_depot
from container_depot.tests.test_container_booking import (
	_cleanup_customer_world,
	_make_active_contract,
)


def _set_finance(enabled: bool, start_date=None):
	"""Flip the switch the way the settings form does, cache included."""
	doc = frappe.get_single(finance.SETTINGS)
	doc.enable_finance = 1 if enabled else 0
	doc.finance_start_date = start_date
	doc.save(ignore_permissions=True)
	finance.clear_cache()


class TestFinanceSwitch(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		_ensure_test_depot()
		self.customer = ensure_test_customer("Finance Switch Co")
		_cleanup_customer_world(self.customer)
		self.contract = _make_active_contract(self.customer, payment_type="Cash")
		finance.clear_cache()
		self._before = (
			frappe.db.get_single_value(finance.SETTINGS, "enable_finance", cache=False),
			frappe.db.get_single_value(finance.SETTINGS, "finance_start_date", cache=False),
		)
		# ERPNext auto-inserts a missing Item Price when an invoice line prices an item the
		# selling list doesn't carry (Stock Settings). The consolidated run bills onto the
		# SITE default list, so sweeping one booking quietly adds a rate there — which then
		# prices every later test's walk-in. Snapshot so tearDown drops exactly ours.
		self._item_prices_before = set(frappe.get_all("Item Price", pluck="name"))

	def tearDown(self):
		_cleanup_customer_world(self.customer)
		frappe.db.rollback()
		# Restore the switch explicitly rather than leaning on the rollback: these tests
		# submit bookings, and a commit anywhere in that path would otherwise leave the
		# site — and every later test — running with finance off.
		enabled, start = self._before
		frappe.db.set_single_value(finance.SETTINGS, "enable_finance", cint(enabled))
		frappe.db.set_single_value(finance.SETTINGS, "finance_start_date", start)
		leaked = set(frappe.get_all("Item Price", pluck="name")) - self._item_prices_before
		if leaked:
			frappe.db.delete("Item Price", {"name": ("in", list(leaked))})
		frappe.db.commit()
		finance.clear_cache()

	def _booking(self, container_no):
		return frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"contract": self.contract,
			"do_reference": "DO-FINSWITCH",
			"charges": [{"item": "Lift Off"}],
			"items": [{"container_no": container_no}],
		}).insert(ignore_permissions=True)

	# --- the default ----------------------------------------------------------
	def test_defaults_to_on_when_never_configured(self):
		"""An app update must never switch a running site's invoicing off.

		Frappe casts an unsaved Check to 0, so "nobody has ever touched this" looks exactly
		like "somebody turned it off" — only a stored 0 may count as the latter. Asserted by
		removing the stored row, not by reading whatever this site happens to be set to.
		"""
		frappe.db.delete("Singles", {"doctype": finance.SETTINGS, "field": "enable_finance"})
		finance.clear_cache()
		self.assertTrue(finance.is_enabled())

	# --- nothing is created ---------------------------------------------------
	def test_no_invoice_is_raised_on_any_path(self):
		_set_finance(False)
		si = invoicing.create_draft_sales_invoice(
			self.customer, [{"item_code": "Lift Off", "qty": 1, "rate": 250000}]
		)
		self.assertIsNone(si, "the one invoice factory must refuse while finance is off")

	def test_billing_actions_say_why_they_did_nothing(self):
		"""Buttons pressed *to bill something* must explain, not fail quietly."""
		from container_depot.consolidated_billing import bill_customer
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			generate_invoice,
		)

		b = self._booking("FINSW0001")
		_set_finance(False)
		with self.assertRaises(frappe.ValidationError):
			generate_invoice(b.name)
		with self.assertRaises(frappe.ValidationError):
			bill_customer(self.customer)

	def test_monthly_scheduler_is_a_no_op(self):
		"""It runs unattended at 02:00 — it must return, not raise."""
		from container_depot.monthly_invoicing import generate_monthly_invoices

		_set_finance(False)
		self.assertEqual(generate_monthly_invoices(), 0)

	# --- nothing is blocked ---------------------------------------------------
	def test_cash_booking_confirms_without_an_invoice(self):
		"""The core of it: with no invoice to pay, waiting for payment would strand every
		Cash booking in Pending Payment forever."""
		_set_finance(False)
		b = self._booking("FINSW0002")
		b.flags.ignore_permissions = True
		b.submit()
		b.reload()
		self.assertEqual(b.docstatus, 1)
		self.assertEqual(b.booking_status, "Confirmed")
		self.assertIsNone(b.sales_invoice)
		# Confirmation still issues the gate codes — the operational half is unaffected.
		self.assertTrue(frappe.get_all("Booking Code", filters={"booking": b.name}, pluck="name"))

	def test_gate_is_never_blocked_for_payment(self):
		_set_finance(False)
		b = self._booking("FINSW0003")
		detail = _booking_gate_detail(b.name)
		# Still not submitted, so still blocked — but never *because of money*.
		self.assertNotEqual(detail["block_reason"], "cash_unpaid")
		b.flags.ignore_permissions = True
		b.submit()
		self.assertIsNone(_booking_gate_detail(b.name)["block_reason"])

	def test_charges_are_still_priced_and_recorded(self):
		"""Operations now, invoices later — only possible if the money is still on record."""
		_set_finance(False)
		b = self._booking("FINSW0004")
		self.assertEqual(len(b.charges), 1)
		self.assertGreater(flt(b.charges_total), 0, "the rate must still resolve from the price list")

	# --- existing invoices are safe -------------------------------------------
	def test_switching_off_leaves_a_live_invoice_alone(self):
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			generate_invoice,
			rollback_to_draft,
		)

		_set_finance(True)  # this site may itself be running operations-only
		b = self._booking("FINSW0005")
		generate_invoice(b.name)
		b.reload()
		si = b.sales_invoice
		self.assertTrue(si)

		_set_finance(False)
		b.reload()
		self.assertEqual(b.sales_invoice, si, "the link must survive the switch")
		self.assertTrue(frappe.db.exists("Sales Invoice", si))
		# And the way back out still works: rollback is cleanup of an existing document,
		# not the creation of a new one, so the switch must not stand in its way.
		rollback_to_draft(b.name)
		b.reload()
		self.assertEqual(b.booking_status, "Draft")
		self.assertIsNone(b.sales_invoice)

	# --- turning it back on ---------------------------------------------------
	def test_start_date_floors_the_backlog_sweep(self):
		"""Without a floor, switching finance on after months of operating would bill the
		entire history in one click."""
		from container_depot.consolidated_billing import bill_customer

		_cleanup_customer_world(self.customer)
		contract = _make_active_contract(
			self.customer, payment_type="TOP", payment_terms="NET 30", credit_limit=1_000_000_000
		)
		b = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"contract": contract,
			"do_reference": "DO-FINSWITCH-TOP",
			"payment_type": "TOP",
			"charges": [{"item": "Lift Off"}],
			"items": [{"container_no": "FINSW0006"}],
		}).insert(ignore_permissions=True)
		b.flags.ignore_permissions = True
		b.submit()

		# Billing starts tomorrow: today's booking is behind the line and is left alone.
		_set_finance(True, start_date=add_days(today(), 1))
		self.assertEqual(bill_customer(self.customer), [])
		b.reload()
		self.assertIsNone(b.sales_invoice)

		# Move the line back and the same booking is swept.
		_set_finance(True, start_date=today())
		self.assertTrue(bill_customer(self.customer))
