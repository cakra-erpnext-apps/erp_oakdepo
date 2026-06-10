"""Tests for the PRD v0.2 gap-closure features:

§1 EIR Damage Code master (Damage Entry.damage_type -> Link)
§2 Canonical cleaning types (PP Wash / Methanol Rinse / Steam Wash)
§3 Depot master + depot field
§4 Periodic Test due-date + TANK OUT gating when overdue
§5 Container Leasing registry
§6 Inventory KPI per Principal report
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, getdate, now_datetime, today

from container_depot.operations.report.inventory_kpi_per_principal.inventory_kpi_per_principal import (
	execute as kpi_execute,
)
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_container_booking import (
	_cleanup_customer_world,
	_make_active_contract,
)

V02_CUSTOMER = "V02 Gap Customer"
V02_CONTAINER = "VGAP0000001"


def _ensure_depot(code="SUB", name="Surabaya", city="Surabaya"):
	if not frappe.db.exists("Depot", code):
		frappe.get_doc({
			"doctype": "Depot",
			"depot_code": code,
			"depot_name": name,
			"city": city,
			"is_active": 1,
		}).insert(ignore_permissions=True)
	return code


def _ensure_damage_code(code="11", description="Dented"):
	if not frappe.db.exists("EIR Damage Code", code):
		frappe.get_doc({
			"doctype": "EIR Damage Code",
			"code": code,
			"category": "Damage",
			"description": description,
			"is_active": 1,
		}).insert(ignore_permissions=True)
	return code


class TestDepotAndFields(FrappeTestCase):
	def test_depot_master_and_container_field(self):
		depot = _ensure_depot()
		# Container carries a depot Link.
		meta = frappe.get_meta("Container")
		self.assertIn("depot", [f.fieldname for f in meta.fields])
		self.assertEqual(meta.get_field("depot").options, "Depot")
		# Depot record is usable.
		self.assertTrue(frappe.db.exists("Depot", depot))


class TestCleaningCanonical(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Container", V02_CONTAINER):
			frappe.get_doc({
				"doctype": "Container",
				"container_no": V02_CONTAINER,
				"container_type": "ISO Tank",
				"status": "Available",
			}).insert(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		frappe.db.delete("Cleaning Certificate", {"container": V02_CONTAINER})
		frappe.db.delete("Container", {"container_no": V02_CONTAINER})
		frappe.db.commit()
		super().tearDownClass()

	def test_methanol_rinse_is_valid(self):
		cert = frappe.get_doc({
			"doctype": "Cleaning Certificate",
			"container": V02_CONTAINER,
			"clean_date": now_datetime(),
			"cleaning_method": "Methanol Rinse",
		})
		cert.insert(ignore_permissions=True)
		self.assertEqual(cert.cleaning_method, "Methanol Rinse")

	def test_legacy_steam_value_rejected(self):
		cert = frappe.get_doc({
			"doctype": "Cleaning Certificate",
			"container": V02_CONTAINER,
			"clean_date": now_datetime(),
			"cleaning_method": "Steam",  # legacy value, no longer in the Select
		})
		with self.assertRaises(frappe.ValidationError):
			cert.insert(ignore_permissions=True)


class TestEIRDamageCode(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_ensure_damage_code("11", "Dented")
		if not frappe.db.exists("Container", V02_CONTAINER):
			frappe.get_doc({
				"doctype": "Container",
				"container_no": V02_CONTAINER,
				"container_type": "ISO Tank",
				"status": "Available",
			}).insert(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		frappe.db.delete("Inspection", {"container_no": V02_CONTAINER})
		frappe.db.delete("Container", {"container_no": V02_CONTAINER})
		frappe.db.commit()
		super().tearDownClass()

	def _inspection(self, damage_code):
		return frappe.get_doc({
			"doctype": "Inspection",
			"container": V02_CONTAINER,
			"inspection_type": "Detailed Survey",
			"status": "Draft",
			"inspector": "Administrator",
			"has_damage": 1,
			"damage_log": [{
				"component": "Manlid",
				"damage_type": damage_code,
				"severity": "Minor",
				"damage_description": "test",
			}],
		})

	def test_valid_damage_code_links(self):
		insp = self._inspection("11")
		insp.insert(ignore_permissions=True)
		self.assertEqual(insp.damage_log[0].damage_type, "11")

	def test_unknown_damage_code_rejected(self):
		insp = self._inspection("NO_SUCH_CODE_XYZ")
		with self.assertRaises(frappe.ValidationError):
			insp.insert(ignore_permissions=True)


class TestPeriodicTest(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.customer = ensure_test_customer(V02_CUSTOMER)
		_cleanup_customer_world(cls.customer)
		cls.contract = _make_active_contract(cls.customer, payment_type="Cash")
		if not frappe.db.exists("Container", V02_CONTAINER):
			frappe.get_doc({
				"doctype": "Container",
				"container_no": V02_CONTAINER,
				"container_type": "ISO Tank",
				"status": "Available",
				"principal": cls.customer,
			}).insert(ignore_permissions=True)
		cls.container = V02_CONTAINER

	@classmethod
	def tearDownClass(cls):
		frappe.db.delete("Periodic Test", {"container": cls.container})
		_cleanup_customer_world(cls.customer)
		frappe.db.delete("Cleaning Certificate", {"container": cls.container})
		frappe.db.delete("Container", {"container_no": cls.container})
		frappe.db.commit()
		super().tearDownClass()

	def _valid_cleaning_cert(self):
		frappe.db.delete("Cleaning Certificate", {"container": self.container})
		cert = frappe.get_doc({
			"doctype": "Cleaning Certificate",
			"container": self.container,
			"clean_date": now_datetime(),
			"cleaning_method": "Hot Water",
		})
		cert.insert(ignore_permissions=True)
		cert.submit()  # valid_until defaults to today + 30

	def _tank_out_booking(self):
		return frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank Out",
			"customer": self.customer,
			"contract": self.contract,
			"booking_status": "Pending Confirmation",
			"items": [{"container": self.container}],
		})

	def test_due_date_auto_computed_and_pushed_to_container(self):
		pt = frappe.get_doc({
			"doctype": "Periodic Test",
			"container": self.container,
			"test_type": "2,5Y",
			"periodic_date": today(),
		})
		pt.insert(ignore_permissions=True)
		expected = getdate(add_to_date(getdate(today()), months=30))
		self.assertEqual(getdate(pt.due_date), expected)
		pt.submit()
		self.assertEqual(
			getdate(frappe.db.get_value("Container", self.container, "next_pt_due")),
			expected,
		)
		# cleanup for other tests in this class
		pt.cancel()
		frappe.db.set_value("Container", self.container, "next_pt_due", None, update_modified=False)

	def test_tank_out_blocked_when_pt_overdue(self):
		self._valid_cleaning_cert()
		frappe.db.set_value(
			"Container", self.container, "next_pt_due", add_days(today(), -1), update_modified=False
		)
		try:
			with self.assertRaises(frappe.ValidationError) as ctx:
				self._tank_out_booking().insert(ignore_permissions=True)
			self.assertIn("periodic test overdue", str(ctx.exception).lower())
		finally:
			frappe.db.set_value("Container", self.container, "next_pt_due", None, update_modified=False)

	def test_tank_out_ok_when_pt_future(self):
		self._valid_cleaning_cert()
		frappe.db.set_value(
			"Container", self.container, "next_pt_due", add_days(today(), 365), update_modified=False
		)
		try:
			b = self._tank_out_booking()
			b.insert(ignore_permissions=True)  # should NOT raise
			self.assertEqual(b.direction, "Tank Out")
		finally:
			frappe.db.set_value("Container", self.container, "next_pt_due", None, update_modified=False)


class TestContainerLeasing(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.customer = ensure_test_customer(V02_CUSTOMER)
		if not frappe.db.exists("Container", V02_CONTAINER):
			frappe.get_doc({
				"doctype": "Container",
				"container_no": V02_CONTAINER,
				"container_type": "ISO Tank",
				"status": "Available",
			}).insert(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		frappe.db.delete("Container Leasing", {"lessee": cls.customer})
		frappe.db.delete("Container", {"container_no": V02_CONTAINER})
		frappe.db.commit()
		super().tearDownClass()

	def test_active_lease_past_end_flagged_overdue(self):
		lease = frappe.get_doc({
			"doctype": "Container Leasing",
			"lessee": self.customer,
			"container": V02_CONTAINER,
			"status": "Active",
			"lease_start": add_days(today(), -120),
			"lease_end": add_days(today(), -1),
		})
		lease.insert(ignore_permissions=True)
		self.assertEqual(lease.status, "Overdue")


class TestKpiReport(FrappeTestCase):
	def test_report_executes(self):
		columns, data = kpi_execute({})
		fieldnames = [c["fieldname"] for c in columns]
		self.assertIn("principal", fieldnames)
		self.assertIn("stock_in_depo", fieldnames)
		self.assertIn("pp_wash", fieldnames)
		self.assertIsInstance(data, list)
