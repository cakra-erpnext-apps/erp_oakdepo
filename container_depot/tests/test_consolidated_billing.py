"""Acceptance tests for on-demand consolidated postpaid billing
(``consolidated_billing.bill_customer``).

- A submitted TOP Survey Order is swept into a consolidated draft Sales Invoice
  and linked back (``sales_invoice`` set, ``invoice_status`` = Draft).
- A Cash Survey Order settles at submit (its own draft invoice) and is NOT swept.
- The sweep is idempotent: a second run finds nothing new.
- Per-order TOP charges (Survey Order) are swept even for a Cash-contract customer,
  while contract-level accruals (cleaning / M&R / storage) are gated on postpaid.
- **Multi-currency**: a customer with USD + IDR orders gets ONE draft invoice per
  currency, each billed in its own currency (never forced to the company default).

``bill_customer`` returns the list of created Sales Invoice names (``[]`` = nothing).
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, today

from container_depot import invoicing
from container_depot.consolidated_billing import bill_customer
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_container_booking import (
	_cleanup_customer_world,
	_make_active_contract,
)


def _cleanup_surveys(customer):
	"""Raw-delete every Survey Order for the customer (+ its charges), regardless of
	docstatus, and drop any leftover draft Sales Invoices."""
	surveys = frappe.get_all("Survey Order", filters={"paid_to": customer}, pluck="name")
	if surveys:
		frappe.db.delete("Survey Order Charge", {"parent": ("in", surveys)})
		frappe.db.delete("Survey Order", {"name": ("in", surveys)})
	frappe.db.delete("Sales Invoice", {"customer": customer, "docstatus": 0})
	frappe.db.commit()


def _make_survey(customer, item, payment_type, price, currency="IDR"):
	"""Insert + submit a one-charge Survey Order billed to ``customer``."""
	doc = frappe.get_doc({
		"doctype": "Survey Order",
		"paid_to": customer,
		"payment_type": payment_type,
		"currency": currency,
		"charges": [{"item": item, "price": price, "container_no": "TESTU0000001"}],
	})
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	doc.submit()
	doc.reload()
	return doc


class TestConsolidatedBillingSurvey(FrappeTestCase):
	"""TOP survey orders flow into the consolidated draft; Cash ones stay out."""

	CUSTOMER = "Consolidated Billing TOP Co"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.item = invoicing.ensure_service_item()
		cls.customer = ensure_test_customer(cls.CUSTOMER)
		_cleanup_surveys(cls.customer)
		_cleanup_customer_world(cls.customer)
		cls.contract = _make_active_contract(
			cls.customer, payment_type="TOP", credit_limit=1_000_000_000, payment_terms="NET 30"
		)

	@classmethod
	def tearDownClass(cls):
		_cleanup_surveys(cls.customer)
		_cleanup_customer_world(cls.customer)
		super().tearDownClass()

	def setUp(self):
		# Each test starts from a clean slate (surveys accrue + commit across tests).
		_cleanup_surveys(self.customer)

	def test_top_survey_swept_into_draft_invoice(self):
		survey = _make_survey(self.customer, self.item, "TOP", 500000)
		self.assertFalse(survey.sales_invoice, "TOP survey carries no invoice at submit")

		sis = bill_customer(self.customer)
		self.assertEqual(len(sis), 1, "one consolidated draft Sales Invoice (single currency)")
		si = sis[0]

		survey.reload()
		self.assertEqual(survey.sales_invoice, si, "survey linked to the consolidated invoice")
		self.assertEqual(survey.invoice_status, "Draft", "invoice_status reads Draft (SI is a draft)")

		inv = frappe.get_doc("Sales Invoice", si)
		self.assertEqual(inv.docstatus, 0, "consolidated invoice is a draft")
		self.assertEqual(inv.currency, "IDR", "billed in the survey's currency")
		self.assertTrue(
			any(abs(flt(row.rate) - 500000) < 1 for row in inv.items),
			"the survey charge is a line on the consolidated invoice",
		)

		self.assertEqual(bill_customer(self.customer), [], "re-run finds nothing unbilled (idempotent)")

	def test_cash_survey_not_swept(self):
		cash = _make_survey(self.customer, self.item, "Cash", 300000)
		self.assertTrue(cash.sales_invoice, "Cash survey raises its own draft invoice at submit")
		own_si = cash.sales_invoice

		self.assertEqual(
			bill_customer(self.customer), [], "a Cash survey is never swept into consolidated billing"
		)
		cash.reload()
		self.assertEqual(cash.sales_invoice, own_si, "Cash survey keeps its own invoice")

	def test_multi_currency_one_invoice_per_currency(self):
		usd = _make_survey(self.customer, self.item, "TOP", 500, currency="USD")
		idr = _make_survey(self.customer, self.item, "TOP", 700000, currency="IDR")

		sis = bill_customer(self.customer)
		self.assertEqual(len(sis), 2, "one draft invoice per currency")
		currencies = {frappe.db.get_value("Sales Invoice", s, "currency") for s in sis}
		self.assertEqual(currencies, {"USD", "IDR"}, "each invoice billed in its own currency")

		usd.reload()
		idr.reload()
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", usd.sales_invoice, "currency"), "USD",
			"USD survey linked to the USD invoice",
		)
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", idr.sales_invoice, "currency"), "IDR",
			"IDR survey linked to the IDR invoice",
		)
		# The USD charge is billed at face value (conversion_rate 1, no FX to IDR).
		usd_inv = frappe.get_doc("Sales Invoice", usd.sales_invoice)
		self.assertTrue(any(abs(flt(r.rate) - 500) < 1 for r in usd_inv.items))

	def test_discard_draft_rolls_back_orders(self):
		survey = _make_survey(self.customer, self.item, "TOP", 500000)
		sis = bill_customer(self.customer)
		self.assertEqual(len(sis), 1)
		si = sis[0]
		survey.reload()
		self.assertEqual(survey.sales_invoice, si)

		# Discard (delete) the generated draft invoice → orders roll back to un-invoiced.
		frappe.delete_doc("Sales Invoice", si, ignore_permissions=True)
		self.assertFalse(frappe.db.exists("Sales Invoice", si), "draft invoice discarded")
		survey.reload()
		self.assertFalse(survey.sales_invoice, "survey link cleared on discard")
		self.assertEqual(survey.invoice_status, "Not Invoiced", "survey rolled back to un-invoiced")

		# The order is billable again — a re-generate resyncs it into a fresh invoice.
		# (The invoice name may coincide with the discarded one: Frappe reverts the
		# naming-series counter when the last document is deleted.)
		sis2 = bill_customer(self.customer)
		self.assertEqual(len(sis2), 1, "order billable again after rollback")
		self.assertTrue(frappe.db.exists("Sales Invoice", sis2[0]))
		survey.reload()
		self.assertEqual(survey.sales_invoice, sis2[0], "survey re-linked to the regenerated invoice")

	def test_discard_one_currency_rolls_back_only_that_currency(self):
		usd = _make_survey(self.customer, self.item, "TOP", 500, currency="USD")
		idr = _make_survey(self.customer, self.item, "TOP", 700000, currency="IDR")
		sis = bill_customer(self.customer)
		self.assertEqual(len(sis), 2)
		usd.reload()
		idr.reload()
		usd_si, idr_si = usd.sales_invoice, idr.sales_invoice
		self.assertTrue(usd_si and idr_si and usd_si != idr_si)

		frappe.delete_doc("Sales Invoice", usd_si, ignore_permissions=True)
		usd.reload()
		idr.reload()
		self.assertFalse(usd.sales_invoice, "USD survey rolled back on discard")
		self.assertEqual(usd.invoice_status, "Not Invoiced")
		self.assertEqual(idr.sales_invoice, idr_si, "IDR survey untouched by USD discard")

	def test_generated_invoice_items_cannot_be_deleted(self):
		doc = frappe.get_doc({
			"doctype": "Survey Order",
			"paid_to": self.customer,
			"payment_type": "TOP",
			"currency": "IDR",
			"charges": [
				{"item": self.item, "price": 100000, "container_no": "TESTU0000001"},
				{"item": self.item, "price": 200000, "container_no": "TESTU0000002"},
			],
		})
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		doc.submit()

		sis = bill_customer(self.customer)
		si = frappe.get_doc("Sales Invoice", sis[0])
		self.assertEqual(len(si.items), 2, "two generated lines")

		# Removing a generated line must be rejected — the invoice mirrors its orders.
		del si.items[-1]
		with self.assertRaises(frappe.ValidationError):
			si.save(ignore_permissions=True)

	def test_generated_invoice_submit_and_pay_reflects_paid(self):
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		survey = _make_survey(self.customer, self.item, "TOP", 500000)
		si = frappe.get_doc("Sales Invoice", bill_customer(self.customer)[0])

		# The item-freeze guard must NOT block a legitimate submit.
		si.submit()
		survey.reload()
		self.assertIn(survey.invoice_status, ("Unpaid", "Overdue"), "submitted invoice → Unpaid")

		pe = get_payment_entry("Sales Invoice", si.name)
		if not pe.paid_to:
			acc = frappe.db.get_value(
				"Account",
				{"company": si.company, "account_type": ["in", ["Bank", "Cash"]], "is_group": 0},
				"name",
			)
			pe.paid_to = acc
			pe.paid_to_account_currency = frappe.db.get_value("Account", acc, "account_currency")
		pe.reference_no = "TEST-PAY"
		pe.reference_date = today()
		pe.insert(ignore_permissions=True)
		pe.submit()

		si.reload()
		survey.reload()
		self.assertEqual(si.status, "Paid", "consolidated invoice marked Paid natively")
		self.assertEqual(survey.invoice_status, "Paid", "survey reflects Paid after payment")

	def test_repair_links_invoice_and_rolls_back(self):
		cno = "TESTMR00001"
		frappe.db.delete("Repair Order", {"container": cno})
		if frappe.db.exists("Container", cno):
			frappe.db.delete("Container", cno)
		cont = frappe.get_doc({
			"doctype": "Container", "container_no": cno, "container_type": "ISO Tank",
			"status": "Available", "principal": self.customer,
		})
		cont.flags.ignore_mandatory = True
		cont.insert(ignore_permissions=True)
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": cno, "status": "Draft", "billing_status": "Unbilled",
		})
		ro.flags.ignore_mandatory = True
		ro.insert(ignore_permissions=True)
		# Force it into a completed, unbilled, costed state (bypass the M&R workflow / cost recompute).
		frappe.db.set_value("Repair Order", ro.name, {
			"status": "Completed", "billing_status": "Unbilled",
			"completion_date": today(), "total_cost": 100000, "principal": self.customer,
		}, update_modified=False)

		try:
			sis = bill_customer(self.customer)
			self.assertEqual(len(sis), 1, "repair swept into one invoice")
			si = sis[0]
			self.assertEqual(
				frappe.db.get_value("Repair Order", ro.name, "sales_invoice"), si,
				"repair linked to the generated invoice",
			)
			self.assertEqual(frappe.db.get_value("Repair Order", ro.name, "billing_status"), "Client Billed")

			# Discard the draft → repair rolls back to un-invoiced (link cleared, Unbilled).
			frappe.delete_doc("Sales Invoice", si, ignore_permissions=True)
			self.assertFalse(
				frappe.db.get_value("Repair Order", ro.name, "sales_invoice"),
				"repair link cleared on discard",
			)
			self.assertEqual(frappe.db.get_value("Repair Order", ro.name, "billing_status"), "Unbilled")
		finally:
			frappe.db.delete("Repair Order", {"name": ro.name})
			frappe.db.delete("Container", cno)


class TestConsolidatedBillingPostpaidSplit(FrappeTestCase):
	"""A per-order TOP charge is swept even when the customer's contract is Cash —
	proving the per-order vs contract-level split."""

	CUSTOMER = "Consolidated Billing Cash Co"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.item = invoicing.ensure_service_item()
		cls.customer = ensure_test_customer(cls.CUSTOMER)
		_cleanup_surveys(cls.customer)
		_cleanup_customer_world(cls.customer)
		cls.contract = _make_active_contract(cls.customer, payment_type="Cash")

	@classmethod
	def tearDownClass(cls):
		_cleanup_surveys(cls.customer)
		_cleanup_customer_world(cls.customer)
		super().tearDownClass()

	def setUp(self):
		_cleanup_surveys(self.customer)

	def test_top_survey_swept_even_for_cash_customer(self):
		survey = _make_survey(self.customer, self.item, "TOP", 400000)
		sis = bill_customer(self.customer)
		self.assertTrue(sis, "per-order TOP survey is swept regardless of contract mode")
		survey.reload()
		self.assertEqual(survey.sales_invoice, sis[0])
