"""The finance master switch: the depot runs with invoicing off.

Two halves are asserted here, and they are the whole point of the switch:

1. **Nothing financial is created, and nothing waits on an invoice.** No Sales Invoice is
   raised on any path. What does NOT step aside is the depot's own Cash rule: the three
   places money can stop an operation — a Cash booking's submit, the gate's ``cash_unpaid``,
   generating a bon — all still refuse an Unpaid booking, they just read the admin's manual
   label instead of an invoice, because with invoicing off that label is the only answer the
   depot has (``container_booking.set_payment_status`` /
   ``container_booking.ContainerBooking._require_manual_paid``).
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

	# --- nothing waits on an invoice ------------------------------------------
	def test_cash_booking_is_refused_until_it_is_marked_paid(self):
		"""The Cash rule survives the switch; only where the answer is read from changes.

		Waiting on an invoice that will never be raised would strand every Cash booking, so
		submit reads the manual label instead (``_require_manual_paid``) — the same answer
		the gate and the bon already read in this mode. Nothing is parked in Pending
		Payment: the draft stays a draft, with the button that clears it on screen.
		"""
		_set_finance(False)
		b = self._booking("FINSW0002")
		b.flags.ignore_permissions = True
		with self.assertRaises(frappe.ValidationError):
			b.submit()
		b.reload()
		self.assertEqual(b.docstatus, 0)
		self.assertEqual(b.booking_status, "Draft")

	def test_cash_booking_confirms_once_marked_paid_without_an_invoice(self):
		"""…and once the admin says the money arrived it confirms with nothing billed — no
		invoice anywhere, and the operational half (the gate codes) issued as always."""
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			set_payment_status,
		)

		_set_finance(False)
		b = self._booking("FINSW0002")
		set_payment_status(b.name, "Paid")
		b.reload()
		b.flags.ignore_permissions = True
		b.submit()
		b.reload()
		self.assertEqual(b.docstatus, 1)
		self.assertEqual(b.booking_status, "Confirmed")
		self.assertIsNone(b.sales_invoice)
		# Confirmation still issues the gate codes — the operational half is unaffected.
		self.assertTrue(frappe.get_all("Booking Code", filters={"booking": b.name}, pluck="name"))

	def test_the_gate_reads_the_manual_paid_label(self):
		"""REVERSED on 2026-09-03, and the reversal is the point.

		This used to assert that money can NEVER shut the gate while finance is off — the
		reasoning being that with no Sales Invoice there is no payment state worth holding a
		tank over. That stopped being true the moment :func:`set_payment_status` gave an admin
		a manual Paid / Unpaid switch for exactly this mode: the field became somebody's
		deliberate statement that the money did or did not arrive, and ignoring it would be
		ignoring the only answer the depot has.

		So with finance off the gate reads the label — Unpaid shuts it, and marking it Paid by
		hand is what opens it.

		A confirmed booking has to be marked Paid to have been confirmed at all now, and
		un-paying one is refused (see :func:`test_a_confirmed_booking_cannot_be_un_paid`), so
		the Unpaid state under test is written straight to the row — the shape of a booking
		carried past submit before either rule existed, which is exactly what the gate still
		has to cope with.
		"""
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			set_payment_status,
		)

		_set_finance(False)
		b = self._booking("FINSW0003")
		set_payment_status(b.name, "Paid")
		b.reload()
		b.flags.ignore_permissions = True
		b.submit()
		frappe.db.set_value("Container Booking", b.name, "payment_status", "Unpaid")
		self.assertEqual(_booking_gate_detail(b.name)["block_reason"], "cash_unpaid")
		set_payment_status(b.name, "Paid")
		self.assertIsNone(_booking_gate_detail(b.name)["block_reason"])

	# --- the manual paid/unpaid label -----------------------------------------
	def test_confirming_does_not_write_the_label_by_itself(self):
		"""``on_submit``'s payment stamp is finance-ON only, and must stay that way: with the
		switch off the label is a person's statement, not something submit derives.

		Asserted on a TOP booking — the type that still submits freely here — carrying a
		hand-set Paid. The finance-on formula writes TOP's "Unpaid", so anything but Paid on
		the far side means submit overwrote somebody's answer about real money.
		"""
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			set_payment_status,
		)

		_set_finance(False)
		# A Both contract is what leaves the choice with the operator — under a Cash one
		# `_sync_payment_type_from_contract` would put the booking straight back to Cash.
		frappe.db.set_value("Depot Contract", self.contract, "payment_type", "Both")
		b = self._booking("FINSW0005")
		b.payment_type = "TOP"
		b.save(ignore_permissions=True)
		set_payment_status(b.name, "Paid")
		b.reload()
		b.flags.ignore_permissions = True
		b.submit()
		b.reload()
		self.assertEqual(b.payment_type, "TOP")
		self.assertEqual(b.payment_status, "Paid")

	def test_admin_sets_the_label_by_hand_on_a_submitted_booking(self):
		"""The label is a human's answer while there is no invoice to derive it from — and
		it has to work AFTER submit, which is when the cash actually arrives (the form
		itself is locked shut by then)."""
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			set_payment_status,
		)

		_set_finance(False)
		b = self._booking("FINSW0006")
		# Marked before submit because submit now insists on it; the point here is what
		# happens AFTER, where the form itself is locked shut.
		set_payment_status(b.name, "Paid")
		b.reload()
		b.flags.ignore_permissions = True
		b.submit()
		self.assertEqual(frappe.db.get_value("Container Booking", b.name, "payment_status"), "Paid")

	def test_a_confirmed_booking_cannot_be_un_paid(self):
		"""Marking a confirmed booking Paid is a statement about money that arrived; taking it
		back is not a mis-click's business, because the gate and the bon both read it.

		The undo that remains is Kembali ke Draft — the draft may then be toggled either way.
		"""
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			set_payment_status,
		)

		_set_finance(False)
		b = self._booking("FINSW0009")
		set_payment_status(b.name, "Paid")
		b.reload()
		b.flags.ignore_permissions = True
		b.submit()
		with self.assertRaises(frappe.ValidationError):
			set_payment_status(b.name, "Unpaid")
		self.assertEqual(frappe.db.get_value("Container Booking", b.name, "payment_status"), "Paid")

	def test_a_draft_may_be_toggled_either_way(self):
		"""Nothing is confirmed yet, so a mis-click is just a mis-click."""
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			set_payment_status,
		)

		_set_finance(False)
		b = self._booking("FINSW0011")
		set_payment_status(b.name, "Paid")
		set_payment_status(b.name, "Unpaid")
		self.assertEqual(frappe.db.get_value("Container Booking", b.name, "payment_status"), "Unpaid")

	def test_hand_setting_is_refused_once_finance_is_on(self):
		"""With invoicing live the Sales Invoice owns the field — the gate and the bon read
		it, so a hand-set Paid over an unpaid invoice would open the gate on money nobody
		collected."""
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			set_payment_status,
		)

		_set_finance(True)
		b = self._booking("FINSW0007")
		with self.assertRaises(frappe.ValidationError):
			set_payment_status(b.name, "Paid")

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
