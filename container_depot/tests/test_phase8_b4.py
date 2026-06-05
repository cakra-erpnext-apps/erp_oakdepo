"""Phase 8 (B4) tests: OAK Monthly Invoice totals/PPN, Sales Invoice generation,
and the monthly aggregation scheduler (M&R category + dup guard)."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_first_day, get_last_day, getdate

from container_depot.monthly_invoicing import generate_monthly_invoices
from container_depot.tests.test_api import ensure_test_customer

PERIOD = "2026-04"
MID = "2026-04-15"


def _tank_owner(name):
	customer = ensure_test_customer(name)
	frappe.db.set_value("Customer", customer, "oak_customer_type", "Tank Owner")
	return customer


class TestMonthlyInvoiceDoc(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_totals_and_ppn(self):
		customer = _tank_owner("B4 Doc Customer")
		doc = frappe.get_doc({
			"doctype": "OAK Monthly Invoice",
			"customer": customer,
			"category": "M&R",
			"period": PERIOD,
			"items": [
				{"description": "RO-1", "amount": 1_000_000},
				{"description": "RO-2", "amount": 500_000},
			],
		})
		doc.insert(ignore_permissions=True)
		self.assertEqual(doc.subtotal, 1_500_000)
		self.assertEqual(doc.ppn, 165_000)  # 11%
		self.assertEqual(doc.total, 1_665_000)

	def test_duplicate_period_blocked(self):
		customer = _tank_owner("B4 Dup Customer")
		base = {"doctype": "OAK Monthly Invoice", "customer": customer, "category": "Cleaning", "period": PERIOD,
				"items": [{"description": "x", "amount": 100}]}
		frappe.get_doc(dict(base)).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(dict(base)).insert(ignore_permissions=True)

	def test_submit_generates_sales_invoice_with_ppn(self):
		customer = _tank_owner("B4 SI Customer")
		doc = frappe.get_doc({
			"doctype": "OAK Monthly Invoice",
			"customer": customer,
			"category": "M&R",
			"period": PERIOD,
			"items": [{"description": "RO-1", "amount": 1_000_000}],
		})
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.reload()
		self.assertTrue(doc.sales_invoice, "no Sales Invoice generated")
		si = frappe.db.get_value(
			"Sales Invoice", doc.sales_invoice, ["net_total", "total_taxes_and_charges", "grand_total"], as_dict=True
		)
		self.assertEqual(si.net_total, 1_000_000)
		self.assertEqual(si.total_taxes_and_charges, 110_000)  # PPN 11% applied natively
		self.assertEqual(si.grand_total, 1_110_000)


class TestMonthlyScheduler(FrappeTestCase):
	NO = "MINV0009990"

	def setUp(self):
		self.customer = _tank_owner("B4 Scheduler Customer")
		frappe.get_doc({
			"doctype": "Container",
			"container_no": self.NO,
			"container_type": "ISO Tank",
			"status": "Repair_In_Progress",
			"principal": self.customer,
		}).insert(ignore_permissions=True)
		# A Completed Repair Order in the target month.
		ro = frappe.get_doc({
			"doctype": "Repair Order",
			"container": self.NO,
			"status": "Completed",
			"billing_status": "Unbilled",
			"completion_date": MID + " 10:00:00",
			"estimation_items": [{"quantity": 1, "unit_price": 750_000}],
		})
		ro.insert(ignore_permissions=True)
		self.ro = ro.name

	def tearDown(self):
		frappe.db.delete("OAK Monthly Invoice Item", {"reference_name": self.ro})
		frappe.db.delete("OAK Monthly Invoice", {"customer": self.customer})
		frappe.db.delete("Repair Order", {"name": self.ro})
		frappe.db.delete("Container Movement", {"container": self.NO})
		frappe.db.delete("Container", {"container_no": self.NO})
		frappe.db.commit()

	def test_scheduler_builds_mr_invoice_and_is_idempotent(self):
		created = generate_monthly_invoices(period=PERIOD)
		self.assertGreaterEqual(created, 1)
		mi = frappe.db.get_value(
			"OAK Monthly Invoice",
			{"customer": self.customer, "period": PERIOD, "category": "M&R"},
			["name", "subtotal", "from_date", "to_date"],
			as_dict=True,
		)
		self.assertTrue(mi, "M&R monthly invoice not created")
		self.assertEqual(mi.subtotal, 750_000)
		self.assertEqual(getdate(mi.from_date), get_first_day(getdate(MID)))
		self.assertEqual(getdate(mi.to_date), get_last_day(getdate(MID)))
		# Re-run must not duplicate.
		again = generate_monthly_invoices(period=PERIOD)
		self.assertEqual(
			frappe.db.count("OAK Monthly Invoice", {"customer": self.customer, "period": PERIOD, "category": "M&R"}),
			1,
		)
