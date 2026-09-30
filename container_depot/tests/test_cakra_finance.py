"""The erp_cakra finance shape: tax boxes, per-line currency, invoice number, kasbon, payments.

Nothing here commits, so FrappeTestCase's class rollback takes every row back — including
the series counters the numbers consumed. Finance and the tax accounts are patched in memory
rather than written to Depot Finance Settings, so the site's own settings are never touched.
"""

from __future__ import annotations

import re
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, today

from container_depot import finance, invoicing
from container_depot import payment_entry as pe_mod
from container_depot.container_depot.doctype.pending_cash.pending_cash import run_action

CUSTOMER = "Cakra Finance Test Co"
SUPPLIER = "Cakra Finance Test Supplier"
KASBON_TYPE = "CFTEST"


def _account(company, like, **filters):
	return frappe.db.get_value("Account", {"company": company, "is_group": 0, "name": ["like", like], **filters}, "name")


class TestCakraFinance(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = invoicing.get_default_company()
		cls.cash = frappe.db.get_value("Account", {"company": cls.company, "account_type": "Cash", "is_group": 0}, "name")
		cls.tax = frappe.db.get_value("Account", {"company": cls.company, "account_type": "Tax", "is_group": 0}, "name")
		cls.expense = frappe.db.get_value("Account", {"company": cls.company, "root_type": "Expense", "is_group": 0}, "name")
		cls.advance = frappe.db.get_value(
			"Account", {"company": cls.company, "account_type": "Payable", "is_group": 0}, "name"
		)
		if not frappe.db.exists("Customer", CUSTOMER):
			frappe.get_doc({"doctype": "Customer", "customer_name": CUSTOMER}).insert(ignore_permissions=True)
		if not frappe.db.exists("Supplier", SUPPLIER):
			frappe.get_doc({
				"doctype": "Supplier", "supplier_name": SUPPLIER,
				"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
			}).insert(ignore_permissions=True)

	def setUp(self):
		for target, attr, value in (
			(finance, "is_enabled", lambda: True),
			(invoicing, "_tax_accounts", lambda company: {"ppn": self.tax, "pph": self.tax, "materai": self.tax}),
			(pe_mod, "_component_accounts", lambda doc: {"ppn": self.tax, "pph": self.tax, "materai": self.tax, "admin": self.expense}),
		):
			p = patch.object(target, attr, value)
			p.start()
			self.addCleanup(p.stop)

	def _invoice(self, lines, **kw):
		kw.setdefault("manhour", False)
		kw.setdefault("branch", frappe.db.get_value("Branch", {}, "name"))  # required to submit
		return frappe.get_doc("Sales Invoice", invoicing.create_draft_sales_invoice(CUSTOMER, lines, **kw))

	# ---- "11%" or "50000" -------------------------------------------------------
	def test_smart_input_reads_both_locales(self):
		cases = {
			"11%": ("pct", 11), "2,5%": ("pct", 2.5), "50000": ("amt", 50000), "50.000": ("amt", 50000),
			"2,000,000": ("amt", 2000000), "1.234,56": ("amt", 1234.56), "1,234.56": ("amt", 1234.56), "": (None, 0),
		}
		for raw, want in cases.items():
			self.assertEqual(invoicing.parse_smart(raw), want, raw)

	# ---- Sales Invoice ----------------------------------------------------------
	def test_number_is_branch_owned_and_yearly(self):
		si = self._invoice([{"item_code": "Lift On", "qty": 1, "rate": 100}])
		self.assertRegex(si.name, rf"^INV-[A-Z0-9]+-OAK-{today()[2:4]}-\d{{4}}$")

	def test_a_usd_invoice_converts_an_idr_line_through_idr(self):
		si = self._invoice(
			[
				{"item_code": "Lift Off", "qty": 1, "rate": 100, "currency": "USD"},
				{"item_code": "Lift On", "qty": 2, "rate": 500000, "currency": "IDR"},
			],
			currency="USD", kurs={"USD": 16000}, tax_input="11%",
		)
		self.assertEqual([flt(r.rate) for r in si.items], [100.0, 31.25])
		self.assertEqual(flt(si.net_total), 162.5)
		# The ledger books IDR at the invoice's own kurs.
		self.assertAlmostEqual(flt(si.base_grand_total), flt(si.grand_total) * 16000, delta=16000 * 0.01)

	def test_ppn_stands_on_price_plus_labour(self):
		# Labour: tariff 25/jam × Total Jam 4 (the default) = 100, once Tagih Manhour is ticked.
		si = self._invoice([{"item_code": "Lift On", "qty": 1, "rate": 1000, "manhour": 25}], manhour=True, tax_input="11%")
		si.depot_bill_manhour = 1
		si.save(ignore_permissions=True)
		self.assertEqual([t.description for t in si.taxes], ["Manhour", "PPN"])
		self.assertEqual(si.taxes[1].charge_type, "On Previous Row Total")
		self.assertAlmostEqual(flt(si.grand_total), (1000 + 100) * 1.11, places=2)

	def test_submit_needs_a_branch_and_can_skip_the_ledger(self):
		si = self._invoice([{"item_code": "Lift On", "qty": 1, "rate": 100}], branch=None)
		self.assertRaises(frappe.ValidationError, si.submit)
		si.reload()
		si.branch, si.dont_post_to_gl = frappe.db.get_value("Branch", {}, "name"), 1
		si.submit()
		self.assertFalse(frappe.db.exists("GL Entry", {"voucher_no": si.name}))

	def test_a_foreign_invoice_does_not_post_at_kurs_one(self):
		si = self._invoice([{"item_code": "Lift On", "qty": 1, "rate": 10, "currency": "USD"}], currency="USD", kurs={"USD": 1})
		self.assertRaises(frappe.ValidationError, si.submit)

	# ---- Kasbon + Payment Entry ---------------------------------------------------
	def _kasbon(self, total):
		if not frappe.db.exists("Pending Cash Type", KASBON_TYPE):
			frappe.get_doc({"doctype": "Pending Cash Type", "code": KASBON_TYPE, "title": "Test", "advance_account": self.advance}).insert()
		return frappe.get_doc({
			"doctype": "Pending Cash", "pending_cash_type": KASBON_TYPE, "pay_to": SUPPLIER, "total": total,
			"bank_account": self.cash, "date": today(),
		}).insert()

	def test_only_finance_pays_a_kasbon(self):
		pc = self._kasbon(1000)
		with patch("frappe.get_roles", return_value=["Cashier"]):
			self.assertEqual(run_action([pc.name], "validate")["done"], [pc.name])
			self.assertEqual(len(run_action([pc.name], "pay")["failed"]), 1)
		self.assertEqual(run_action([pc.name], "pay")["done"], [pc.name])
		pc.reload()
		self.assertEqual((pc.status, bool(pc.journal_entry)), ("Paid", True))

	def test_a_receipt_net_of_pph_clears_the_whole_invoice(self):
		si = self._invoice([{"item_code": "Lift On", "qty": 1, "rate": 1000000}])
		si.submit()
		rv = frappe.get_doc({
			"doctype": "Payment Entry", "payment_type": "Receive", "company": self.company,
			"party_type": "Customer", "party": CUSTOMER, "paid_to": self.cash, "depot_pph_input": "2%",
			"depot_lines": [{"document_type": "Sales Invoice", "document_no": si.name, "outstanding": 1000000, "amount": 1000000}],
		}).insert()
		self.assertEqual((flt(rv.received_amount), flt(rv.difference_amount)), (980000.0, 0.0))
		rv.submit()
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", si.name, "outstanding_amount")), 0.0)
		# Customer Paid follows the payment, both ways.
		self.assertEqual(str(frappe.db.get_value("Sales Invoice", si.name, "depot_paid_date")), str(rv.posting_date))
		# A paid invoice waits for its receipt to be cancelled first.
		si.reload()
		self.assertRaisesRegex(frappe.ValidationError, rv.name, si.cancel)
		rv.cancel()
		self.assertIsNone(frappe.db.get_value("Sales Invoice", si.name, "depot_paid_date"))
		si.reload()
		si.cancel()
		self.assertEqual(si.docstatus, 2)

	def test_a_kasbon_pays_instead_of_the_bank(self):
		pc = self._kasbon(500000)
		run_action([pc.name], "validate")
		run_action([pc.name], "pay")
		pe = frappe.get_doc({
			"doctype": "Payment Entry", "payment_type": "Pay", "company": self.company, "paid_from": self.cash,
			"depot_direct": 1, "depot_lines": [{"description": "ATK", "account": self.expense, "amount": 300000}],
			"depot_kasbon": [{"pending_cash": pc.name, "allocated": 300000}],
		}).insert()
		pe.submit()
		bank = frappe.db.get_value("GL Entry", {"voucher_no": pe.name, "account": self.cash, "is_cancelled": 0}, "name")
		self.assertIsNone(bank, "the kasbon already paid: the bank is not charged again")
		self.assertIn(pe.name, run_action([pc.name], "unpaid")["failed"][0]["error"])
