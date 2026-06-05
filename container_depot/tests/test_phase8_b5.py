"""Phase 8 (B5) tests: booking guards + auto-invoice, surveyor seed, customer
notifications."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot.tasks import notify_customers
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_isotank_booking import _make_active_contract, _cleanup_customer_world


class TestBookingGuards(FrappeTestCase):
	def setUp(self):
		self.customer = ensure_test_customer("B5 Guard Customer")
		_cleanup_customer_world(self.customer)
		self.contract = _make_active_contract(self.customer, payment_type="TOP", credit_limit=999_000_000, payment_terms="NET 30")

	def tearDown(self):
		_cleanup_customer_world(self.customer)
		frappe.db.rollback()

	def _booking(self, **kw):
		doc = {
			"doctype": "Isotank Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"contract": self.contract,
			"booking_status": "Pending Confirmation",
			"items": [{"container_no": "TANK0005551"}],
		}
		doc.update(kw)
		return frappe.get_doc(doc)

	def test_do_required_at_submit(self):
		# A draft can be saved without a DO; confirming (submit) needs one.
		b = self._booking()
		b.insert(ignore_permissions=True)  # draft saves fine
		with self.assertRaises(frappe.ValidationError):
			b.submit()

	def test_submit_ok_with_do(self):
		b = self._booking(do_reference="DO-123", do_document="/files/do.pdf")
		b.insert(ignore_permissions=True)
		b.submit()  # TOP huge credit + DO present
		self.assertEqual(b.docstatus, 1)
		self.assertTrue(frappe.db.exists("Booking Code", {"booking": b.name}))


class TestTopBookingAccrual(FrappeTestCase):
	"""B7: a TOP booking submits but does NOT create a per-transaction Sales
	Invoice — the charge accrues Unpaid for later consolidated billing."""

	def setUp(self):
		self.customer = ensure_test_customer("B5 BookInvoice Customer")
		_cleanup_customer_world(self.customer)
		self.contract = _make_active_contract(self.customer, payment_type="TOP", credit_limit=999_000_000, payment_terms="NET 30")

	def tearDown(self):
		_cleanup_customer_world(self.customer)
		frappe.db.rollback()

	def test_top_booking_accrues_without_invoice(self):
		b = frappe.get_doc({
			"doctype": "Isotank Booking",
			"direction": "Tank In",  # Tank In -> Lift Off @ 250000 tariff line
			"customer": self.customer,
			"contract": self.contract,
			"booking_status": "Pending Confirmation",
			"do_reference": "DO-AUTO",
			"do_document": "/files/do.pdf",
			"items": [{"container_no": "TANK0005552"}, {"container_no": "TANK0005553"}],
		})
		b.insert(ignore_permissions=True)
		b.submit()
		b.reload()
		self.assertFalse(b.sales_invoice, "TOP booking must not create a per-transaction invoice")
		self.assertEqual(b.payment_status, "Unpaid")
		self.assertTrue(frappe.db.exists("Booking Code", {"booking": b.name}))


class TestSurveyorSeed(FrappeTestCase):
	def test_surveyors_seeded(self):
		for name in ("PT Indomarine Survey", "PT Surveyor Indonesia", "PT Cipta Mitra Surveyor"):
			self.assertTrue(frappe.db.exists("Surveyor Company", name), f"{name} not seeded")


class TestCustomerNotifications(FrappeTestCase):
	NO = "NOTU0009991"
	USER = "b5-notify@example.com"

	def setUp(self):
		self.customer = ensure_test_customer("B5 Notify Customer")
		if not frappe.db.exists("User", self.USER):
			frappe.get_doc({"doctype": "User", "email": self.USER, "first_name": "Notify", "send_welcome_email": 0}).insert(ignore_permissions=True)
		frappe.get_doc({
			"doctype": "Customer Portal User",
			"customer": self.customer, "user": self.USER,
			"portal_role": "Finance", "approval_status": "Active",
		}).insert(ignore_permissions=True)
		frappe.get_doc({
			"doctype": "Container", "container_no": self.NO, "container_type": "ISO Tank",
			"status": "Awaiting_MR_Approval", "principal": self.customer,
		}).insert(ignore_permissions=True)
		self.ro = frappe.get_doc({
			"doctype": "Repair Order", "container": self.NO, "status": "Pending Approval", "billing_status": "Unbilled",
		}).insert(ignore_permissions=True).name

	def tearDown(self):
		frappe.db.delete("ToDo", {"reference_type": "Repair Order", "reference_name": self.ro})
		frappe.db.delete("Repair Order", {"name": self.ro})
		frappe.db.delete("Container Movement", {"container": self.NO})
		frappe.db.delete("Container", {"container_no": self.NO})
		frappe.db.delete("Customer Portal User", {"user": self.USER})
		frappe.db.delete("User Permission", {"user": self.USER})
		frappe.db.delete("Has Role", {"parent": self.USER, "role": "Customer"})
		frappe.delete_doc("User", self.USER, force=True, ignore_permissions=True)
		frappe.db.commit()

	def test_pending_mr_notifies_portal_user(self):
		notify_customers()
		self.assertTrue(
			frappe.db.exists("ToDo", {
				"reference_type": "Repair Order", "reference_name": self.ro,
				"allocated_to": self.USER, "status": "Open",
			}),
			"portal user not notified of pending M&R",
		)
		# Idempotent: a second run must not create a duplicate.
		notify_customers()
		self.assertEqual(
			frappe.db.count("ToDo", {"reference_type": "Repair Order", "reference_name": self.ro, "allocated_to": self.USER, "status": "Open"}),
			1,
		)
