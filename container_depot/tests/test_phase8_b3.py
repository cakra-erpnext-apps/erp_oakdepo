"""Phase 8 (B3) tests: pricing, auto-invoice, survey->M&R loop, re-cleaning,
portal-user provisioning."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, today

from container_depot import pricing
from container_depot.tests._booking_helpers import make_booking_code, make_contract
from container_depot.tests.test_api import ensure_test_customer


# --------------------------------------------------------------------------- #
# Pricing helper (deterministic, no accounting needed)
# --------------------------------------------------------------------------- #
class TestPricing(FrappeTestCase):
	def test_resolve_tariff_rate(self):
		customer = ensure_test_customer("B3 Pricing Customer")
		contract = make_contract(customer)  # has a Lift Off @ 250000 line
		self.assertEqual(pricing.resolve_tariff_rate(contract, "Lift Off"), 250000)
		self.assertEqual(pricing.resolve_tariff_rate(contract, "Nonexistent"), 0)

	def test_order_amount_uses_price_then_qty(self):
		order = frappe._dict({"quantity": 3, "price_per_container": 100000, "order_type": "Lift Off"})
		total, rate = pricing.order_amount(order)
		self.assertEqual((total, rate), (300000, 100000))


# NOTE: Order-level auto-invoicing was removed — the bon (Order Bongkar/Muat) is
# operational only. Lift on/off is billed at the booking (Cash at submit; TOP via
# consolidated_billing). See test_phase10 / test_phase8_b4 for booking-side billing.


# --------------------------------------------------------------------------- #
# Survey -> Container loop + M&R approval
# --------------------------------------------------------------------------- #
class TestSurveyLoop(FrappeTestCase):
	NO = "SRVU0009990"

	def setUp(self):
		self.customer = ensure_test_customer("B3 Survey Customer")

	def tearDown(self):
		frappe.db.rollback()

	def _container(self, status):
		return frappe.get_doc({
			"doctype": "Container",
			"container_no": self.NO,
			"container_type": "ISO Tank",
			"status": status,
			"principal": self.customer,
		}).insert(ignore_permissions=True)

	def _survey(self, **kw):
		doc = frappe.get_doc({
			"doctype": "Inspection",
			"inspection_type": "Detailed Survey",
			"status": "Submitted",
			"container": self.NO,
			"inspector": "Administrator",
			**kw,
		})
		doc.insert(ignore_permissions=True)
		doc.submit()
		return doc

	def test_clean_survey_issues_cert(self):
		self._container("Survey_In_Progress")
		self._survey(has_damage=0, tank_status="Empty Clean", seal_manhole="M-01")
		c = frappe.db.get_value("Container", self.NO, ["status", "certification_status", "seal_manhole"], as_dict=True)
		self.assertEqual(c.status, "Available")  # clean survey -> ready pool
		self.assertEqual(c.certification_status, "Completed")  # the "cert issued" fact lives here now
		self.assertEqual(c.seal_manhole, "M-01")  # surveyor seal carried over

	def test_dirty_survey_awaits_recleaning(self):
		self._container("Survey_In_Progress")
		self._survey(has_damage=0, tank_status="Empty Dirty")
		self.assertEqual(frappe.db.get_value("Container", self.NO, "status"), "Awaiting_Recleaning_Approval")

	def test_damage_survey_creates_repair_order_and_approval_flows(self):
		self._container("Survey_In_Progress")
		insp = self._survey(has_damage=1, tank_status="Empty Dirty")
		self.assertEqual(frappe.db.get_value("Container", self.NO, "status"), "Awaiting_MR_Approval")
		ro_name = frappe.db.get_value("Repair Order", {"inspection": insp.name}, "name")
		self.assertTrue(ro_name, "Repair Order not created from damaged survey")
		self.assertEqual(frappe.db.get_value("Repair Order", ro_name, "status"), "Pending Approval")
		# Tank Owner approves -> container moves to Repair_In_Progress.
		ro = frappe.get_doc("Repair Order", ro_name)
		ro.status = "Approved"
		ro.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Container", self.NO, "status"), "Repair_In_Progress")


# --------------------------------------------------------------------------- #
# Re-cleaning propagation
# --------------------------------------------------------------------------- #
class TestRecleaning(FrappeTestCase):
	NO = "RCLN0009990"

	def setUp(self):
		self.customer = ensure_test_customer("B3 Recleaning Customer")
		frappe.get_doc({
			"doctype": "Container",
			"container_no": self.NO,
			"container_type": "ISO Tank",
			"status": "Awaiting_Recleaning_Approval",
			"principal": self.customer,
		}).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()

	def test_recleaning_drives_container_states(self):
		co = frappe.get_doc({
			"doctype": "Cleaning Order",
			"container": self.NO,
			"status": "In_Progress",
			"approval_status": "Approved",
			"is_recleaning": 1,
			"cleaning_type": "Hot Water",
		})
		co.insert(ignore_permissions=True)
		co.submit()
		self.assertEqual(frappe.db.get_value("Container", self.NO, "status"), "Recleaning_In_Progress")
		co.status = "Completed"
		co.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Container", self.NO, "status"), "Cleaning_Completed")


# --------------------------------------------------------------------------- #
# Customer Portal User provisioning
# --------------------------------------------------------------------------- #
class TestPortalProvisioning(FrappeTestCase):
	USER = "b3-portal-user@example.com"

	def setUp(self):
		self.customer = ensure_test_customer("B3 Portal Customer")
		if not frappe.db.exists("User", self.USER):
			frappe.get_doc({
				"doctype": "User",
				"email": self.USER,
				"first_name": "B3 Portal",
				"send_welcome_email": 0,
			}).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.delete("Customer Portal User", {"user": self.USER})
		frappe.db.delete("User Permission", {"user": self.USER})
		frappe.db.delete("Has Role", {"parent": self.USER, "role": "Customer"})
		frappe.delete_doc("User", self.USER, force=True, ignore_permissions=True)
		frappe.db.commit()

	def test_active_portal_user_is_scoped_and_roled(self):
		frappe.get_doc({
			"doctype": "Customer Portal User",
			"customer": self.customer,
			"user": self.USER,
			"portal_role": "Admin",
			"approval_status": "Active",
		}).insert(ignore_permissions=True)
		self.assertTrue(
			frappe.db.exists(
				"User Permission",
				{"user": self.USER, "allow": "Customer", "for_value": self.customer},
			),
			"User Permission not created for active portal user",
		)
		self.assertTrue(
			frappe.db.exists("Has Role", {"parent": self.USER, "role": "Customer"}),
			"Customer role not granted to active portal user",
		)
