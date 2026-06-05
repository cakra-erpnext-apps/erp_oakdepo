"""Phase 10 (B7) tests: postpaid (TOP) accrual + on-demand consolidated billing.

- TOP bookings submit freely, create NO per-transaction invoice, accrue Unpaid.
- ``consolidated_billing.bill_customer`` sweeps a customer's unbilled bookings
  (+ M&R, etc.) into ONE draft Sales Invoice; idempotent on re-run.
- The OAK Billing Run doctype is the manual Desk trigger.
- The monthly scheduler skips TOP customers (no double-billing).
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot.consolidated_billing import bill_customer
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_isotank_booking import _cleanup_customer_world, _make_active_contract


def _purge(customer):
	"""Deep cleanup: billing runs, repair orders, containers (any status), plus the
	shared customer-world cleanup (bookings, draft invoices, contracts)."""
	frappe.db.delete("OAK Billing Run", {"customer": customer})
	ros = frappe.get_all("Repair Order", filters={"principal": customer}, pluck="name")
	if ros:
		frappe.db.delete("Repair Estimate Item", {"parent": ["in", ros]})
		frappe.db.delete("Repair Order", {"name": ["in", ros]})
	conts = frappe.get_all("Container", filters={"principal": customer}, pluck="name")
	if conts:
		frappe.db.delete("Container Movement", {"container": ["in", conts]})
		frappe.db.delete("Cleaning Order", {"container": ["in", conts]})
		frappe.db.delete("Container", {"name": ["in", conts]})
	_cleanup_customer_world(customer)  # commits


class TestTopConsolidatedBilling(FrappeTestCase):
	def setUp(self):
		self.customer = ensure_test_customer("B7 TOP Customer")
		_purge(self.customer)
		# Tiny credit limit — TOP no longer gates on it (accrual).
		self.contract = _make_active_contract(
			self.customer, payment_type="TOP", credit_limit=1, payment_terms="NET 30"
		)

	def tearDown(self):
		_purge(self.customer)
		frappe.db.rollback()

	def _booking(self, container_no):
		b = frappe.get_doc({
			"doctype": "Isotank Booking",
			"direction": "Tank In",  # Tank In -> Lift Off @ 250000
			"customer": self.customer,
			"contract": self.contract,
			"booking_status": "Pending Confirmation",
			"do_reference": "DO-B7",
			"do_document": "/files/do.pdf",
			"items": [{"container_no": container_no}],
		})
		b.insert(ignore_permissions=True)
		b.submit()
		return b

	def test_two_bookings_become_one_invoice(self):
		b1 = self._booking("B7TANK00001")
		b2 = self._booking("B7TANK00002")
		si = bill_customer(self.customer)
		self.assertTrue(si, "consolidated invoice not created")
		# 2 bookings x Lift Off 250000 (PPN sits on top of net_total).
		self.assertEqual(frappe.db.get_value("Sales Invoice", si, "net_total"), 500000)
		b1.reload()
		b2.reload()
		self.assertEqual(b1.sales_invoice, si)
		self.assertEqual(b1.payment_status, "Invoiced")
		self.assertEqual(b2.sales_invoice, si)
		self.assertEqual(b2.payment_status, "Invoiced")

	def test_billing_is_idempotent(self):
		self._booking("B7TANK00003")
		first = bill_customer(self.customer)
		self.assertTrue(first)
		second = bill_customer(self.customer)  # nothing left unbilled
		self.assertIsNone(second, "re-run must not double-bill")

	def test_booking_and_mr_in_one_invoice(self):
		"""A single customer's unbilled booking lift + M&R land on one invoice."""
		b = self._booking("B7MRTANK001")
		container = b.items[0].container
		ro = frappe.get_doc({
			"doctype": "Repair Order",
			"container": container,
			"status": "Completed",
			"completion_date": today(),
			"billing_status": "Unbilled",
			"estimation_items": [{"quantity": 1, "unit_price": 300000}],
		})
		ro.insert(ignore_permissions=True)
		si = bill_customer(self.customer)
		self.assertTrue(si)
		# lift 250000 + M&R 300000.
		self.assertEqual(frappe.db.get_value("Sales Invoice", si, "net_total"), 550000)
		self.assertEqual(frappe.db.get_value("Repair Order", ro.name, "billing_status"), "Client Billed")

	def test_billing_run_doctype_generates_invoice(self):
		self._booking("B7TANK00004")
		run = frappe.get_doc({"doctype": "OAK Billing Run", "customer": self.customer}).insert(ignore_permissions=True)
		run.submit()
		run.reload()
		self.assertTrue(run.sales_invoice, "billing run did not link a Sales Invoice")
		self.assertGreater(run.total or 0, 0)

	def test_nothing_to_bill_returns_none(self):
		self.assertIsNone(bill_customer(self.customer))


class TestPostpaidSchedulerSkip(FrappeTestCase):
	def setUp(self):
		self.customer = ensure_test_customer("B7 Skip Customer")
		_cleanup_customer_world(self.customer)
		self.contract = _make_active_contract(
			self.customer, payment_type="TOP", credit_limit=1, payment_terms="NET 30"
		)

	def tearDown(self):
		_cleanup_customer_world(self.customer)
		frappe.db.rollback()

	def test_top_customer_is_flagged_postpaid(self):
		from container_depot.monthly_invoicing import _is_postpaid

		self.assertTrue(_is_postpaid(self.customer), "TOP customer must be treated as postpaid (monthly-skip)")
