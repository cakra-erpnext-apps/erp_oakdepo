"""Phase 8 (B2) tests: new doctypes + Release DO container-status flow."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from container_depot.tests.test_api import ensure_test_customer


class TestB2Doctypes(FrappeTestCase):
	def test_new_doctypes_exist(self):
		for dt in (
			"Surveyor Company",
			"Customer Portal User",
			"Survey Request",
			"Release DO",
			"Release DO Item",
			"Shipping Line",
		):
			self.assertTrue(frappe.db.exists("DocType", dt), f"{dt} missing")

	def test_inspection_surveyor_company_link(self):
		f = frappe.get_meta("Inspection").get_field("surveyor_company")
		self.assertEqual(f.fieldtype, "Link")
		self.assertEqual(f.options, "Surveyor Company")

	def test_booking_shipping_line_is_link(self):
		f = frappe.get_meta("Isotank Booking").get_field("shipping_line")
		self.assertEqual(f.fieldtype, "Link")
		self.assertEqual(f.options, "Shipping Line")


class TestReleaseDOFlow(FrappeTestCase):
	CONTAINER_NO = "RDOU8880001"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.customer = ensure_test_customer("B2 Release Customer")

	def _make_container(self, status):
		if frappe.db.exists("Container", self.CONTAINER_NO):
			frappe.db.delete("Container Movement", {"container": self.CONTAINER_NO})
			frappe.delete_doc("Container", self.CONTAINER_NO, force=True, ignore_permissions=True)
		return frappe.get_doc({
			"doctype": "Container",
			"container_no": self.CONTAINER_NO,
			"container_type": "ISO Tank",
			"status": status,
			"principal": self.customer,
		}).insert(ignore_permissions=True)

	def _make_rdo(self):
		return frappe.get_doc({
			"doctype": "Release DO",
			"tank_owner": self.customer,
			"status": "Issued",
			"release_date": today(),
			"shipper": "PT Test Shipper",
			"containers": [{"container": self.CONTAINER_NO, "seal": "S-001", "cargo_weight": 1000}],
		})

	def tearDown(self):
		frappe.db.delete("Release DO Item", {"container": self.CONTAINER_NO})
		frappe.db.delete("Release DO", {"tank_owner": self.customer})
		frappe.db.delete("Container Movement", {"container": self.CONTAINER_NO})
		frappe.db.delete("Container", {"container_no": self.CONTAINER_NO})
		frappe.db.commit()

	def test_release_flow_issued_then_picked_up(self):
		self._make_container("Ready_For_Release")
		rdo = self._make_rdo()
		rdo.insert(ignore_permissions=True)
		rdo.submit()
		self.assertEqual(
			frappe.db.get_value("Container", self.CONTAINER_NO, "status"),
			"Released_Pending_Pickup",
		)
		rdo.reload()
		rdo.status = "Picked Up"
		rdo.save(ignore_permissions=True)
		self.assertEqual(
			frappe.db.get_value("Container", self.CONTAINER_NO, "status"),
			"Gate_Out",
		)

	def test_release_blocks_ineligible_container(self):
		self._make_container("Available")
		rdo = self._make_rdo()
		with self.assertRaises(frappe.ValidationError):
			rdo.insert(ignore_permissions=True)
