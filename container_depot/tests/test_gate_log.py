"""Tests for the gate log — one Gate Entry spanning a tank's whole depot visit.

For a long time only the OUT half was ever written: the gate-out was the sole creator, so
"Riwayat Gate" listed nothing but departures and the reuse branch in
``gate._resolve_or_create_gate_entry`` had never fired. ``Order Bongkar._record_gate_in``
opens the record at arrival; these tests pin that one record covers both events, and that the
ways it could go wrong (a re-submitted bon, a cancelled bon, a second visit) each behave.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, now_datetime, today

from container_depot.container_depot.container_status import PRESENT
from container_depot.container_depot.doctype.booking_code.booking_code import generate_code
from container_depot.container_depot.gate import open_gate_entry_for
from container_depot.container_depot.order_generation import make_order
from container_depot.tests.test_api import ensure_test_branch, ensure_test_customer
from container_depot.tests.test_eir import _make_order_muat

PREFIX = "GLOG"
CUSTOMER = "Gate Log Test Customer"
DEPOT = "GLOG-DEP"


def _depot():
	if not frappe.db.exists("Depot", DEPOT):
		frappe.get_doc({
			"doctype": "Depot",
			"depot_code": DEPOT,
			"depot_name": "Gate Log Test Depot",
			"branch": ensure_test_branch(),
		}).insert(ignore_permissions=True)
	return DEPOT


def _contract(customer):
	return (
		frappe.db.get_value("Depot Contract", {"customer": customer, "status": "Active"}, "name")
		or frappe.get_doc({
			"doctype": "Depot Contract",
			"customer": customer,
			"currency": "IDR",
			"status": "Active",
			"payment_type": "Cash",
			"valid_from": today(),
			"valid_to": add_days(today(), 365),
			"tariff_lines": [{"item": "Lift Off", "rate": 250000}],
		}).insert(ignore_permissions=True).name
	)


def _container(no, status="Booked"):
	frappe.get_doc({
		"doctype": "Container",
		"container_no": no,
		"container_type": "ISO Tank",
		"status": status,
		"principal": ensure_test_customer(CUSTOMER),
	}).insert(ignore_permissions=True)
	return no


def _tank_in_bon(container_no, *, submit=True, vehicle=None):
	"""A submitted Tank In bon for one container — the arrival, as the gate records it.

	``vehicle``: the dict the PWA gate posts. Tank In names the driver ``driver`` (it goes
	on the container row); Tank Out uses ``driver_name`` on the header. See
	``order_generation.BONGKAR_ROW_DETAIL``."""
	customer = ensure_test_customer(CUSTOMER)
	booking = frappe.get_doc({
		"doctype": "Container Booking",
		"direction": "Tank In",
		"customer": customer,
		"contract": _contract(customer),
		"depot": _depot(),
		"booking_status": "Confirmed",
		"payment_status": "Paid",
		"items": [{"container_no": container_no}],
	}).insert(ignore_permissions=True)
	# Confirmed == submitted. Set docstatus directly rather than calling submit(), which
	# would auto-issue its own Booking Code and collide with the explicit one below.
	frappe.db.set_value("Container Booking", booking.name, "docstatus", 1, update_modified=False)
	frappe.db.sql("UPDATE `tabContainer Booking Item` SET docstatus=1 WHERE parent=%s", booking.name)
	code = frappe.get_doc({
		"doctype": "Booking Code",
		"code": generate_code(),
		"booking": booking.name,
		"direction": "Tank In",
		"container_no": container_no,
		"container": container_no,
		"state": "Active",
		"issued_at": now_datetime(),
		"expires_at": add_to_date(now_datetime(), hours=24),
	}).insert(ignore_permissions=True)
	return make_order(booking.name, [code.name], vehicle_data=vehicle, submit=submit)


def _drop_provisioned_eir_in(container):
	"""A Tank In bon auto-provisions a draft EIR-In. Any open order blocks gate-out, and this
	suite is about the gate log rather than the EIR flow — so clear it rather than work it."""
	frappe.db.delete("Inspection", {"container": container, "inspection_type": "EIR-In"})


def _clean_eir_out(container):
	"""Submit a clean EIR-Out — which IS the departure: ``Inspection.on_submit`` runs the
	gate-out, so there is nothing else for these tests to press.

	A loading bon is ensured first when the tank has none: since 2026-09-03 an EIR-Out cannot
	be submitted until one carries its tank (``Inspection.before_submit``). This suite is
	about the gate LOG, so the bon is setup rather than subject matter.
	"""
	from container_depot.container_depot import eir as _eir

	if not _eir.latest_voucher_for_container(container, "EIR-Out"):
		_make_order_muat(ensure_test_customer("Gate Log Shipper"), container)
	doc = frappe.new_doc("Inspection")
	doc.inspection_type = "EIR-Out"
	doc.container = container
	doc.inspector = frappe.session.user
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


class TestGateLog(FrappeTestCase):
	@classmethod
	def tearDownClass(cls):
		"""Yang berumur sepanjang kelas ikut dibuang: depot, kontrak (+ price list yang
		diterbitkannya) dan kedua customer uji. ``ensure_test_customer`` commit, jadi tanpa ini
		mereka menetap di site kerja dan menumpuk tiap kali suite dijalankan."""
		from container_depot.tests.test_container_booking import _cleanup_customer_world

		for name in (CUSTOMER, "Gate Log Shipper"):
			customer = frappe.db.get_value("Customer", {"customer_name": name})
			if not customer:
				continue
			_cleanup_customer_world(customer)
			frappe.delete_doc(
				"Customer", customer, force=True, ignore_permissions=True, delete_permanently=True
			)
		if frappe.db.exists("Depot", DEPOT):
			frappe.db.delete("Depot", {"name": DEPOT})
		frappe.db.commit()
		super().tearDownClass()

	def tearDown(self):
		conts = frappe.get_all("Container", filters={"name": ["like", f"{PREFIX}%"]}, pluck="name")
		gates = frappe.get_all("Gate Entry", filters={"container_no": ["like", f"{PREFIX}%"]}, pluck="name")
		if gates:
			frappe.db.delete("Comment", {"reference_doctype": "Gate Entry", "reference_name": ["in", gates]})
		frappe.db.delete("Gate Entry", {"container_no": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Container Activity", {"container": ["in", conts or [""]]})
		frappe.db.delete("Container Movement", {"container": ["in", conts or [""]]})
		frappe.db.delete("Inspection", {"container": ["in", conts or [""]]})
		# Bon + booking yang dibuat fixture, dicari lewat baris containernya sendiri — jadi
		# harus DIKUMPULKAN dulu, sebelum baris-baris itu ikut terhapus di bawah. Tanpa ini
		# setiap test meninggalkan satu bon dan satu booking yang menunjuk tank yang sudah
		# tidak ada, dan daftar Order Bongkar di site kerja penuh sampah uji.
		#
		# Perhatikan dua tabel anak yang berbeda: Container Booking DAN Order Bongkar
		# sama-sama memakai `Container Booking Item` (bedanya di `parenttype`), sementara
		# Order Muat punya `Order Container Item` sendiri. Menyamakan keduanya akan menghapus
		# baris bon tapi meninggalkan bonnya — persis bug yang pernah membuat daftar bon penuh
		# order tanpa container.
		rows = frappe.get_all(
			"Container Booking Item",
			filters={"container_no": ["like", f"{PREFIX}%"]},
			fields=["parent", "parenttype"],
		)
		muat = frappe.get_all(
			"Order Container Item",
			filters={"container_no": ["like", f"{PREFIX}%"]},
			fields=["parent", "parenttype"],
		)
		for doctype, parents in (
			("Order Bongkar", [r.parent for r in rows if r.parenttype == "Order Bongkar"]),
			("Order Muat", [r.parent for r in muat if r.parenttype == "Order Muat"]),
		):
			if parents:
				frappe.db.delete(doctype, {"name": ["in", parents]})
		bookings = [r.parent for r in rows if r.parenttype == "Container Booking"]
		if bookings:
			frappe.db.delete("Booking Code", {"booking": ["in", bookings]})
			frappe.db.delete("Container Booking Charge", {"parent": ["in", bookings]})
			frappe.db.delete("Container Booking", {"name": ["in", bookings]})
		frappe.db.delete("Container Booking Item", {"container_no": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Order Container Item", {"container_no": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Booking Code", {"container_no": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Container", {"name": ["like", f"{PREFIX}%"]})

	def _gates(self, container_no):
		return frappe.get_all(
			"Gate Entry",
			filters={"container_no": container_no},
			fields=["name", "status", "gate_in_timestamp", "gate_out_timestamp", "depot",
			        "order_doctype", "order_ref", "booking_code", "eir_reference",
			        "truck_plate", "driver_name"],
			order_by="creation asc",
		)

	def test_tank_in_opens_the_gate_record(self):
		"""The arrival half — the thing that never existed."""
		c = _container(f"{PREFIX}000001")
		bon = _tank_in_bon(c)

		rows = self._gates(c)
		self.assertEqual(len(rows), 1)
		ge = rows[0]
		self.assertEqual(ge.status, "Gate_In_Completed")
		self.assertTrue(ge.gate_in_timestamp)
		self.assertFalse(ge.gate_out_timestamp)
		self.assertEqual(ge.depot, DEPOT)
		self.assertEqual(ge.order_doctype, "Order Bongkar")
		self.assertEqual(ge.order_ref, bon)
		self.assertTrue(ge.booking_code)

	def test_arrival_writes_a_gate_in_activity(self):
		"""The count every "Tank masuk" tile reads.

		Container Activity is the single table every movement counter reads — the PWA home
		tile, the Desk monitor, and the days-in-depot fallback. The arrival never wrote to
		it: the Gate Entry this bon opens stays a DRAFT, so ``GateEntry.on_submit`` — the
		only writer of that row — never ran, and every bonned arrival counted zero while the
		rarely-used SST kiosk path counted.
		"""
		c = _container(f"{PREFIX}000010")
		bon = _tank_in_bon(c)

		rows = frappe.get_all(
			"Container Activity",
			filters={"container": c, "activity_type": "Gate In"},
			fields=["reference_doctype", "reference_name", "activity_time", "summary"],
		)
		self.assertEqual(len(rows), 1, "exactly one arrival row per visit")
		self.assertEqual(rows[0].reference_doctype, "Gate Entry")
		self.assertEqual(rows[0].reference_name, self._gates(c)[0].name)
		self.assertIn(bon, rows[0].summary)
		# Stamped with the gate log's own timestamp, so "today" can never disagree between
		# the timeline and Riwayat Gate.
		self.assertEqual(
			frappe.utils.get_datetime(rows[0].activity_time),
			frappe.utils.get_datetime(self._gates(c)[0].gate_in_timestamp),
		)

	def test_the_record_is_a_draft(self):
		"""Not an oversight — ``GateEntry.on_submit`` refuses a tank already in the depot,
		and ``_sync_container_arrival`` has just put it there. Submitting would throw on
		every single bon. The list view reads ``status`` instead of docstatus for this."""
		c = _container(f"{PREFIX}000002")
		_tank_in_bon(c)
		self.assertEqual(frappe.db.get_value("Gate Entry", {"container_no": c}, "docstatus"), 0)
		# PRESENT, not In_Depot specifically: arrival now settles on the computed state, so
		# a tank that lands with no open work reads Available. Either way it is in the
		# depot, which is what makes the Gate Entry unsubmittable.
		self.assertIn(frappe.db.get_value("Container", c, "status"), PRESENT)

	def test_one_record_spans_the_whole_visit(self):
		"""In and out land on the SAME row — the reuse branch that had never fired."""
		c = _container(f"{PREFIX}000003")
		_tank_in_bon(c)
		opened = open_gate_entry_for(c)
		self.assertTrue(opened)

		_drop_provisioned_eir_in(c)
		frappe.db.set_value("Container", c, "status", "Available", update_modified=False)
		eir = _clean_eir_out(c)

		rows = self._gates(c)
		self.assertEqual(rows[0].name, opened, "gate-out filed a second record")
		self.assertEqual(len(rows), 1)
		ge = rows[0]
		self.assertEqual(ge.status, "Gate_Out_Completed")
		self.assertTrue(ge.gate_in_timestamp)
		self.assertTrue(ge.gate_out_timestamp)
		self.assertLessEqual(ge.gate_in_timestamp, ge.gate_out_timestamp)
		# eir_reference used to be a field nothing ever wrote.
		self.assertEqual(ge.eir_reference, eir)

	def test_a_second_visit_gets_its_own_record(self):
		"""The one-open-record invariant is per visit, not per tank — a tank that comes
		back must not have its closed record reopened."""
		c = _container(f"{PREFIX}000004")
		_tank_in_bon(c)
		_drop_provisioned_eir_in(c)
		frappe.db.set_value("Container", c, "status", "Available", update_modified=False)
		_clean_eir_out(c)
		self.assertIsNone(open_gate_entry_for(c))

		_tank_in_bon(c)  # comes back
		self.assertEqual(len(self._gates(c)), 2)

	def test_a_re_submitted_bon_does_not_duplicate(self):
		"""Cancel → amend → submit is routine. It must not file a second arrival for a
		tank that never left."""
		c = _container(f"{PREFIX}000005")
		_tank_in_bon(c)
		self.assertEqual(len(self._gates(c)), 1)

		# A second bon on a tank still standing in the yard — same open visit.
		_container(f"{PREFIX}000006")
		_tank_in_bon(c)
		self.assertEqual(len(self._gates(c)), 1)

	def test_cancelling_the_bon_voids_the_arrival(self):
		"""Kept, not deleted: Riwayat Gate is an audit log. Cancelled closes the visit, so
		the tank can open a fresh record if it arrives again."""
		c = _container(f"{PREFIX}000007")
		bon = _tank_in_bon(c)
		frappe.get_doc("Order Bongkar", bon).cancel()

		rows = self._gates(c)
		self.assertEqual(len(rows), 1, "the record is voided, never removed")
		self.assertEqual(rows[0].status, "Cancelled")
		self.assertIsNone(open_gate_entry_for(c))

	def test_the_arrival_records_the_truck_and_driver(self):
		"""Riwayat Gate reads truck + driver off the Gate Entry, and for a long time nothing
		wrote them — every row showed "—" while the plate the guard typed sat on the bon.
		Note the fieldname shift: Tank In carries the driver per container as ``driver``."""
		c = _container(f"{PREFIX}000009")
		_tank_in_bon(c, vehicle={"truck_plate": "L 1234 GL", "driver": "Pak Sopir"})

		ge = self._gates(c)[0]
		self.assertEqual(ge.truck_plate, "L 1234 GL")
		self.assertEqual(ge.driver_name, "Pak Sopir")

	def test_the_departure_does_not_overwrite_the_arrival_truck(self):
		"""One slot, a whole visit: the record describes the arrival (its date, its bon), so
		the truck stays the arrival's. The departure truck is on the Order Muat."""
		c = _container(f"{PREFIX}000010")
		_tank_in_bon(c, vehicle={"truck_plate": "L 1234 GL", "driver": "Pak Sopir"})
		_drop_provisioned_eir_in(c)
		frappe.db.set_value("Container", c, "status", "Available", update_modified=False)
		_clean_eir_out(c)

		ge = self._gates(c)[0]
		self.assertEqual(ge.status, "Gate_Out_Completed")
		self.assertEqual(ge.truck_plate, "L 1234 GL")
		self.assertEqual(ge.driver_name, "Pak Sopir")

	def test_gate_out_without_an_arrival_still_files_one(self):
		"""Tanks that predate this, and arrivals that were never bonned, must still leave a
		trace — the create branch of ``_resolve_or_create_gate_entry`` stays."""
		c = _container(f"{PREFIX}000008", status="Available")
		_clean_eir_out(c)
		rows = self._gates(c)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].status, "Gate_Out_Completed")

	def test_a_bonned_departure_records_its_truck(self):
		"""With no arrival to inherit from, the record takes the departure's vehicle — which
		Tank Out carries on the Order Muat header rather than per container."""
		c = _container(f"{PREFIX}000011", status="Available")
		bon = _make_order_muat(
			ensure_test_customer(CUSTOMER), c, truck="B 9001 XY", driver="Budi"
		)
		_clean_eir_out(c)

		ge = self._gates(c)[0]
		self.assertEqual(ge.order_ref, bon)
		self.assertEqual(ge.truck_plate, "B 9001 XY")
		self.assertEqual(ge.driver_name, "Budi")
		frappe.db.delete("Order Muat", {"name": bon})


class TestGateLogIsNotHandWritten(FrappeTestCase):
	"""The gate + audit doctypes are written by hooks. Nobody may create one from the Desk —
	see ``install.NO_MANUAL_CREATE`` and the ``v0_55.lock_gate_audit_doctypes`` patch."""

	def test_no_role_may_create_a_gate_or_audit_record(self):
		from container_depot.install import NO_MANUAL_CREATE

		offenders = frappe.get_all(
			"Custom DocPerm",
			filters={"parent": ["in", sorted(NO_MANUAL_CREATE)], "create": 1},
			fields=["parent", "role"],
		)
		self.assertFalse(
			offenders,
			"a gate/audit log with a '+ Add' button is a log that can disagree with the yard: "
			+ ", ".join(f"{o.parent}/{o.role}" for o in offenders),
		)

	def test_the_yard_roles_keep_their_write_perm(self):
		"""The reason the lock strips create but NOT write: a mistyped truck plate on an
		audit row has to stay correctable by the people standing at the gate."""
		writers = frappe.get_all(
			"Custom DocPerm", filters={"parent": "Gate Entry", "write": 1}, pluck="role"
		)
		self.assertIn("Security", writers)
		self.assertIn("Team Kalmar", writers)
