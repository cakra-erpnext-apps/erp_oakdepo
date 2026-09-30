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
from container_depot.container_depot.doctype.pending_cash import pending_cash as pc_mod
from container_depot.container_depot.doctype.pending_cash.pending_cash import _guard_not_refunded, run_action
from container_depot.container_depot.doctype.pending_cash_refund import pending_cash_refund as rf_mod

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
			(pc_mod, "charge_account", lambda setting: self.expense),
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
	def _kasbon(self, total, **kw):
		if not frappe.db.exists("Pending Cash Type", KASBON_TYPE):
			frappe.get_doc({"doctype": "Pending Cash Type", "code": KASBON_TYPE, "title": "Test", "advance_account": self.advance}).insert()
		return frappe.get_doc({
			"doctype": "Pending Cash", "pending_cash_type": KASBON_TYPE, "pay_to": SUPPLIER, "total": total,
			"bank_account": self._bank().name, "date": today(), **kw,
		}).insert()

	def _deposit(self, total):
		"""A customer's deposit: a Cash Inflow type on a liability account of its own."""
		if not frappe.db.exists("Pending Cash Type", "CFDEP"):
			parent = frappe.db.get_value("Account", {"company": self.company, "is_group": 1, "root_type": "Liability"}, "name")
			account = frappe.get_doc({
				"doctype": "Account", "account_name": "CF Deposit Customer", "parent_account": parent, "company": self.company,
			}).insert(ignore_permissions=True).name
			frappe.get_doc({
				"doctype": "Pending Cash Type", "code": "CFDEP", "title": "Deposit", "direction": "Cash Inflow", "advance_account": account,
			}).insert()
		pc = frappe.get_doc({
			"doctype": "Pending Cash", "pending_cash_type": "CFDEP", "receive_from": CUSTOMER, "total": total,
			"bank_account": self._bank().name, "date": today(),
		}).insert()
		run_action([pc.name], "validate")
		run_action([pc.name], "pay")
		return frappe.get_doc("Pending Cash", pc.name)

	def _gl(self, voucher):
		out = {}
		for r in frappe.get_all("GL Entry", filters={"voucher_no": voucher, "is_cancelled": 0}, fields=["account", "party", "debit", "credit"]):
			key = (r.account, r.party or None)
			out[key] = out.get(key, 0.0) + flt(r.debit) - flt(r.credit)
		return out

	def test_a_customer_deposit_settles_invoices_and_the_rest_is_refunded(self):
		dep = self._deposit(1500000)
		bank = self._bank().account
		deposit_account = frappe.db.get_value("Pending Cash Type", "CFDEP", "advance_account")
		# Received: Dr Bank / Cr Deposit, the customer on the deposit.
		self.assertEqual(self._gl(dep.journal_entry), {(bank, None): 1500000.0, (deposit_account, CUSTOMER): -1500000.0})
		si = self._invoice([{"item_code": "Lift On", "qty": 1, "rate": 1000000}])
		si.submit()
		rv = self._receipt(si, depot_kasbon=[{"pending_cash": dep.name}])
		# Only what the invoice needs is drawn; nothing comes through the bank.
		self.assertEqual((flt(rv.depot_kasbon[0].allocated), flt(rv.depot_bank_amount)), (1000000.0, 0.0))
		rv.submit()
		gl = self._gl(rv.name)
		self.assertEqual(gl.get((deposit_account, CUSTOMER)), 1000000.0)
		self.assertNotIn((self.cash, None), gl)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", si.name, "outstanding_amount")), 0.0)
		self.assertIn("Dipotong dari deposit", frappe.get_print("Payment Entry", rv.name, "OAK Payment Voucher"))
		# A submitted payment drew on it: Completed, and the payment is on its list column.
		self.assertEqual(frappe.db.get_value("Pending Cash", dep.name, ["status", "payment_no"]), ("Completed", rv.name))
		# Another customer's receipt cannot draw on it.
		self.assertEqual(pe_mod.get_kasbon(company=self.company, payment_type="Receive", customer="Nobody"), [])
		# What is left goes back through a Pending Cash Refund of its own, a draft that
		# already claims it; its journal (Dr Deposit / Cr Bank) waits for Validate.
		dep.reload()
		self.assertEqual(dep.available(), 500000.0)
		out = run_action([dep.name], "refund", remark="sisa deposit")
		rf = frappe.get_doc("Pending Cash Refund", out["created"][0])
		self.assertEqual((rf.party_type, rf.party, flt(rf.amount), rf.journal_entry), ("Customer", CUSTOMER, 500000.0, None))
		self.assertEqual(dep.available(), 0.0)
		self.assertEqual(rf_mod.bulk_validate([rf.name])["done"], [rf.name])
		rf.reload()
		self.assertEqual(self._gl(rf.journal_entry), {(deposit_account, CUSTOMER): 500000.0, (bank, None): -500000.0})
		# Money refunded cannot be un-received under it.
		self.assertRaisesRegex(frappe.ValidationError, "refund aktif", _guard_not_refunded, dep)
		# Void keeps its cancelled journal as the trace, and gives the amount back.
		rf_mod.bulk_void([rf.name])
		rf.reload()
		self.assertEqual(frappe.db.get_value("Journal Entry", rf.journal_entry, "docstatus"), 2)
		self.assertEqual((flt(frappe.db.get_value("Pending Cash", dep.name, "refunded_amount")), dep.available()), (0.0, 500000.0))

	def test_a_kasbon_carries_its_bank_charges_and_only_an_unpaid_one_is_voided(self):
		bank = self._bank().account
		pc = self._kasbon(1000000, admin_fee=6500, stamp_duty=10000)
		self.assertEqual(flt(pc.net_amount_paid), 1016500.0)
		# Paying a draft validates it in the same step; the bank pays the advance and its charges.
		self.assertEqual(run_action([pc.name], "pay")["done"], [pc.name])
		pc.reload()
		self.assertEqual((pc.validated, pc.status), (1, "Paid"))
		self.assertEqual(self._gl(pc.journal_entry), {(self.advance, SUPPLIER): 1000000.0, (self.expense, None): 16500.0, (bank, None): -1016500.0})
		self.assertIn("Unpaid", run_action([pc.name], "void")["failed"][0]["error"])
		# Don't Post to GL: paid without a journal, so nothing for a payment to draw on.
		quiet = self._kasbon(200000, dont_post_to_gl=1)
		run_action([quiet.name], "pay")
		quiet.reload()
		self.assertEqual((quiet.status, quiet.journal_entry), ("Paid", None))
		self.assertNotIn(quiet.name, [r["name"] for r in pe_mod.get_kasbon(company=self.company)])
		# Confidential: hidden from a list or a URL for anyone but its maker and Finance.
		quiet.db_set("confidential", 1)
		self.assertIn("confidential = 0", pc_mod.get_permission_query_conditions("nobody@example.com"))
		self.assertFalse(pc_mod.has_permission(quiet, user="nobody@example.com"))

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

	# ---- The erp_cakra form: Bank, the user's amount, rounding, Dont Post To GL ----------
	def _bank(self):
		if frappe.db.exists("Bank Account", "CFBANK 001 - CFTEST Bank"):
			return frappe.get_doc("Bank Account", "CFBANK 001 - CFTEST Bank")
		parent = frappe.db.get_value("Account", {"company": self.company, "is_group": 1, "account_type": "Bank"}, "name")
		account = frappe.get_doc({
			"doctype": "Account", "account_name": "CFBANK 001", "parent_account": parent, "company": self.company,
			"account_type": "Bank", "account_currency": "IDR",
		}).insert(ignore_permissions=True).name
		frappe.get_doc({"doctype": "Bank", "bank_name": "CFTEST Bank"}).insert(ignore_permissions=True)
		return frappe.get_doc({
			"doctype": "Bank Account", "account_name": "CFBANK 001", "bank": "CFTEST Bank", "is_company_account": 1,
			"company": self.company, "account": account,
		}).insert(ignore_permissions=True)

	def _receipt(self, si, **kw):
		return frappe.get_doc({
			"doctype": "Payment Entry", "payment_type": "Receive", "company": self.company,
			"party_type": "Customer", "party": CUSTOMER, "paid_to": kw.pop("paid_to", None) or (None if kw.get("depot_bank") else self.cash),
			"depot_lines": [{"document_type": "Sales Invoice", "document_no": si.name, "outstanding": 1000000, "amount": 1000000}],
			**kw,
		}).insert()

	def test_the_bank_picks_the_account_and_a_surplus_stays_unallocated(self):
		ba = self._bank()
		si = self._invoice([{"item_code": "Lift On", "qty": 1, "rate": 1000000}])
		si.submit()
		rv = self._receipt(si, depot_bank="CFTEST Bank", paid_amount=1200000, depot_remark_note="Setoran PO 88")
		# The Bank's company account is the bank side, and names the number.
		self.assertEqual((rv.paid_to, rv.bank_account), (ba.account, ba.name))
		self.assertTrue(rv.name.startswith("RV-CFBANK-"), rv.name)
		# The typed amount stands; what the invoice does not take is ERPNext's own advance.
		self.assertEqual((flt(rv.unallocated_amount), flt(rv.difference_amount)), (200000.0, 0.0))
		self.assertEqual((rv.remarks, flt(rv.depot_bank_amount)), ("Setoran PO 88", 1200000.0))

	def test_a_tail_under_a_rupiah_is_booked_as_rounding(self):
		si = self._invoice([{"item_code": "Lift On", "qty": 1, "rate": 1000000}])
		si.submit()
		rv = self._receipt(si, paid_amount=999999.5)
		rounding = [d for d in rv.deductions if d.description == pe_mod.ROUNDING]
		self.assertEqual([flt(d.amount) for d in rounding], [0.5])
		self.assertEqual(flt(rv.difference_amount), 0.0)
		rv.submit()
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", si.name, "outstanding_amount")), 0.0)

	def test_dont_post_to_gl_leaves_the_invoice_outstanding(self):
		si = self._invoice([{"item_code": "Lift On", "qty": 1, "rate": 1000000}])
		si.submit()
		rv = self._receipt(si, depot_dont_post_to_gl=1)
		rv.submit()
		self.assertFalse(frappe.db.exists("GL Entry", {"voucher_no": rv.name}))
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", si.name, "outstanding_amount")), 1000000.0)

	def test_an_advance_on_a_purchase_order_is_erpnexts_own(self):
		po = frappe.get_doc({
			"doctype": "Purchase Order", "supplier": SUPPLIER, "company": self.company, "transaction_date": today(),
			"schedule_date": today(), "items": [{"item_code": "Lift On", "qty": 1, "rate": 2000000, "schedule_date": today()}],
		}).insert()
		po.submit()
		pe = frappe.get_doc({
			"doctype": "Payment Entry", "payment_type": "Pay", "company": self.company, "party_type": "Supplier",
			"party": SUPPLIER, "paid_from": self.cash, "depot_advance": [{"purchase_order": po.name, "allocated": 500000}],
		}).insert()
		self.assertEqual(flt(pe.paid_amount), 500000.0)
		self.assertEqual([(r.reference_doctype, flt(r.allocated_amount)) for r in pe.references], [("Purchase Order", 500000.0)])
		pe.submit()
		self.assertEqual(flt(frappe.db.get_value("Purchase Order", po.name, "advance_paid")), 500000.0)
		# An advance is the whole payment: no invoice lines beside it.
		pe2 = frappe.get_doc({
			"doctype": "Payment Entry", "payment_type": "Pay", "company": self.company, "party_type": "Supplier",
			"party": SUPPLIER, "depot_advance": [{"purchase_order": po.name}],
			"depot_lines": [{"document_type": "Purchase Invoice", "document_no": "PINV-X", "amount": 1}],
		})
		self.assertRaisesRegex(frappe.ValidationError, "tidak bisa digabung", pe_mod._apply_advance, pe2)

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
