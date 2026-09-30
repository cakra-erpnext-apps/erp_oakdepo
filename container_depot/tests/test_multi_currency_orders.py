"""One order, two currencies: billed on ONE invoice, the other currency converted.

A cleaning order and an M&R price each of their rows in the currency that row's tariff line
states, so a single order can carry both USD and IDR work. A run bills it onto one invoice:
each line keeps its own currency and price and is converted into the invoice's through its
kurs to IDR. Runs used to raise one invoice per currency; the user dropped that on
2026-09-28 because two invoices for one bill were easy to get wrong.

The order's ``sales_invoice`` link still cannot say on its own whether an order is billed
(the preview can tick one currency of an order alone), so that is read off the live rollback
manifests (``consolidated_billing._billed_pairs``). These tests pin the one invoice on the
way in, and a rollback that gives the order back whole.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, today

from container_depot import consolidated_billing as cb
from container_depot import invoicing
from container_depot import monthly_invoicing as mi
from container_depot.tests.finance_fixture import require_finance
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_container_booking import (
	_cleanup_customer_world,
	_make_active_contract,
)

CUSTOMER = "Multi Currency Billing Co"
PREFIX = "MCURU"
SERVICE_ITEM = "MCUR-TEST-SERVICE"


def _purge(customer):
	"""Everything these tests create, including the invoices they raise."""
	containers = frappe.get_all("Container", filters={"container_no": ("like", f"{PREFIX}%")}, pluck="name")
	repairs = frappe.get_all("Repair Order", filters={"container": ("in", containers or [""])}, pluck="name")
	orders = frappe.get_all("Cleaning Order", filters={"container": ("in", containers or [""])}, pluck="name")
	frappe.db.delete("Repair Used Item", {"parent": ("in", repairs or [""])})
	frappe.db.delete("Repair Order", {"name": ("in", repairs or [""])})
	frappe.db.delete("Cleaning Order Service", {"parent": ("in", orders or [""])})
	frappe.db.delete("Cleaning Order", {"name": ("in", orders or [""])})
	for log in ("Container Movement", "Container Activity", "Storage Charge"):
		frappe.db.delete(log, {"container": ("in", containers or [""])})
	frappe.db.delete("Container", {"name": ("in", containers or [""])})
	for si in frappe.get_all("Sales Invoice", filters={"customer": customer}, pluck="name"):
		for child in ("Sales Invoice Item", "Sales Taxes and Charges", "Payment Schedule", "Item Wise Tax Detail"):
			frappe.db.delete(child, {"parent": si})
		# A submitted-then-cancelled invoice leaves its journal behind.
		for ledger in ("GL Entry", "Payment Ledger Entry"):
			frappe.db.delete(ledger, {"voucher_no": si})
		frappe.db.delete("Sales Invoice", {"name": si})
	frappe.db.commit()


class TestOneOrderTwoCurrencies(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		require_finance(cls)
		cls.customer = ensure_test_customer(CUSTOMER)
		_purge(cls.customer)
		# Cleaning and M&R only accrue for a credit (TOP) customer — see _collect.
		if not frappe.db.exists("Depot Contract", {"customer": cls.customer, "status": "Active"}):
			_make_active_contract(
				cls.customer, payment_type="TOP", credit_limit=1_000_000_000, payment_terms="NET 30"
			)
		if not frappe.db.exists("Item", SERVICE_ITEM):
			frappe.get_doc({
				"doctype": "Item", "item_code": SERVICE_ITEM, "item_name": "Multi Currency Test Service",
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups",
				"stock_uom": "Nos", "is_stock_item": 0, "is_sales_item": 1,
			}).insert(ignore_permissions=True)

	def tearDown(self):
		_purge(self.customer)
		super().tearDown()

	@classmethod
	def tearDownClass(cls):
		_purge(cls.customer)
		# The contract (and the price list it published) outlives the per-class rollback
		# because _purge commits — take it back out rather than leaving it on the site.
		_cleanup_customer_world(cls.customer)
		if frappe.db.exists("Item", SERVICE_ITEM):
			frappe.delete_doc("Item", SERVICE_ITEM, force=True, ignore_permissions=True)
		frappe.db.delete("Notification Log", {"subject": ["like", f"%{CUSTOMER}%"]})  # "Kontrak baru …"
		frappe.db.delete("Customer", {"name": cls.customer})  # last: everything above hangs off it
		frappe.db.commit()
		super().tearDownClass()

	# ---- fixtures -------------------------------------------------------
	def _container(self, no):
		doc = frappe.get_doc({
			"doctype": "Container", "container_no": f"{PREFIX}{no}", "container_type": "ISO Tank",
			"status": "Available", "principal": self.customer,
		})
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		return doc.name

	def _cleaning(self, container, priced):
		"""A completed cleaning order carrying ``[(currency, rate), ...]``.

		The currency is passed on the ROW: the controller seeds a blank one from the contract
		and never overwrites a filled one, so what is written here is what the order keeps.
		"""
		doc = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "Completed",
			"cleaning_end": today(),
			"cleaning_services": [
				{"cleaning_item": SERVICE_ITEM, "quantity": 1, "rate": rate, "currency": ccy}
				for ccy, rate in priced
			],
		})
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		frappe.db.set_value(
			"Cleaning Order", doc.name, {"status": "Completed", "cleaning_end": today()},
			update_modified=False,
		)
		return doc.name

	def _repair(self, container, priced):
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": container, "status": "Draft",
			"billing_status": "Unbilled",
			"used_items": [
				{"item": SERVICE_ITEM, "quantity": 1, "item_rate": rate, "currency": ccy}
				for ccy, rate in priced
			],
		})
		ro.flags.ignore_mandatory = True
		ro.insert(ignore_permissions=True)
		frappe.db.set_value("Repair Order", ro.name, {
			"status": "Completed", "billing_status": "Unbilled",
			"completion_date": today(), "principal": self.customer,
		}, update_modified=False)
		return ro.name

	def _bill(self, **kw):
		"""One run at a fixed kurs, so no test depends on today's Currency Exchange."""
		out = cb.fill_invoice(self.customer, kurs={"USD": 16000}, **kw)["invoices"]
		self.assertLessEqual(len(out), 1, "one run, one invoice")
		return frappe.get_doc("Sales Invoice", out[0]) if out else None

	# ---- one invoice ----------------------------------------------------
	def test_mixed_cleaning_order_bills_one_invoice(self):
		order = self._cleaning(self._container("0000001"), [("USD", 160), ("IDR", 100000)])

		si = self._bill()
		# Two currencies on the order: the invoice is in the company's, each line keeps its own.
		self.assertEqual(si.currency, "IDR")
		self.assertEqual(
			sorted((r.depot_currency, flt(r.depot_price), flt(r.rate)) for r in si.items),
			[("IDR", 100000.0, 100000.0), ("USD", 160.0, 2560000.0)],
		)
		self.assertIsNone(self._bill(), "the sweep is idempotent")
		self.assertEqual(frappe.db.get_value("Cleaning Order", order, "sales_invoice"), si.name)

	def test_the_invoice_type_decides_which_orders_bill(self):
		self._cleaning(self._container("0000009"), [("IDR", 100000)])
		self.assertIsNone(self._bill(categories=["M&R"]), "an M&R invoice offers no cleaning")
		self.assertEqual(self._bill(categories=["Cleaning"]).depot_invoice_type, "Cleaning")

	def test_the_pick_list_shows_order_tank_and_date(self):
		container = self._container("0000010")
		order = self._cleaning(container, [("IDR", 100000)])
		rows = [r for s in cb.preview_bill(self.customer, categories=["Cleaning"])["sections"] for r in s["rows"]]
		# Gabungan: the client's null arrives as "" and means every type.
		self.assertEqual(cb.preview_bill(self.customer, categories="")["total_orders"], 1)
		self.assertEqual(
			[(r["doctype"], r["name"], r["tank"], str(r["date"])) for r in rows],
			[("Cleaning Order", order, container, today())],
		)

	def test_the_form_header_travels_with_the_pick(self):
		"""Picking from an unsaved form raises a new invoice: what the form said must survive."""
		self._cleaning(self._container("0000011"), [("IDR", 100000)])
		branch = frappe.db.get_value("Branch", {}, "name")
		si = self._bill(categories=["Cleaning"], header={
			"depot_invoice_type": "Gabungan", "posting_date": today(), "branch": branch,
		})
		self.assertEqual((si.depot_invoice_type, si.branch, str(si.posting_date)), ("Gabungan", branch, today()))

	def test_picking_again_edits_the_same_invoice(self):
		"""One invoice, many orders: a re-pick adds and drops orders on THIS draft."""
		first = self._cleaning(self._container("0000012"), [("IDR", 100000)])
		si = self._bill(categories=["Cleaning"])
		second = self._cleaning(self._container("0000013"), [("IDR", 50000)])
		rows = {
			r["name"]: r
			for s in cb.preview_bill(self.customer, categories=["Cleaning"], sales_invoice=si.name)["sections"]
			for r in s["rows"]
		}
		self.assertEqual({n: r.get("on_invoice") for n, r in rows.items()}, {first: 1, second: None})

		keys = [rows[first]["key"], rows[second]["key"]]
		self.assertEqual(self._bill(categories=["Cleaning"], keys=keys, sales_invoice=si.name).name, si.name)
		self.assertEqual(sorted(flt(r.depot_price) for r in frappe.get_doc("Sales Invoice", si.name).items), [50000, 100000])
		self.assertEqual(frappe.db.get_value("Cleaning Order", second, "sales_invoice"), si.name)

		self._bill(categories=["Cleaning"], keys=[rows[second]["key"]], sales_invoice=si.name)
		self.assertEqual([flt(r.depot_price) for r in frappe.get_doc("Sales Invoice", si.name).items], [50000])
		self.assertFalse(frappe.db.get_value("Cleaning Order", first, "sales_invoice"), "the dropped order goes back")

		# The pick may move the draft into another currency: the IDR line converts at the kurs.
		si = self._bill(categories=["Cleaning"], keys=[rows[second]["key"]], sales_invoice=si.name, currency="USD")
		self.assertEqual((si.currency, flt(si.conversion_rate)), ("USD", 16000))
		self.assertAlmostEqual(flt(si.items[0].rate), 50000 / 16000, places=2)

	def test_cancelling_the_submitted_invoice_gives_the_order_back(self):
		order = self._cleaning(self._container("0000010"), [("IDR", 100000)])
		si = self._bill()
		si.branch = si.branch or frappe.db.get_value("Branch", {}, "name")
		si.save()
		si.submit()
		si.cancel()
		self.assertFalse(frappe.db.get_value("Cleaning Order", order, "sales_invoice"))
		self.assertEqual(len(self._bill().items), 1, "the order bills again")

	def test_mixed_repair_order_bills_one_invoice(self):
		self._repair(self._container("0000002"), [("USD", 25), ("IDR", 400000)])

		si = self._bill()
		self.assertEqual(sorted(flt(r.rate) for r in si.items), [400000.0, 400000.0])
		self.assertEqual({r.depot_currency for r in si.items}, {"USD", "IDR"})

	def test_a_single_currency_run_is_billed_in_that_currency(self):
		self._cleaning(self._container("0000003"), [("USD", 160)])
		si = self._bill()
		self.assertEqual((si.currency, [flt(r.rate) for r in si.items]), ("USD", [160.0]))

	def test_a_foreign_receivable_decides_the_currency(self):
		"""ERPNext refuses any other currency once the customer's receivable is foreign."""
		self._cleaning(self._container("0000008"), [("IDR", 160000)])
		with patch.object(invoicing, "locked_currency", lambda customer, company=None: "USD"):
			si = self._bill(currency="IDR")
		self.assertEqual((si.currency, [flt(r.rate) for r in si.items]), ("USD", [10.0]))

	# ---- the monthly (Cash-customer) path -------------------------------
	def test_monthly_run_bills_through_the_same_builder_and_marks_the_order(self):
		"""The monthly run uses Ambil Tagihan's own collector and invoice builder, so what it
		bills lands on a manifest and the next run finds nothing left.

		Driven through ``_collect`` + ``bill_units`` rather than ``generate_monthly_invoices``,
		which walks EVERY tank owner on the site.
		"""
		order = self._cleaning(self._container("0000005"), [("USD", 160), ("IDR", 100000)])
		day = mi.getdate(today())

		def mine():
			return [
				u for u in cb._collect(self.customer, ("Cleaning",), day, day, accrual=True)
				if u["sources"][0]["name"] == order
			]

		out = cb.bill_units(self.customer, mine(), "Tagihan bulanan Cleaning (test)", kurs={"USD": 16000})
		self.assertEqual(len(out["invoices"]), 1)
		self.assertEqual(mine(), [], "a billed order is on a manifest: the next run skips it")

	# ---- the chosen currency --------------------------------------------
	def test_one_invoice_in_the_chosen_currency_converts_the_rest(self):
		"""Billed in USD: the IDR line is converted through the kurs, the USD line is as-is."""
		self._cleaning(self._container("0000006"), [("USD", 160), ("IDR", 100000)])
		si = self._bill(currency="USD")
		self.assertEqual(si.currency, "USD")
		self.assertEqual(sorted(flt(r.rate) for r in si.items), [6.25, 160.0])

		# The lines mirror the order: they cannot be edited on the invoice.
		si.items[0].qty = 3
		self.assertRaises(frappe.ValidationError, si.save)

	def test_discarding_the_invoice_returns_the_order_to_unbilled(self):
		order = self._cleaning(self._container("0000004"), [("USD", 160), ("IDR", 100000)])
		si = self._bill()
		frappe.delete_doc("Sales Invoice", si.name, ignore_permissions=True)

		self.assertFalse(
			frappe.db.get_value("Cleaning Order", order, "sales_invoice"),
			"nothing bills it any more, so the link is cleared",
		)
		self.assertEqual(len(self._bill().items), 2, "the whole order is billable again")

	def test_frappe_discard_gives_the_order_back_too(self):
		"""Discard voids a draft without on_cancel; the orders must not stay billed to it."""
		order = self._cleaning(self._container("0000012"), [("IDR", 100000)])
		si = self._bill()
		si.discard()
		self.assertFalse(frappe.db.get_value("Cleaning Order", order, "sales_invoice"))
		self.assertFalse(frappe.db.get_value("Sales Invoice", si.name, "depot_billed_sources"))
		self.assertEqual(len(self._bill().items), 1, "billable again")

	def test_the_sources_tab_lists_the_order_and_its_tank(self):
		container = self._container("0000007")
		order = self._cleaning(container, [("USD", 160), ("IDR", 100000)])
		frappe.db.set_value("Cleaning Order", order, "reff_doc", "CUST-PO-7")
		si = self._bill()
		self.assertEqual(
			cb.invoice_sources(si.name),
			[{"doctype": "Cleaning Order", "name": order, "tank": container, "amounts": {"USD": 160.0, "IDR": 100000.0},
				"reff_doc": "CUST-PO-7"}],
		)
		# Every line of it carries the customer's reference too.
		self.assertEqual({r.depot_reff_doc for r in si.items}, {"CUST-PO-7"})
