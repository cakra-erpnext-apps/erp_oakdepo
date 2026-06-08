"""Acceptance tests for the Cash-vs-Termin billing model + read-only statement.

Covers the requirements in reference/invoice.md (§4 acceptance):

- Payment Terms Templates (Immediate / Net 30 / End of Following Month) seeded.
- Modes of Payment Cash + Bank Transfer exist and are mapped to company accounts.
- A Customer's default payment terms flow into a new Sales Invoice (inheritance),
  and can be overridden per invoice.
- The contract-mode backfill sets the right default and never clobbers an
  existing choice.
- Process Statement Of Accounts is read-only (not submittable) → it cannot post
  accounting entries / create documents.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.install import (
	ensure_modes_of_payment,
	ensure_payment_terms_templates,
)
from container_depot.patches.v0_13 import set_customer_payment_terms as backfill_patch
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_isotank_booking import (
	_cleanup_customer_world,
	_make_active_contract,
)

EOFM = "End of Following Month"


def _default_company():
	return frappe.defaults.get_global_default("company") or frappe.db.get_value(
		"Company", {}, "name"
	)


class TestBillingModeMasters(FrappeTestCase):
	"""Payment Terms Templates + Modes of Payment are seeded & mapped."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Idempotent — safe to (re)run; makes the test independent of a prior migrate.
		ensure_payment_terms_templates()
		ensure_modes_of_payment()

	def test_payment_terms_templates_seeded(self):
		for name in ("Immediate", "Net 30", EOFM):
			self.assertTrue(
				frappe.db.exists("Payment Terms Template", name),
				f"missing Payment Terms Template '{name}'",
			)

	def test_immediate_is_zero_days(self):
		tmpl = frappe.get_doc("Payment Terms Template", "Immediate")
		row = tmpl.terms[0]
		self.assertEqual(row.due_date_based_on, "Day(s) after invoice date")
		self.assertEqual(row.credit_days or 0, 0)
		self.assertEqual(row.invoice_portion, 100)

	def test_eofm_is_month_after_invoice_month(self):
		tmpl = frappe.get_doc("Payment Terms Template", EOFM)
		row = tmpl.terms[0]
		self.assertEqual(row.due_date_based_on, "Month(s) after the end of the invoice month")
		self.assertEqual(row.credit_months, 1)

	def test_modes_of_payment_seeded_and_mapped(self):
		company = _default_company()
		for mop, mop_type in (("Cash", "Cash"), ("Bank Transfer", "Bank")):
			self.assertTrue(frappe.db.exists("Mode of Payment", mop), f"missing MoP '{mop}'")
			self.assertEqual(frappe.db.get_value("Mode of Payment", mop, "type"), mop_type)
			account = frappe.db.get_value(
				"Mode of Payment Account",
				{"parent": mop, "company": company},
				"default_account",
			)
			self.assertTrue(account, f"MoP '{mop}' not mapped to an account for {company}")


class TestCustomerDefaultInheritance(FrappeTestCase):
	"""Customer default flows into a Sales Invoice, and is overridable per invoice."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_payment_terms_templates()
		cls.company = _default_company()
		cls.customer = ensure_test_customer("Billing Termin Customer")
		frappe.db.set_value("Customer", cls.customer, "payment_terms", EOFM)

	@classmethod
	def tearDownClass(cls):
		frappe.db.set_value("Customer", cls.customer, "payment_terms", None)
		super().tearDownClass()

	def test_get_payment_terms_template_resolves_customer_default(self):
		from erpnext.accounts.party import get_payment_terms_template

		self.assertEqual(
			get_payment_terms_template(self.customer, "Customer", self.company), EOFM
		)

	def test_new_sales_invoice_inherits_default(self):
		si = frappe.new_doc("Sales Invoice")
		si.company = self.company
		si.customer = self.customer
		si.run_method("set_missing_values")
		self.assertEqual(si.payment_terms_template, EOFM)

	def test_override_per_invoice_field_is_editable(self):
		# No property setter hides/read-onlys the override field on Sales Invoice.
		meta = frappe.get_meta("Sales Invoice")
		df = meta.get_field("payment_terms_template")
		self.assertIsNotNone(df, "Sales Invoice has no payment_terms_template field")
		self.assertFalse(df.hidden, "payment_terms_template is hidden")
		self.assertFalse(df.read_only, "payment_terms_template is read-only")

	def test_override_beats_customer_default(self):
		# Explicitly choosing a different template on the invoice wins over the
		# customer default (ignore_default_payment_terms_template is set).
		si = frappe.new_doc("Sales Invoice")
		si.company = self.company
		si.customer = self.customer
		si.payment_terms_template = "Immediate"
		si.run_method("set_missing_values")
		self.assertEqual(si.payment_terms_template, "Immediate")


class TestContractBackfill(FrappeTestCase):
	"""Backfill maps Depot Contract.payment_type -> Customer.payment_terms default."""

	def setUp(self):
		ensure_payment_terms_templates()

	def _customer_with_contract(self, name, payment_type):
		customer = ensure_test_customer(name)
		_cleanup_customer_world(customer)
		frappe.db.set_value("Customer", customer, "payment_terms", None)
		# Depot Contract has its OWN descriptive payment_terms Select (NET 30/45/...),
		# required for TOP contracts — unrelated to the Customer Payment Terms
		# Template the backfill sets. Provide it so the contract validates.
		contract_terms = "NET 30" if payment_type == "TOP" else None
		credit_limit = 1 if payment_type == "TOP" else 0
		_make_active_contract(
			customer,
			payment_type=payment_type,
			payment_terms=contract_terms,
			credit_limit=credit_limit,
		)
		return customer

	def tearDown(self):
		frappe.db.rollback()

	def test_top_contract_backfills_eofm(self):
		customer = self._customer_with_contract("Billing TOP Backfill", "TOP")
		backfill_patch.backfill()
		self.assertEqual(frappe.db.get_value("Customer", customer, "payment_terms"), EOFM)

	def test_cash_contract_backfills_immediate(self):
		customer = self._customer_with_contract("Billing Cash Backfill", "Cash")
		backfill_patch.backfill()
		self.assertEqual(
			frappe.db.get_value("Customer", customer, "payment_terms"), "Immediate"
		)

	def test_backfill_does_not_clobber_existing(self):
		customer = self._customer_with_contract("Billing Keep Backfill", "TOP")
		frappe.db.set_value("Customer", customer, "payment_terms", "Net 30")
		backfill_patch.backfill()
		self.assertEqual(
			frappe.db.get_value("Customer", customer, "payment_terms"),
			"Net 30",
			"backfill must not overwrite an existing default",
		)


class TestStatementIsReadOnly(FrappeTestCase):
	"""Process Statement Of Accounts is a reminder, not an accounting document."""

	def test_psoa_doctype_available(self):
		self.assertTrue(frappe.db.exists("DocType", "Process Statement Of Accounts"))

	def test_psoa_is_not_submittable(self):
		# A non-submittable doctype cannot post GL entries; PSOA only renders/emails
		# a summary of EXISTING invoices — it never creates invoices/journals.
		self.assertEqual(
			frappe.get_meta("Process Statement Of Accounts").is_submittable, 0
		)
