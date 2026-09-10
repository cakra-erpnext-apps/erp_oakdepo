"""An order that prices out at ZERO must never become an invoice.

A free job is a real outcome — the depot did the work and decided not to charge for it —
not a missing price to be filled in from the tariff. Container Booking has always refused
to invoice a zero total (``ContainerBooking._billable_lines``); these tests pin the same
rule for the other categories, which is enforced once in
:func:`consolidated_billing._bills_something`:

* an M&R order whose parts are all free AND which books no labour bills nothing;
* the same order still bills when it books HOURS — labour is value even at rate 0;
* a cleaning order whose chosen services are all priced 0 bills nothing, and the contract's
  flat cleaning tariff is NOT substituted for that decision (an order that chose no service
  at all still falls back to it — that one is a missing price).
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from container_depot import consolidated_billing as cb
from container_depot.tests.finance_fixture import require_finance
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_container_booking import (
	_cleanup_customer_world,
	_make_active_contract,
)

CUSTOMER = "Zero Total Billing Co"
PREFIX = "ZEROU"
SERVICE_ITEM = "ZEROT-TEST-SERVICE"
WINDOW = ("2000-01-01 00:00:00", f"{today()} 23:59:59")


def _purge(customer):
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
	frappe.db.commit()


class TestZeroTotalOrdersAreNotBilled(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		require_finance(cls)
		cls.customer = ensure_test_customer(CUSTOMER)
		_purge(cls.customer)
		# M&R and cleaning only accrue for a credit (TOP) customer — see _collect.
		if not frappe.db.exists("Depot Contract", {"customer": cls.customer, "status": "Active"}):
			_make_active_contract(cls.customer, payment_type="TOP", credit_limit=1_000_000, payment_terms="NET 30")
		if not frappe.db.exists("Item", SERVICE_ITEM):
			frappe.get_doc({
				"doctype": "Item", "item_code": SERVICE_ITEM, "item_name": "Zero Total Test Service",
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

	def _repair(self, container, *, rate, manhour=0):
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": container, "status": "Draft",
			"billing_status": "Unbilled",
			"used_items": [{"item": SERVICE_ITEM, "quantity": 1, "item_rate": rate}],
		})
		ro.flags.ignore_mandatory = True
		ro.insert(ignore_permissions=True)
		if manhour:
			# ``calculate_totals`` seeds the row's hours from the ITEM master, so they cannot
			# be passed in — write them where the sweep reads them.
			frappe.db.set_value(
				"Repair Used Item", ro.used_items[0].name,
				{"manhour": manhour, "manhour_rate": 100000}, update_modified=False,
			)
		# Force the completed, unbilled state the sweep looks for (bypass the M&R workflow).
		frappe.db.set_value("Repair Order", ro.name, {
			"status": "Completed", "billing_status": "Unbilled",
			"completion_date": today(), "principal": self.customer,
		}, update_modified=False)
		return ro.name

	def _cleaning(self, container, services):
		doc = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "Completed",
			"cleaning_end": today(),
			"cleaning_services": [{"cleaning_item": SERVICE_ITEM, "rate": r} for r in services],
		})
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		frappe.db.set_value(
			"Cleaning Order", doc.name, {"status": "Completed", "cleaning_end": today()},
			update_modified=False,
		)
		return doc.name

	# ---- M&R ------------------------------------------------------------
	def test_repair_worth_nothing_is_not_swept(self):
		"""Free parts, no hours: nothing to bill, and the order stays Unbilled."""
		ro = self._repair(self._container("0000001"), rate=0)

		self.assertEqual(cb.bill_customer(self.customer), [], "no invoice for a free job")
		self.assertEqual(frappe.db.get_value("Repair Order", ro, "billing_status"), "Unbilled")
		self.assertFalse(frappe.db.get_value("Repair Order", ro, "sales_invoice"))

	def test_repair_that_books_only_labour_is_still_swept(self):
		"""A free part that took two hours is NOT a free job — the hours are the charge."""
		ro = self._repair(self._container("0000002"), rate=0, manhour=2)

		units = cb.collect_units(self.customer, ["M&R"])
		self.assertTrue(
			any(u["sources"][0]["name"] == ro for u in units),
			"labour alone keeps the order billable",
		)

	# ---- cleaning -------------------------------------------------------
	def test_cleaning_priced_to_zero_does_not_fall_back_to_the_tariff(self):
		"""Services were chosen and priced at 0 — a decision, not a missing price."""
		self._cleaning(self._container("0000003"), [0, 0])

		with patch.object(cb, "resolve_tariff_rate", return_value=500000):
			self.assertEqual(cb._cleaning_lines(self.customer, *WINDOW), [])

	def test_cleaning_with_no_service_still_falls_back_to_the_tariff(self):
		"""No service row at all: the contract tariff is the answer, as it always was."""
		self._cleaning(self._container("0000004"), [])

		with patch.object(cb, "resolve_tariff_rate", return_value=500000):
			units = cb._cleaning_lines(self.customer, *WINDOW)
		self.assertEqual(len(units), 1)
		self.assertEqual(units[0]["lines"][0]["rate"], 500000)
