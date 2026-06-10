"""Phase 4 tests: SST, Order Bongkar/Muat, re-pointed Gate Entry,
Cleaning Cert validity, status-trail hook via Container Movement,
and SST Activity Log append-only enforcement.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, now_datetime, today

from container_depot.api import sst_issue_order, sst_heartbeat, upload_inspection_offline_batch
from container_depot.operations.doctype.booking_code.booking_code import generate_code
from container_depot.tests.test_api import ensure_test_customer


P4_CUSTOMER = "Phase4 Test Customer"
P4_CONTAINER_NO = "TSTU4445550"
P4_TERMINAL = "SST-TEST-01"
P4_USER = "sst-test@example.com"


def _make_contract(customer):
	return frappe.get_doc({
		"doctype": "Depot Contract",
		"customer": customer,
		"currency": "IDR",
		"status": "Active",
		"payment_type": "Cash",
		"valid_from": today(),
		"valid_to": add_days(today(), 365),
		"tariff_lines": [{"item": "Lift Off", "rate": 250000}],
	}).insert(ignore_permissions=True).name


def _make_booking_code(*, direction, container_no, container=None, state="Active", offset_hours=24):
	"""Create a fresh booking + code per call.

	Inlining the booking (rather than caching it across tests) avoids stale
	names after FrappeTestCase rolls back per-test transactions.
	"""
	customer = ensure_test_customer(P4_CUSTOMER)
	contract_name = (
		frappe.db.get_value("Depot Contract", {"customer": customer, "status": "Active"}, "name")
		or _make_contract(customer)
	)
	# Always use Tank In for the parent booking to dodge Tank-Out gating —
	# the Booking Code carries its own direction and that's what SST checks.
	booking = frappe.get_doc({
		"doctype": "Container Booking",
		"direction": "Tank In",
		"customer": customer,
		"contract": contract_name,
		"booking_status": "Confirmed",
		"items": [{"container_no": container_no}],
	}).insert(ignore_permissions=True)
	return frappe.get_doc({
		"doctype": "Booking Code",
		"code": generate_code(),
		"booking": booking.name,
		"direction": direction,
		"container_no": container_no,
		"container": container,
		"state": state,
		"issued_at": now_datetime(),
		"expires_at": add_to_date(now_datetime(), hours=offset_hours),
	}).insert(ignore_permissions=True)


class TestStatusTrail(FrappeTestCase):
	"""Container.on_update writes a Container Movement audit row when status changes."""

	CONTAINER_NO = "TSTU4440001"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		customer = ensure_test_customer("Phase4 Status Trail Customer")
		if not frappe.db.exists("Container", cls.CONTAINER_NO):
			frappe.get_doc({
				"doctype": "Container",
				"container_no": cls.CONTAINER_NO,
				"container_type": "ISO Tank",
				"status": "Available",
				"principal": customer,
			}).insert(ignore_permissions=True)
		cls.container = cls.CONTAINER_NO

	@classmethod
	def tearDownClass(cls):
		frappe.db.delete("Container Movement", {"container": cls.container})
		frappe.db.delete("Container", {"container_no": cls.container})
		frappe.db.commit()
		super().tearDownClass()

	def test_status_change_writes_movement(self):
		before = frappe.db.count("Container Movement", {"container": self.container, "event_type": "Status"})
		c = frappe.get_doc("Container", self.container)
		c.status = "Inspecting"
		c.save(ignore_permissions=True)
		after = frappe.db.count("Container Movement", {"container": self.container, "event_type": "Status"})
		self.assertEqual(after, before + 1)
		latest = frappe.get_all(
			"Container Movement",
			filters={"container": self.container, "event_type": "Status"},
			fields=["from_status", "to_status"],
			order_by="creation desc",
			limit_page_length=1,
		)[0]
		self.assertEqual(latest["to_status"], "Inspecting")

	def test_no_status_change_no_movement(self):
		c = frappe.get_doc("Container", self.container)
		c.last_cargo = "Methanol"  # non-status edit
		before = frappe.db.count("Container Movement", {"container": self.container, "event_type": "Status"})
		c.save(ignore_permissions=True)
		after = frappe.db.count("Container Movement", {"container": self.container, "event_type": "Status"})
		self.assertEqual(after, before)

	def test_yard_movement_does_not_spawn_status_movement(self):
		# Direct Container.save inside Movement.after_insert must not recurse.
		c = frappe.get_doc("Container", self.container)
		c.status = "Gate_In"
		c.save(ignore_permissions=True)
		status_before = frappe.db.count("Container Movement", {"container": self.container, "event_type": "Status"})
		frappe.get_doc({
			"doctype": "Container Movement",
			"container": self.container,
			"event_type": "Yard",
			"to_zone": "Storage_Yard_A",
		}).insert(ignore_permissions=True)
		status_after = frappe.db.count("Container Movement", {"container": self.container, "event_type": "Status"})
		# Yard event should not create a *new* Status event.
		self.assertEqual(status_after, status_before)


class TestSSTIssueOrder(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Test user holding the SST service role + linked terminal.
		if not frappe.db.exists("User", P4_USER):
			frappe.get_doc({
				"doctype": "User",
				"email": P4_USER,
				"first_name": "SST",
				"last_name": "Tester",
				"send_welcome_email": 0,
				"roles": [{"role": "Container Depot SST Service"}],
			}).insert(ignore_permissions=True)
		if not frappe.db.exists("Self Service Terminal", P4_TERMINAL):
			frappe.get_doc({
				"doctype": "Self Service Terminal",
				"terminal_id": P4_TERMINAL,
				"gate_location": "Gate A (Test)",
				"api_user": P4_USER,
			}).insert(ignore_permissions=True)
		# Seed a ready Container + valid cleaning cert (used by Tank Out test).
		customer = ensure_test_customer("Phase4 SST Customer")
		if not frappe.db.exists("Container", P4_CONTAINER_NO):
			frappe.get_doc({
				"doctype": "Container",
				"container_no": P4_CONTAINER_NO,
				"container_type": "ISO Tank",
				"status": "Available",
				"principal": customer,
			}).insert(ignore_permissions=True)
		if not frappe.db.exists("Cleaning Certificate", {"container": P4_CONTAINER_NO, "docstatus": 1}):
			cert = frappe.get_doc({
				"doctype": "Cleaning Certificate",
				"container": P4_CONTAINER_NO,
				"clean_date": now_datetime(),
				"cleaning_method": "Hot Water",
			})
			cert.insert(ignore_permissions=True)
			cert.submit()

	@classmethod
	def tearDownClass(cls):
		frappe.db.delete("Order Bongkar", {"sst": P4_TERMINAL})
		frappe.db.delete("Order Muat", {"sst": P4_TERMINAL})
		frappe.db.delete("SST Activity Log", {"sst": P4_TERMINAL})
		frappe.db.delete("Self Service Terminal", {"terminal_id": P4_TERMINAL})
		frappe.db.delete("Cleaning Certificate", {"container": P4_CONTAINER_NO})
		frappe.db.delete("Container", {"container_no": P4_CONTAINER_NO})
		super().tearDownClass()

	def _as_sst_user(self, fn):
		orig = frappe.session.user
		try:
			frappe.set_user(P4_USER)
			return fn()
		finally:
			frappe.set_user(orig)

	def test_issue_order_bongkar(self):
		code = _make_booking_code(direction="Tank In", container_no="TANK0001001")
		result = self._as_sst_user(lambda: sst_issue_order(
			qr_data=f"OAK|{code.name}",
			truck_plate="B-1234-XYZ",
			driver_name="Pak Driver",
		))
		self.assertEqual(result["order_doctype"], "Order Bongkar")
		# Booking code flipped to Used.
		self.assertEqual(frappe.db.get_value("Booking Code", code.name, "state"), "Used")
		# SST activity row written.
		logs = frappe.get_all(
			"SST Activity Log",
			filters={"sst": P4_TERMINAL, "booking_code": code.name, "action": "Order Issued"},
		)
		self.assertEqual(len(logs), 1)

	def test_issue_order_muat_requires_cleaning_cert(self):
		code = _make_booking_code(
			direction="Tank Out",
			container_no=P4_CONTAINER_NO,
			container=P4_CONTAINER_NO,
		)
		with self.assertRaises(frappe.ValidationError):
			self._as_sst_user(lambda: sst_issue_order(qr_data=f"OAK|{code.name}"))

	def test_issue_order_muat_with_valid_cert(self):
		code = _make_booking_code(
			direction="Tank Out",
			container_no=P4_CONTAINER_NO,
			container=P4_CONTAINER_NO,
		)
		cert = frappe.db.get_value(
			"Cleaning Certificate",
			{"container": P4_CONTAINER_NO, "docstatus": 1},
			"name",
		)
		result = self._as_sst_user(lambda: sst_issue_order(
			qr_data=f"OAK|{code.name}",
			truck_plate="B-9999-XYZ",
			cleaning_certificate=cert,
			destination="Surabaya",
		))
		self.assertEqual(result["order_doctype"], "Order Muat")

	def test_issue_order_rejects_expired_code(self):
		code = _make_booking_code(
			direction="Tank In",
			container_no="TANK0001002",
			state="Expired",
			offset_hours=-1,
		)
		with self.assertRaises(frappe.ValidationError):
			self._as_sst_user(lambda: sst_issue_order(qr_data=f"OAK|{code.name}"))

	def test_heartbeat_updates_terminal(self):
		from frappe.utils import get_datetime
		orig_last = frappe.db.get_value("Self Service Terminal", P4_TERMINAL, "last_heartbeat")
		self._as_sst_user(lambda: sst_heartbeat(printer_status="OK"))
		new_last = frappe.db.get_value("Self Service Terminal", P4_TERMINAL, "last_heartbeat")
		self.assertIsNotNone(new_last)
		if orig_last:
			self.assertGreaterEqual(get_datetime(new_last), get_datetime(orig_last))


class TestOfflineEIRBatch(FrappeTestCase):
	"""Phase-7 endpoint promoted to Phase 4: offline batch dedups by client_uuid."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.container_no = "TSTU7770001"
		if not frappe.db.exists("Container", cls.container_no):
			frappe.get_doc({
				"doctype": "Container",
				"container_no": cls.container_no,
				"container_type": "ISO Tank",
				"status": "Available",
				"principal": ensure_test_customer("Phase4 Offline EIR Customer"),
			}).insert(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		frappe.db.delete("Inspection", {"container_no": cls.container_no})
		frappe.db.delete("Container", {"container_no": cls.container_no})
		super().tearDownClass()

	def test_offline_batch_dedupes(self):
		items = [
			{
				"client_uuid": "uuid-a",
				"container_no": self.container_no,
				"inspection_type": "EIR-In",
				"photos": [{"view": "Front"}],
			},
			{
				"client_uuid": "uuid-a",  # duplicate
				"container_no": self.container_no,
				"inspection_type": "EIR-In",
				"photos": [{"view": "Back"}],
			},
			{
				"client_uuid": "uuid-b",
				"container_no": self.container_no,
				"inspection_type": "EIR-In",
				"photos": [{"view": "Front"}],
			},
		]
		res = upload_inspection_offline_batch(items=items)
		self.assertTrue(res["success"])
		self.assertEqual(len(res["created"]), 2)
		# Re-submitting the same batch must add zero new inspections.
		res2 = upload_inspection_offline_batch(items=items)
		self.assertEqual(len(res2["created"]), 0)
		self.assertGreaterEqual(len(res2["skipped"]), 2)


class TestGateEntryBookingCodePath(FrappeTestCase):
	"""Gate Entry: an Active/Used Booking Code clears the gate; other states are rejected."""

	def test_gate_entry_with_active_booking_code(self):
		code = _make_booking_code(direction="Tank In", container_no="TANK0002001")
		ge = frappe.get_doc({
			"doctype": "Gate Entry",
			"booking_code": code.name,
			"container_no": "TANK0002001",
			"gate_in_timestamp": now_datetime(),
			"inspection_status": "Pending",
		})
		ge.insert(ignore_permissions=True)
		ge.submit()
		self.assertEqual(ge.status, "Gate_In_Completed")

	def test_gate_entry_rejects_expired_booking_code(self):
		code = _make_booking_code(
			direction="Tank In",
			container_no="TANK0002002",
			state="Expired",
			offset_hours=-1,
		)
		ge = frappe.get_doc({
			"doctype": "Gate Entry",
			"booking_code": code.name,
			"container_no": "TANK0002002",
			"gate_in_timestamp": now_datetime(),
			"inspection_status": "Pending",
		})
		with self.assertRaises(frappe.ValidationError):
			ge.insert(ignore_permissions=True)


class TestSSTActivityLogAppendOnly(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.terminal = "SST-APPEND-01"
		if not frappe.db.exists("Self Service Terminal", cls.terminal):
			frappe.get_doc({
				"doctype": "Self Service Terminal",
				"terminal_id": cls.terminal,
				"gate_location": "Gate A (Append-Only Test)",
			}).insert(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		frappe.db.delete("SST Activity Log", {"sst": cls.terminal})
		frappe.db.delete("Self Service Terminal", {"terminal_id": cls.terminal})
		super().tearDownClass()

	def test_non_admin_cannot_edit_log_row(self):
		row = frappe.get_doc({
			"doctype": "SST Activity Log",
			"sst": self.terminal,
			"action": "Heartbeat",
			"result": "OK",
			"timestamp": now_datetime(),
			"payload_json": "{}",
		}).insert(ignore_permissions=True)

		# Pretend to be a non-SysMgr user by temporarily monkey-patching roles.
		orig_roles = frappe.get_roles

		def fake_roles(user=None):
			return ["Container Depot"]

		frappe.get_roles = fake_roles
		try:
			row.payload_json = "{\"tampered\": true}"
			with self.assertRaises(frappe.ValidationError):
				row.save(ignore_permissions=True)
		finally:
			frappe.get_roles = orig_roles
