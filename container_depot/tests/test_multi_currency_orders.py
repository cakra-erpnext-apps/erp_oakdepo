"""One order, two currencies: billed as two sibling invoices, rolled back one at a time.

A cleaning order and an M&R price each of their rows in the currency that row's tariff line
states, so a single order can carry both USD and IDR work. An ERPNext Sales Invoice is
single-currency, so such an order cannot be one invoice — it becomes one PER CURRENCY, tied
together by the run's billing number.

What that costs is the assumption the sweep used to make: that an order's ``sales_invoice``
link answers "has this been billed". It cannot — it names one document — so the answer is
read off the live rollback manifests instead (``consolidated_billing._billed_pairs``). These
tests pin both halves of that: the split on the way in, and a rollback that gives back ONLY
the currency whose invoice went away.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, today

from container_depot import consolidated_billing as cb
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
	for log in ("Container Movement", "Container Activity"):
		frappe.db.delete(log, {"container": ("in", containers or [""])})
	frappe.db.delete("Container", {"name": ("in", containers or [""])})
	for si in frappe.get_all("Sales Invoice", filters={"customer": customer}, pluck="name"):
		frappe.db.delete("Sales Invoice Item", {"parent": si})
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

	def _invoices_by_currency(self, names):
		return {frappe.db.get_value("Sales Invoice", si, "currency"): si for si in names}

	# ---- the split ------------------------------------------------------
	def test_mixed_cleaning_order_bills_one_invoice_per_currency(self):
		order = self._cleaning(self._container("0000001"), [("USD", 160), ("IDR", 100000)])

		invoices = self._invoices_by_currency(cb.bill_customer(self.customer))
		self.assertEqual(set(invoices), {"USD", "IDR"}, "one invoice per currency of the order")

		# Each invoice carries ONLY its own currency's work, at face value — the USD line is
		# never re-read as 100000 rupiah, which is what a single invoice would have done.
		usd = frappe.get_doc("Sales Invoice", invoices["USD"])
		idr = frappe.get_doc("Sales Invoice", invoices["IDR"])
		self.assertEqual([flt(r.rate) for r in usd.items], [160.0])
		self.assertEqual([flt(r.rate) for r in idr.items], [100000.0])

		# Both invoices are one bill: the run ties them under a single billing number.
		groups = {frappe.db.get_value("Sales Invoice", si, cb.GROUP_FIELD) for si in invoices.values()}
		self.assertEqual(len(groups), 1, "sibling invoices share one billing number")

		# Nothing is left to bill, and a second run must not find the order again.
		self.assertEqual(cb.bill_customer(self.customer), [], "the sweep is idempotent")
		self.assertIn(
			frappe.db.get_value("Cleaning Order", order, "sales_invoice"), set(invoices.values()),
			"the order points at one of the invoices it is on",
		)

	def test_mixed_repair_order_bills_one_invoice_per_currency(self):
		self._repair(self._container("0000002"), [("USD", 25), ("IDR", 400000)])

		invoices = self._invoices_by_currency(cb.bill_customer(self.customer))
		self.assertEqual(set(invoices), {"USD", "IDR"})
		usd = frappe.get_doc("Sales Invoice", invoices["USD"])
		self.assertEqual([flt(r.rate) for r in usd.items], [25.0])

	# ---- the rollback ---------------------------------------------------
	def test_discarding_one_invoice_gives_back_only_that_currency(self):
		order = self._cleaning(self._container("0000003"), [("USD", 160), ("IDR", 100000)])
		invoices = self._invoices_by_currency(cb.bill_customer(self.customer))
		self.assertEqual(set(invoices), {"USD", "IDR"})

		frappe.delete_doc("Sales Invoice", invoices["USD"], ignore_permissions=True)

		# The order is still billed — the IDR invoice stands — so its link moves to the
		# survivor rather than being cleared. A cleared link would read as "never invoiced".
		self.assertEqual(
			frappe.db.get_value("Cleaning Order", order, "sales_invoice"), invoices["IDR"],
			"the order follows the invoice that is still standing",
		)

		# Re-running bills back the USD half ONLY. Billing the IDR half a second time is the
		# double-charge this whole mechanism exists to prevent.
		again = self._invoices_by_currency(cb.bill_customer(self.customer))
		self.assertEqual(set(again), {"USD"}, "only the rolled-back currency is billable again")
		self.assertEqual(
			[flt(r.rate) for r in frappe.get_doc("Sales Invoice", list(again.values())[0]).items],
			[160.0],
		)

	# ---- the monthly (Cash-customer) path -------------------------------
	def test_monthly_invoice_is_raised_once_per_currency(self):
		"""The scheduler's OAK Monthly Invoice splits the same way the TOP sweep does.

		Driven through the builder + writer rather than through
		``generate_monthly_invoices``, which walks EVERY tank owner on the site and would
		raise invoices for customers this test has nothing to do with.
		"""
		order = self._cleaning(self._container("0000005"), [("USD", 160), ("IDR", 100000)])
		items = mi._cleaning_items(self.customer, mi.getdate(today()), mi.getdate(today()))
		mine = [i for i in items if i["reference_name"] == order]
		self.assertEqual(
			{i["currency"] for i in mine}, {"USD", "IDR"},
			"each service line is tagged with the currency it was priced in",
		)

		created = {}
		for ccy in ("USD", "IDR"):
			name = mi.create_monthly_invoice(
				self.customer, "2026-09", "Cleaning", today(), today(),
				[i for i in mine if i["currency"] == ccy], ccy,
			)
			created[ccy] = frappe.get_doc("OAK Monthly Invoice", name)
		try:
			self.assertEqual(created["USD"].currency, "USD")
			self.assertEqual(flt(created["USD"].subtotal), 160.0)
			self.assertEqual(flt(created["IDR"].subtotal), 100000.0)
			# The currency is only a grouping key on the item dicts — it is not a column on
			# the child row, and writing it there would break the insert.
			self.assertTrue(all(not r.get("currency") for r in created["USD"].items))
		finally:
			for doc in created.values():
				frappe.db.delete("OAK Monthly Invoice Item", {"parent": doc.name})
				frappe.db.delete("OAK Monthly Invoice", {"name": doc.name})
			frappe.db.commit()

	def test_discarding_every_invoice_returns_the_order_to_unbilled(self):
		order = self._cleaning(self._container("0000004"), [("USD", 160), ("IDR", 100000)])
		invoices = self._invoices_by_currency(cb.bill_customer(self.customer))
		for si in invoices.values():
			frappe.delete_doc("Sales Invoice", si, ignore_permissions=True)

		self.assertFalse(
			frappe.db.get_value("Cleaning Order", order, "sales_invoice"),
			"nothing bills it any more, so the link is cleared",
		)
		self.assertEqual(
			set(self._invoices_by_currency(cb.bill_customer(self.customer))), {"USD", "IDR"},
			"the whole order is billable again",
		)
