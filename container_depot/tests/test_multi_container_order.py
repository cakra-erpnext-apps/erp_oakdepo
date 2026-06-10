"""Tests for multi-container bon/voucher generation.

One booking (single direction) can spawn several Order Bongkar / Order Muat,
each carrying up to 3 of its still-pending containers, via the shared atomic
core ``operations.order_generation.make_order``.
"""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime, today, add_days

from container_depot.api import (
	generate_order_from_booking,
	get_booking_pending_containers,
)
from container_depot.operations.order_generation import make_order
from container_depot.operations.doctype.booking_code.booking_code import generate_code
from container_depot.tests.test_api import ensure_test_customer

MC_CUSTOMER = "MultiContainer Test Customer"


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


def _booking_with_codes(*, code_direction, count, prefix, state="Active", offset_hours=24, containers=None):
	"""Create a Confirmed booking + ``count`` Booking Codes (one per container).

	The parent booking is always Tank In to dodge Tank-Out gating; each Booking
	Code carries its own ``code_direction`` (that's what the order path checks).
	"""
	customer = ensure_test_customer(MC_CUSTOMER)
	contract = (
		frappe.db.get_value("Depot Contract", {"customer": customer, "status": "Active"}, "name")
		or _make_contract(customer)
	)
	# Container numbers must be 11 chars (ISO). Force a 7-char base + 4-digit suffix.
	base = (prefix + "XXXXXXX")[:7]
	cno = lambda i: f"{base}{i:04d}"
	booking = frappe.get_doc({
		"doctype": "Container Booking",
		"direction": "Tank In",
		"customer": customer,
		"contract": contract,
		"booking_status": "Confirmed",
		"items": [{"container_no": cno(i)} for i in range(1, count + 1)],
	}).insert(ignore_permissions=True)
	codes = []
	for i in range(1, count + 1):
		code = frappe.get_doc({
			"doctype": "Booking Code",
			"code": generate_code(),
			"booking": booking.name,
			"direction": code_direction,
			"container_no": cno(i),
			"container": containers[i - 1] if containers else None,
			"state": state,
			"issued_at": now_datetime(),
			"expires_at": add_to_date(now_datetime(), hours=offset_hours),
		}).insert(ignore_permissions=True)
		codes.append(code.name)
	return booking.name, codes


def _states(codes):
	return [frappe.db.get_value("Booking Code", c, "state") for c in codes]


class TestMakeOrderCore(FrappeTestCase):
	def test_multi_happy_path(self):
		booking, codes = _booking_with_codes(code_direction="Tank In", count=2, prefix="MCBKR0")
		name = make_order(booking, codes)
		order = frappe.get_doc("Order Bongkar", name)
		self.assertEqual(len(order.containers), 2)
		self.assertEqual(order.booking, booking)
		# Shipper defaults to the booking customer.
		self.assertEqual(order.shipper, frappe.db.get_value("Container Booking", booking, "customer"))
		# Containers carry exactly the selected codes.
		self.assertEqual(sorted(r.booking_code for r in order.containers), sorted(codes))
		# All codes consumed.
		self.assertEqual(_states(codes), ["Used", "Used"])

	def test_rejects_more_than_2(self):
		booking, codes = _booking_with_codes(code_direction="Tank In", count=3, prefix="MCMAX0")
		with self.assertRaises(frappe.ValidationError):
			make_order(booking, codes)
		self.assertEqual(_states(codes), ["Active"] * 3)
		self.assertFalse(frappe.db.exists("Order Bongkar", {"booking": booking}))

	def test_rejects_container_not_in_booking(self):
		booking_a, codes_a = _booking_with_codes(code_direction="Tank In", count=2, prefix="MCSCA0")
		_booking_b, codes_b = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCSCB0")
		with self.assertRaises(frappe.ValidationError):
			make_order(booking_a, [codes_a[0], codes_b[0]])
		self.assertEqual(_states([codes_a[0], codes_b[0]]), ["Active", "Active"])

	def test_rejects_used_code(self):
		booking, codes = _booking_with_codes(
			code_direction="Tank In", count=1, prefix="MCUSED", state="Used"
		)
		with self.assertRaises(frappe.ValidationError):
			make_order(booking, codes)

	def test_rejects_expired_code(self):
		booking, codes = _booking_with_codes(
			code_direction="Tank In", count=1, prefix="MCEXP0", state="Active", offset_hours=-1
		)
		with self.assertRaises(frappe.ValidationError):
			make_order(booking, codes)

	def test_no_double_issue(self):
		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCDBL0")
		make_order(booking, codes)
		self.assertEqual(_states(codes), ["Used"])
		with self.assertRaises(frappe.ValidationError):
			make_order(booking, codes)

	def test_remaining_containers_reusable(self):
		booking, codes = _booking_with_codes(code_direction="Tank In", count=3, prefix="MCRMN0")
		make_order(booking, [codes[0]])
		pending = get_booking_pending_containers(booking)
		pending_codes = sorted(p["booking_code"] for p in pending)
		self.assertEqual(pending_codes, sorted(codes[1:]))
		# The remaining two go on a second bon.
		name = make_order(booking, codes[1:])
		self.assertEqual(len(frappe.get_doc("Order Bongkar", name).containers), 2)
		self.assertEqual(_states(codes), ["Used", "Used", "Used"])

	def test_partial_failure_atomic_rollback(self):
		booking, codes = _booking_with_codes(code_direction="Tank In", count=2, prefix="MCATM0")
		with self.assertRaises(frappe.ValidationError):
			make_order(booking, [codes[0], codes[1], "OAK-DOES-NOT-EXIST"])
		# Nothing consumed, nothing created.
		self.assertEqual(_states(codes), ["Active", "Active"])
		self.assertFalse(frappe.db.exists("Order Bongkar", {"booking": booking}))

	def test_submit_generated_bon(self):
		# The bon's own codes are Used (consumed by it); submit must NOT re-reject them.
		booking, codes = _booking_with_codes(code_direction="Tank In", count=2, prefix="MCSUB0")
		order = frappe.get_doc("Order Bongkar", make_order(booking, codes))
		order.submit()
		self.assertEqual(order.docstatus, 1)
		self.assertEqual(_states(codes), ["Used", "Used"])

	def test_cancel_releases_codes(self):
		booking, codes = _booking_with_codes(code_direction="Tank In", count=2, prefix="MCCNL0")
		order = frappe.get_doc("Order Bongkar", make_order(booking, codes))
		order.submit()
		order.cancel()
		self.assertEqual(_states(codes), ["Active", "Active"])

	def test_revise_add_and_remove(self):
		booking, codes = _booking_with_codes(code_direction="Tank In", count=3, prefix="MCRV0")
		order = frappe.get_doc("Order Bongkar", make_order(booking, [codes[0]]))
		# Add a second container to the draft bon -> consumed.
		order.append("containers", {"booking_code": codes[1]})
		order.save()
		self.assertEqual(frappe.db.get_value("Booking Code", codes[1], "state"), "Used")
		# Remove the first container -> released back to Active for another voucher.
		order.containers = [r for r in order.containers if r.booking_code != codes[0]]
		order.save()
		self.assertEqual(frappe.db.get_value("Booking Code", codes[0], "state"), "Active")
		self.assertEqual(frappe.db.get_value("Booking Code", codes[1], "state"), "Used")


class TestMakeOrderMuat(FrappeTestCase):
	CONTAINERS = ["MCMUAT00001", "MCMUAT00002"]

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		customer = ensure_test_customer(MC_CUSTOMER)
		cls.certs = {}
		for cno in cls.CONTAINERS:
			if not frappe.db.exists("Container", cno):
				frappe.get_doc({
					"doctype": "Container",
					"container_no": cno,
					"container_type": "ISO Tank",
					"status": "Ready_For_Service",
					"principal": customer,
				}).insert(ignore_permissions=True)
			cert = frappe.get_doc({
				"doctype": "Cleaning Certificate",
				"container": cno,
				"clean_date": now_datetime(),
				"cleaning_method": "Hot Water",
			})
			cert.insert(ignore_permissions=True)
			cert.submit()
			cls.certs[cno] = cert.name

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()

	def test_muat_requires_cert_per_row(self):
		booking, codes = _booking_with_codes(
			code_direction="Tank Out", count=2, prefix="MCMT0", containers=self.CONTAINERS
		)
		# No certs supplied -> rejected.
		with self.assertRaises(frappe.ValidationError):
			make_order(booking, codes)
		self.assertEqual(_states(codes), ["Active", "Active"])

	def test_muat_with_valid_certs(self):
		booking, codes = _booking_with_codes(
			code_direction="Tank Out", count=2, prefix="MCMV0", containers=self.CONTAINERS
		)
		vd = {"cleaning_certificates": {codes[0]: self.certs[self.CONTAINERS[0]],
									   codes[1]: self.certs[self.CONTAINERS[1]]}}
		name = make_order(booking, codes, vehicle_data=vd)
		order = frappe.get_doc("Order Muat", name)
		self.assertEqual(len(order.containers), 2)
		self.assertEqual(_states(codes), ["Used", "Used"])

	def test_muat_rejects_cert_for_wrong_container(self):
		booking, codes = _booking_with_codes(
			code_direction="Tank Out", count=2, prefix="MCMW0", containers=self.CONTAINERS
		)
		# Swap the certs so each row's cert is for the OTHER container.
		vd = {"cleaning_certificates": {codes[0]: self.certs[self.CONTAINERS[1]],
									   codes[1]: self.certs[self.CONTAINERS[0]]}}
		with self.assertRaises(frappe.ValidationError):
			make_order(booking, codes, vehicle_data=vd)
		self.assertEqual(_states(codes), ["Active", "Active"])


class TestGenerateOrderFromBookingAPI(FrappeTestCase):
	def test_dms_wrapper_creates_bon(self):
		booking, codes = _booking_with_codes(code_direction="Tank In", count=2, prefix="MCDMS0")
		result = generate_order_from_booking(
			booking,
			json.dumps(codes),
			vehicle_data=json.dumps({"truck_plate": "B-1234-AA", "driver": "Budi"}),
		)
		self.assertTrue(result["success"])
		self.assertEqual(result["order_doctype"], "Order Bongkar")
		order = frappe.get_doc("Order Bongkar", result["order_name"])
		self.assertEqual(len(order.containers), 2)
		# Truck / driver now live per-row (Container Booking Item), applied to every row.
		self.assertTrue(all(r.truck_plate == "B-1234-AA" for r in order.containers))
		self.assertTrue(all(r.driver == "Budi" for r in order.containers))
		self.assertEqual(_states(codes), ["Used", "Used"])

	def test_bongkar_writes_back_detail_to_booking(self):
		# Generating a bon updates the booking's own container line with the voucher detail.
		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCWB0")
		make_order(
			booking, codes,
			vehicle_data={"truck_plate": "B-9-XY", "driver": "Andi", "tanggal_bongkar": today()},
		)
		cno = frappe.db.get_value("Booking Code", codes[0], "container_no")
		item = frappe.db.get_value(
			"Container Booking Item", {"parent": booking, "container_no": cno},
			["truck_plate", "driver"], as_dict=True,
		)
		self.assertEqual(item.truck_plate, "B-9-XY")
		self.assertEqual(item.driver, "Andi")

	def test_bongkar_actual_unload_date_on_header(self):
		# The generate dialog's "Tanggal Bongkar" (actual) lands on the Order Bongkar header.
		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCAD0")
		name = make_order(
			booking, codes,
			vehicle_data={"tanggal_bongkar": today(), "tanggal_bongkar_actual": "2026-07-01"},
		)
		self.assertEqual(str(frappe.db.get_value("Order Bongkar", name, "tanggal_bongkar")), "2026-07-01")

	def test_bongkar_actual_date_defaults_to_estimation(self):
		# With no explicit actual date, the header falls back to the row's estimation.
		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCAE0")
		name = make_order(booking, codes, vehicle_data={"tanggal_bongkar": "2026-07-02"})
		self.assertEqual(str(frappe.db.get_value("Order Bongkar", name, "tanggal_bongkar")), "2026-07-02")

	def test_order_bongkar_carries_booking_principal(self):
		# The voucher inherits the booking's Principal (Tank Owner) on its header.
		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCPR0")
		principal = frappe.db.get_value("Container Booking", booking, "principal")
		name = make_order(booking, codes)
		self.assertTrue(principal)
		self.assertEqual(frappe.db.get_value("Order Bongkar", name, "principal"), principal)

	def test_manual_container_add_resolves_booking_code(self):
		# A grid row added by Container (booking_code left blank) back-resolves the
		# container's Active Booking Code on this voucher's booking.
		container = frappe.get_doc({
			"doctype": "Container", "container_no": "MCMAN000099",
			"container_type": "ISO Tank", "status": "Available",
		}).insert(ignore_permissions=True).name
		booking, codes = _booking_with_codes(
			code_direction="Tank In", count=1, prefix="MCMAN0", containers=[container],
		)
		order = frappe.get_doc({
			"doctype": "Order Bongkar",
			"booking": booking,
			"order_status": "Issued",
			"containers": [{"container": container}],
		})
		order.insert(ignore_permissions=True)
		self.assertEqual(order.containers[0].booking_code, codes[0])

	def test_pending_query_scoped_to_booking(self):
		# The manual picker only surfaces containers with an Active code on THIS booking.
		from container_depot.operations.doctype.order_bongkar.order_bongkar import (
			pending_container_query,
		)
		c1 = frappe.get_doc({
			"doctype": "Container", "container_no": "MCPQ0000001",
			"container_type": "ISO Tank", "status": "Available",
		}).insert(ignore_permissions=True).name
		b1, _ = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCPQA0", containers=[c1])
		c2 = frappe.get_doc({
			"doctype": "Container", "container_no": "MCPQ0000002",
			"container_type": "ISO Tank", "status": "Available",
		}).insert(ignore_permissions=True).name
		_booking_with_codes(code_direction="Tank In", count=1, prefix="MCPQB0", containers=[c2])
		names = [r[0] for r in pending_container_query(
			"Container", "", "name", 0, 20, {"booking": b1},
		)]
		self.assertIn(c1, names)
		self.assertNotIn(c2, names)

	def test_cancel_draft_releases_codes(self):
		# Cancelling a DRAFT bon frees its codes (Used -> Active) and marks it Cancelled,
		# so the containers can be put on a fresh voucher.
		from container_depot.operations.doctype.order_bongkar.order_bongkar import cancel_order
		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCCD0")
		name = make_order(booking, codes)
		self.assertEqual(_states(codes), ["Used"])
		cancel_order(name)
		self.assertEqual(_states(codes), ["Active"])
		self.assertEqual(frappe.db.get_value("Order Bongkar", name, "docstatus"), 2)

	def test_cancel_submitted_releases_codes(self):
		# A submitted bon can still be cancelled; on_cancel releases its codes.
		from container_depot.operations.doctype.order_bongkar.order_bongkar import cancel_order
		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCCS0")
		name = make_order(booking, codes)
		frappe.get_doc("Order Bongkar", name).submit()
		self.assertEqual(_states(codes), ["Used"])
		cancel_order(name)
		self.assertEqual(_states(codes), ["Active"])
		self.assertEqual(frappe.db.get_value("Order Bongkar", name, "docstatus"), 2)

	def test_order_bongkar_cannot_be_deleted(self):
		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCDL0")
		name = make_order(booking, codes)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Order Bongkar", name)

	def test_pending_excludes_used_and_expired(self):
		booking, codes = _booking_with_codes(code_direction="Tank In", count=3, prefix="MCPND0")
		# Consume one, expire another by flipping state.
		make_order(booking, [codes[0]])
		frappe.db.set_value("Booking Code", codes[1], "state", "Expired", update_modified=False)
		pending = get_booking_pending_containers(booking)
		self.assertEqual([p["booking_code"] for p in pending], [codes[2]])
