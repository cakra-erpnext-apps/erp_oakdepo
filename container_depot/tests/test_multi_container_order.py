"""Tests for multi-container bon/voucher generation.

One booking (single direction) can spawn several Order Bongkar / Order Muat,
each carrying up to 3 of its still-pending containers, via the shared atomic
core ``container_depot.order_generation.make_order``.
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
from container_depot.container_depot.order_generation import make_order
from container_depot.container_depot.doctype.booking_code.booking_code import generate_code
from container_depot.tests.finance_fixture import require_finance
from container_depot.tests.test_api import ensure_test_customer

MC_CUSTOMER = "MultiContainer Test Customer"
# The hauler on a bon is a Customer link, so the test hauler must be a real one.
_MC_SHIPPER = MC_CUSTOMER


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
	# A Confirmed booking is a submitted one — mark it docstatus 1 directly (the gate
	# requires a submitted booking) without re-running on_submit (which would auto-issue
	# its own codes, conflicting with the explicit ones created below).
	frappe.db.set_value("Container Booking", booking.name, "docstatus", 1, update_modified=False)
	frappe.db.sql("UPDATE `tabContainer Booking Item` SET docstatus=1 WHERE parent=%s", booking.name)
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


def purge_mc_data():
	"""Remove every record this module created for ``MC_CUSTOMER``, and commit the removal.

	FrappeTestCase does NOT roll back per test — the rollback is registered once per class
	(``addClassCleanup(_rollback_db)``). So the moment anything commits mid-class (fixtures
	do), every row written so far becomes permanent, and this module's bookings/codes/bons
	pile up on the site one set per suite run. Call it from ``tearDownClass``.

	The commit at the end is deliberate: class cleanups run AFTER ``tearDownClass``, so an
	uncommitted delete would be undone by that rollback and the leaked rows would come back.
	Raw deletes (not ``delete_doc``) because Container Booking / Order * refuse ordinary
	deletion, and because the whole related set goes together so no dangling link is left.
	"""
	bookings = frappe.get_all("Container Booking", filters={"customer": MC_CUSTOMER}, pluck="name")
	containers = frappe.get_all("Container", filters={"principal": MC_CUSTOMER}, pluck="name")
	scope = [
		("Inspection", {"container": ["in", containers]} if containers else None),
		("Cleaning Order", {"container": ["in", containers]} if containers else None),
		("Repair Order", {"container": ["in", containers]} if containers else None),
		("Order Bongkar", {"booking": ["in", bookings]} if bookings else None),
		("Order Muat", {"booking": ["in", bookings]} if bookings else None),
		("Booking Code", {"booking": ["in", bookings]} if bookings else None),
		("Container Booking", {"customer": MC_CUSTOMER}),
		("Container", {"principal": MC_CUSTOMER}),
		("Depot Contract", {"customer": MC_CUSTOMER}),
	]
	# Same reason the booking purge above is raw: nothing unwinds Container.lift_on_booking,
	# and a Link left pointing at a deleted booking blows up the next save of that tank.
	if bookings:
		frappe.db.sql(
			"""UPDATE `tabContainer` SET lift_on_booking = NULL, target_lift_on = NULL
			   WHERE lift_on_booking IN %(bookings)s""",
			{"bookings": tuple(bookings)},
		)
	for doctype, filters in scope:
		if filters is None:
			continue
		try:
			names = frappe.get_all(doctype, filters=filters, pluck="name")
			children = [df.options for df in frappe.get_meta(doctype).get_table_fields()]
		except Exception:
			continue
		for name in names:
			for child in children:
				frappe.db.delete(child, {"parent": name, "parenttype": doctype})
			frappe.db.delete(doctype, {"name": name})
	for price_list in frappe.get_all("Price List", filters={"customer": MC_CUSTOMER}, pluck="name"):
		frappe.db.delete("Item Price", {"price_list": price_list})
		frappe.db.delete("Price List", {"name": price_list})
	frappe.db.delete("Customer", {"customer_name": MC_CUSTOMER})
	frappe.db.commit()


class TestMakeOrderCore(FrappeTestCase):
	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		purge_mc_data()

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

	def test_container_summary_fills_the_bon_list_column(self):
		"""A Desk list column cannot render a child table, so the row numbers are
		denormalised onto ``container_summary``. Empty here means the Order Bongkar list
		shows a booking and a status but never which tank the bon is actually for.
		"""
		booking, codes = _booking_with_codes(code_direction="Tank In", count=2, prefix="MCSUM0")
		order = frappe.get_doc("Order Bongkar", make_order(booking, codes))
		self.assertEqual(order.container_summary, "MCSUM0X0001, MCSUM0X0002")

	def test_container_summary_follows_a_revision(self):
		"""Recomputed on every save, not stamped once at creation — a bon whose containers
		were swapped after issue would otherwise advertise a tank it no longer carries.
		"""
		booking, codes = _booking_with_codes(code_direction="Tank In", count=3, prefix="MCSMR0")
		order = frappe.get_doc("Order Bongkar", make_order(booking, [codes[0]]))
		self.assertEqual(order.container_summary, "MCSMR0X0001")
		order.append("containers", {"booking_code": codes[1]})
		order.save()
		self.assertEqual(order.container_summary, "MCSMR0X0001, MCSMR0X0002")
		order.containers = [r for r in order.containers if r.booking_code != codes[0]]
		order.save()
		self.assertEqual(order.container_summary, "MCSMR0X0002")

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
		for cno in cls.CONTAINERS:
			if not frappe.db.exists("Container", cno):
				frappe.get_doc({
					"doctype": "Container",
					"container_no": cno,
					"container_type": "ISO Tank",
					"status": "Available",
					"principal": customer,
				}).insert(ignore_permissions=True)

	@staticmethod
	def _finish_cleaning(container):
		"""Give a container the submitted, Completed Cleaning Order the Muat gate wants."""
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "Completed",
		}).insert(ignore_permissions=True)
		frappe.db.set_value("Cleaning Order", co.name, "docstatus", 1, update_modified=False)
		return co.name

	@staticmethod
	def _open_cleaning(container):
		"""An UNFINISHED cleaning — the thing that actually holds a tank in the depot."""
		return frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "Service Setup",
		}).insert(ignore_permissions=True).name

	@staticmethod
	def _drop_cleaning(container):
		frappe.db.delete("Cleaning Order", {"container": container})

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		purge_mc_data()

	def test_muat_allowed_when_no_order_was_ever_raised(self):
		"""A tank with nothing open may be loaded out, even with no cleaning on record.

		The gate is the ABSENCE of unfinished work. Demanding a Completed Cleaning Order
		instead made a tank that arrived clean unloadable forever: there was no order to
		finish, and no way to produce one.
		"""
		for c in self.CONTAINERS:
			self._drop_cleaning(c)
		booking, codes = _booking_with_codes(
			code_direction="Tank Out", count=2, prefix="MCMT0", containers=self.CONTAINERS
		)
		name = make_order(booking, codes)  # must NOT raise
		self.assertEqual(len(frappe.get_doc("Order Muat", name).containers), 2)
		self.assertEqual(_states(codes), ["Used", "Used"])

	def test_container_summary_fills_the_bon_list_column(self):
		"""Same denormalisation as Order Bongkar, and worth asserting separately: the two
		bons use DIFFERENT container child tables (Order Container Item vs Container Booking
		Item), so one can fill and the other stay blank.
		"""
		for c in self.CONTAINERS:
			self._drop_cleaning(c)
		booking, codes = _booking_with_codes(
			code_direction="Tank Out", count=2, prefix="MCSMM", containers=self.CONTAINERS
		)
		order = frappe.get_doc("Order Muat", make_order(booking, codes))
		self.assertEqual(order.container_summary, "MCSMMXX0001, MCSMMXX0002")

	def test_muat_with_finished_cleaning(self):
		for c in self.CONTAINERS:
			self._finish_cleaning(c)
		booking, codes = _booking_with_codes(
			code_direction="Tank Out", count=2, prefix="MCMV0", containers=self.CONTAINERS
		)
		name = make_order(booking, codes)
		order = frappe.get_doc("Order Muat", name)
		self.assertEqual(len(order.containers), 2)
		self.assertEqual(_states(codes), ["Used", "Used"])
		for c in self.CONTAINERS:
			self._drop_cleaning(c)

	def test_muat_carries_the_pickup_detail_it_is_asked_for(self):
		"""A Tank Out bon must land the PICK-UP fields — hauler, destination, Tgl. Muat and
		the driver. Order Muat's field is ``driver_name``; a payload built for Tank In sends
		``driver`` (plus ex_vessel / tanggal_bongkar), so the bon came out blank where it
		mattered even though the right doctype was created.

		The hauler is ONE field (``shipper``). It used to be two — a free-text ``angkutan``
		beside the Customer link — so the same company could be typed into one and looked up
		in the other. The old key is still accepted, but only when it names a real Customer.
		"""
		for c in self.CONTAINERS:
			self._drop_cleaning(c)
		booking, codes = _booking_with_codes(
			code_direction="Tank Out", count=1, prefix="MCMD0", containers=self.CONTAINERS[:1]
		)
		name = make_order(booking, codes, vehicle_data={
			"shipper": _MC_SHIPPER,
			"destination": "Gresik",
			"tanggal_muat": frappe.utils.today(),
			"truck_plate": "L 1234 XY",
			"driver_name": "Budi",
			"driver_phone": "0812",
			"ro": "RO-1",
			# One note for the whole bon (what the PWA gate sends) must reach every row.
			"remarks": "catatan gate",
		})
		doc = frappe.get_doc("Order Muat", name)
		self.assertEqual(doc.shipper, _MC_SHIPPER)
		self.assertFalse(doc.meta.get_field("angkutan"), "angkutan is merged into shipper")
		self.assertEqual(doc.destination, "Gresik")
		self.assertEqual(str(doc.tanggal_muat), frappe.utils.today())
		self.assertEqual(doc.driver_name, "Budi")
		self.assertEqual(doc.truck_plate, "L 1234 XY")
		self.assertEqual([r.remarks for r in doc.containers], ["catatan gate"])

	def test_muat_rejects_when_one_container_still_has_open_work(self):
		"""One unfinished order on one row refuses the whole bon, and names it."""
		for c in self.CONTAINERS:
			self._drop_cleaning(c)
		self._finish_cleaning(self.CONTAINERS[0])         # first is done
		co = self._open_cleaning(self.CONTAINERS[1])      # second is still being cleaned
		booking, codes = _booking_with_codes(
			code_direction="Tank Out", count=2, prefix="MCMW0", containers=self.CONTAINERS
		)
		with self.assertRaises(frappe.ValidationError) as ctx:
			make_order(booking, codes)
		self.assertIn(co, str(ctx.exception), "the blocking order must be named")
		self.assertEqual(_states(codes), ["Active", "Active"])
		for c in self.CONTAINERS:
			self._drop_cleaning(c)


class TestGenerateOrderFromBookingAPI(FrappeTestCase):
	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		purge_mc_data()

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

	def test_generate_auto_submits_bon(self):
		# The DMS "generate" entry point issues a FINAL (submitted) bon, not a draft.
		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCAS0")
		result = generate_order_from_booking(booking, json.dumps(codes))
		self.assertTrue(result["success"])
		self.assertEqual(frappe.db.get_value("Order Bongkar", result["order_name"], "docstatus"), 1)

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
			"principal": ensure_test_customer(MC_CUSTOMER),
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
		from container_depot.container_depot.doctype.order_bongkar.order_bongkar import (
			pending_container_query,
		)
		c1 = frappe.get_doc({
			"doctype": "Container", "container_no": "MCPQ0000001",
			"container_type": "ISO Tank", "status": "Available",
			"principal": ensure_test_customer(MC_CUSTOMER),
		}).insert(ignore_permissions=True).name
		b1, _ = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCPQA0", containers=[c1])
		c2 = frappe.get_doc({
			"doctype": "Container", "container_no": "MCPQ0000002",
			"container_type": "ISO Tank", "status": "Available",
			"principal": ensure_test_customer(MC_CUSTOMER),
		}).insert(ignore_permissions=True).name
		_booking_with_codes(code_direction="Tank In", count=1, prefix="MCPQB0", containers=[c2])
		names = [r[0] for r in pending_container_query(
			"Container", "", "name", 0, 20, {"booking": b1},
		)]
		self.assertIn(c1, names)
		self.assertNotIn(c2, names)

	def test_void_draft_releases_codes(self):
		# Voiding a DRAFT bon frees its codes (Used -> Active) and marks it Cancelled
		# (soft delete — record kept), so the containers can go on a fresh voucher.
		from container_depot.container_depot.order_generation import void_order
		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCCD0")
		name = make_order(booking, codes)
		self.assertEqual(_states(codes), ["Used"])
		void_order(name, "Order Bongkar")
		self.assertEqual(_states(codes), ["Active"])
		self.assertEqual(frappe.db.get_value("Order Bongkar", name, "docstatus"), 2)

	def test_void_submitted_releases_codes(self):
		# A submitted bon can still be voided; on_cancel releases its codes.
		from container_depot.container_depot.order_generation import void_order
		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCCS0")
		name = make_order(booking, codes)
		frappe.get_doc("Order Bongkar", name).submit()
		self.assertEqual(_states(codes), ["Used"])
		void_order(name, "Order Bongkar")
		self.assertEqual(_states(codes), ["Active"])
		self.assertEqual(frappe.db.get_value("Order Bongkar", name, "docstatus"), 2)

	def test_revert_submitted_order_to_draft(self):
		# Cancel = return a submitted bon to an editable Draft; containers stay reserved.
		from container_depot.container_depot.order_generation import revert_order_to_draft
		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCRV0")
		name = make_order(booking, codes)
		frappe.get_doc("Order Bongkar", name).submit()
		self.assertEqual(_states(codes), ["Used"])
		revert_order_to_draft(name, "Order Bongkar")
		self.assertEqual(frappe.db.get_value("Order Bongkar", name, "docstatus"), 0)
		# Containers stay reserved — codes remain Used so the draft still holds them.
		self.assertEqual(_states(codes), ["Used"])

	def test_revert_rejects_non_submitted(self):
		from container_depot.container_depot.order_generation import revert_order_to_draft
		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCRN0")
		name = make_order(booking, codes)  # draft
		with self.assertRaises(frappe.ValidationError):
			revert_order_to_draft(name, "Order Bongkar")

	def test_void_requires_the_cancel_permission(self):
		"""Voiding is cancelling, so it needs the cancel permission — on both surfaces.

		It used to need neither. ``void_order`` is a plain ``@frappe.whitelist``, and nothing
		inside it checked: ``frappe.get_doc`` does not, and the draft branch writes docstatus
		with ``db.sql``, which skips the ORM check too. A Finance account holding read-only
		DocPerm on Order Bongkar could void a bon over the API, and the Desk button was shown
		to it as well.

		§8.1 gives the field roles submit but withholds cancel on purpose — undoing a
		mis-submitted bon escalates to Admin Ops — and that only means something if the
		endpoint enforces it.
		"""
		from container_depot.container_depot.order_generation import void_order

		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCPRM0")
		name = make_order(booking, codes)

		email = "mc-readonly@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, ignore_permissions=True, force=True)
		user = frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": "MC ReadOnly",
			"send_welcome_email": 0,
			"user_type": "System User",
		}).insert(ignore_permissions=True)
		user.add_roles("Finance")
		# No commit: that would defeat FrappeTestCase's per-test rollback and leak
		# every fixture above into sibling tests. The role cache is per-user, so
		# clearing it is enough for has_permission to see the new roles.
		frappe.clear_cache(user=email)

		try:
			frappe.set_user(email)
			self.assertFalse(frappe.has_permission("Order Bongkar", "cancel"))
			with self.assertRaises(frappe.PermissionError):
				void_order(name, "Order Bongkar")
		finally:
			frappe.set_user("Administrator")
			frappe.delete_doc("User", email, ignore_permissions=True, force=True)

		# Still untouched, and Admin Ops (which does hold cancel) can still void it.
		self.assertEqual(frappe.db.get_value("Order Bongkar", name, "docstatus"), 0)
		self.assertEqual(_states(codes), ["Used"])
		void_order(name, "Order Bongkar")
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


class TestBookingFrozenOnceBonRaised(FrappeTestCase):
	"""A bon is the point of no return for the booking that spawned it.

	The bon is paper a driver was handed at the gate and it names this booking, so once one
	exists the booking can no longer be reverted to a draft or cancelled — any correction
	from that point on goes through the bon.
	"""

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		purge_mc_data()

	def test_revert_refused_once_a_bon_is_raised(self):
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			revert_booking_to_draft,
		)

		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCFR0")
		make_order(booking, codes)
		with self.assertRaises(frappe.ValidationError):
			revert_booking_to_draft(booking)
		self.assertEqual(frappe.db.get_value("Container Booking", booking, "docstatus"), 1)

	def test_cancel_refused_once_a_bon_is_raised(self):
		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCFC0")
		make_order(booking, codes)
		doc = frappe.get_doc("Container Booking", booking)
		doc.flags.ignore_permissions = True
		with self.assertRaises(frappe.ValidationError):
			doc.cancel()
		# before_cancel, not on_cancel: nothing must have been unwound by the refusal.
		self.assertEqual(frappe.db.get_value("Container Booking", booking, "docstatus"), 1)
		self.assertNotEqual(
			frappe.db.get_value("Container Booking", booking, "booking_status"), "Cancelled"
		)

	def test_refusal_survives_voiding_the_bon(self):
		"""The whole point of asking "was one ever raised?" instead of reading the codes.

		Voiding a bon releases its Booking Codes back to ``Active``, which is what the old
		code-state check keyed on — so voiding used to hand the booking back to the operator
		even though the bon had already been printed and handed over.
		"""
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			revert_booking_to_draft,
		)
		from container_depot.container_depot.order_generation import void_order

		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCFV0")
		name = make_order(booking, codes)
		void_order(name, "Order Bongkar")
		self.assertEqual(_states(codes), ["Active"])  # codes released, bon still on record

		with self.assertRaises(frappe.ValidationError):
			revert_booking_to_draft(booking)
		doc = frappe.get_doc("Container Booking", booking)
		doc.flags.ignore_permissions = True
		with self.assertRaises(frappe.ValidationError):
			doc.cancel()

	def test_revision_state_reports_what_blocks_it(self):
		"""The form script gates its buttons on this, so it must see a voided bon too."""
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			revision_state,
		)
		from container_depot.container_depot.order_generation import void_order

		booking, codes = _booking_with_codes(code_direction="Tank In", count=2, prefix="MCFB0")
		state = revision_state(booking)
		self.assertEqual(state["bons"], [])
		self.assertEqual(state["locked_containers"], [])

		name = make_order(booking, [codes[0]])
		state = revision_state(booking)
		self.assertEqual(state["bons"], [f"Order Bongkar {name}"])
		# Only the container the bon took is locked — the other row stays revisable.
		self.assertEqual(
			state["locked_containers"],
			[frappe.db.get_value("Booking Code", codes[0], "container_no")],
		)

		void_order(name, "Order Bongkar")
		state = revision_state(booking)
		self.assertEqual(state["bons"], [f"Order Bongkar {name}"])
		self.assertEqual(
			state["locked_containers"],
			[frappe.db.get_value("Booking Code", codes[0], "container_no")],
		)

	def test_a_booking_with_no_bon_still_reverts(self):
		"""The guard must not freeze every confirmed booking — only the ones with paper out."""
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			revert_booking_to_draft,
		)

		booking, _codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="MCFN0")
		revert_booking_to_draft(booking)
		self.assertEqual(frappe.db.get_value("Container Booking", booking, "docstatus"), 0)


class TestConfirmedBookingIsLocked(FrappeTestCase):
	"""A submitted booking is closed: nothing on it can be changed, and it cannot be
	cancelled either.

	It used to be revisable in place (the user-editable fields are ``allow_on_submit``, so an
	ordinary ``save()`` reached ``before_update_after_submit``). That hook now refuses every
	such save, and ``before_cancel`` refuses a direct cancel — the one way in is **Kembali ke
	Draft** (``revert_booking_to_draft``), which is itself refused once a bon has been raised
	or a code has been used at the gate (see ``TestBookingFrozenOnceBonRaised``).

	The fields keep ``allow_on_submit`` on purpose: it is what lets the hook be reached at
	all, so the refusal can say what to do instead of core's "not allowed to change X after
	submission". Every system write to a submitted booking goes through ``db_set`` and never
	reaches the hook.
	"""

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		purge_mc_data()

	def _confirmed(self, prefix, count=2):
		booking, codes = _booking_with_codes(
			code_direction="Tank In", count=count, prefix=prefix
		)
		return frappe.get_doc("Container Booking", booking), codes

	def _refuses(self, doc):
		doc.flags.ignore_permissions = True
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_a_header_field_cannot_be_changed(self):
		doc, _codes = self._confirmed("MCRVA0")
		doc.remarks = "revisi catatan"
		self._refuses(doc)
		doc.reload()
		self.assertNotEqual(doc.remarks, "revisi catatan")

	def test_a_row_cannot_be_edited(self):
		doc, _codes = self._confirmed("MCRVB0")
		doc.items[0].driver = "Sopir Baru"
		self._refuses(doc)

	def test_a_row_cannot_be_added(self):
		doc, _codes = self._confirmed("MCRVF0", count=1)
		doc.append("items", {
			"container_no": "MCRVF0X0009",
			"condition": "EMPTY CLEAN",
			"tanggal_bongkar": today(),
		})
		self._refuses(doc)

	def test_a_row_cannot_be_dropped(self):
		doc, _codes = self._confirmed("MCRVG0")
		doc.items = [doc.items[0]]
		self._refuses(doc)

	def test_charges_cannot_be_changed(self):
		doc, _codes = self._confirmed("MCRVH0")
		doc.append("charges", {"item": "Lift Off", "qty": 1, "rate": 999})
		self._refuses(doc)

	def test_cancel_is_refused(self):
		"""Same rule as editing: undo a submitted booking by stepping back, not sideways."""
		doc, _codes = self._confirmed("MCRVI0")
		doc.flags.ignore_permissions = True
		with self.assertRaises(frappe.ValidationError):
			doc.cancel()
		doc.reload()
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(doc.booking_status, "Confirmed")

	def test_the_way_out_is_draft_then_void(self):
		"""The supported two-step, and it must unwind what a direct cancel used to.

		Codes especially: ``revert_booking_to_draft`` deliberately keeps them (the booking is
		meant to be re-submitted), so a booking cancelled through this path would leave live
		72h gate codes behind if ``void_draft`` did not void them.
		"""
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			revert_booking_to_draft,
			void_draft,
		)

		doc, codes = self._confirmed("MCRVJ0")
		revert_booking_to_draft(doc.name)
		doc.reload()
		self.assertEqual(doc.docstatus, 0)
		# Now editable again — that is the whole point of going back.
		doc.remarks = "koreksi setelah dibuka"
		doc.flags.ignore_permissions = True
		doc.save()

		void_draft(doc.name)
		doc.reload()
		self.assertEqual(doc.docstatus, 2)
		self.assertEqual(doc.booking_status, "Cancelled")
		self.assertFalse(
			[c for c in _states(codes) if c == "Active"],
			"a cancelled booking must not leave live gate codes behind",
		)

	def test_direction_is_not_revisable(self):
		"""Codes and the bon type are derived from it — it must stay put after submit."""
		self.assertFalse(
			frappe.get_meta("Container Booking").get_field("direction").allow_on_submit
		)
		# charges_total / container_summary are deliberately absent: they are read-only and
		# server-computed, and the system paths must be able to write them.
		for fieldname in ("booking_status", "payment_status", "sales_invoice", "lift_type"):
			self.assertFalse(
				frappe.get_meta("Container Booking").get_field(fieldname).allow_on_submit,
				f"{fieldname} is system-written and must not be revisable",
			)


class TestGate(FrappeTestCase):
	"""Gate PWA backend: gate_lookup (resolve + detail) and gate_generate_order."""

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		purge_mc_data()

	def setUp(self):
		# The gate reports a payment block, so these assertions only mean anything on a
		# site that invoices at all.
		require_finance(self)

	def test_lookup_by_booking_code_returns_detail(self):
		from container_depot.api import gate_lookup
		booking, codes = _booking_with_codes(code_direction="Tank In", count=2, prefix="GTLK0")
		res = gate_lookup(codes[0])
		self.assertTrue(res["valid"])
		self.assertEqual(res["booking"], booking)
		self.assertEqual(len(res["containers"]), 2)
		self.assertIn(codes[0], [c["booking_code"] for c in res["containers"]])

	def test_lookup_invalid_code(self):
		from container_depot.api import gate_lookup
		self.assertFalse(gate_lookup("OAK-DEADBEEF99")["valid"])

	def test_lookup_by_order_code_resolves_to_booking(self):
		from container_depot.api import gate_lookup
		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="GTOR0")
		order = make_order(booking, codes, submit=True)
		res = gate_lookup(order)  # scan/type the bon's own code
		self.assertTrue(res["valid"])
		self.assertEqual(res["booking"], booking)
		c = res["containers"][0]
		self.assertEqual(c["order"]["name"], order)
		self.assertEqual(c["order"]["doctype"], "Order Bongkar")

	def test_lookup_payment_blocked_flag(self):
		from container_depot.api import gate_lookup
		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="GTPB0")
		frappe.db.set_value("Container Booking", booking, {"payment_type": "Cash", "payment_status": "Unpaid"})
		self.assertTrue(gate_lookup(codes[0])["payment_blocked"])
		frappe.db.set_value("Container Booking", booking, "payment_status", "Paid")
		self.assertFalse(gate_lookup(codes[0])["payment_blocked"])

	def test_generate_blocks_cash_unpaid(self):
		from container_depot.api import gate_generate_order
		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="GTGB0")
		frappe.db.set_value("Container Booking", booking, {"payment_type": "Cash", "payment_status": "Unpaid"})
		with self.assertRaises(frappe.ValidationError):
			gate_generate_order(booking, json.dumps(codes))

	def test_generate_tank_in_issues_submitted_bon(self):
		from container_depot.api import gate_generate_order, gate_lookup
		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="GTGN0")
		frappe.db.set_value("Container Booking", booking, "payment_type", "TOP")  # not Cash → not blocked
		res = gate_generate_order(booking, json.dumps(codes))
		self.assertTrue(res["success"])
		self.assertEqual(res["order_doctype"], "Order Bongkar")
		self.assertEqual(frappe.db.get_value("Order Bongkar", res["order_name"], "docstatus"), 1)
		# Re-lookup: the container now carries the bon.
		self.assertEqual(gate_lookup(codes[0])["containers"][0]["order"]["name"], res["order_name"])

	def test_generate_passes_vehicle_data_to_bon(self):
		"""The gate form's truck/driver detail must land on the generated bon's row."""
		from container_depot.api import gate_generate_order, gate_lookup
		booking, codes = _booking_with_codes(code_direction="Tank In", count=1, prefix="GTVD0")
		frappe.db.set_value("Container Booking", booking, "payment_type", "TOP")
		# Booking-line detail is surfaced for the gate form to auto-fill from.
		self.assertIn("line", gate_lookup(codes[0])["containers"][0])
		res = gate_generate_order(
			booking,
			json.dumps(codes),
			vehicle_data=json.dumps(
				{"truck_plate": "B-7788-XY", "driver": "Slamet", "driver_phone": "0812345"}
			),
		)
		row = frappe.get_all(
			"Container Booking Item",
			filters={"parent": res["order_name"], "parenttype": "Order Bongkar"},
			fields=["truck_plate", "driver", "driver_phone"],
		)[0]
		self.assertEqual(row.truck_plate, "B-7788-XY")
		self.assertEqual(row.driver, "Slamet")
		self.assertEqual(row.driver_phone, "0812345")


class TestBonCoverage(FrappeTestCase):
	"""The "belum dibon" marker: how much of a booking is still waiting for paper.

	Read off Booking Code state, so it must follow a bon through its whole life —
	issued, and voided again — not just the moment it is created.
	"""

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		purge_mc_data()

	def _coverage(self, booking):
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			bon_coverage,
		)
		return bon_coverage(booking)

	def _stored(self, booking):
		return frappe.db.get_value(
			"Container Booking", booking, ["bon_status", "bon_summary"], as_dict=True
		)

	def test_coverage_tracks_bons_issued_and_voided(self):
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			refresh_bon_status,
		)
		from container_depot.container_depot.order_generation import void_order

		booking, codes = _booking_with_codes(code_direction="Tank In", count=3, prefix="MCCOV0")
		# The fixture writes its codes directly, bypassing on_submit — stamp the booking the
		# way submit would, which is also what the backfill patch does.
		refresh_bon_status(booking)
		cov = self._coverage(booking)
		self.assertEqual((cov["total"], cov["issued"]), (3, 0))
		self.assertEqual(cov["status"], "Belum Dibon")
		self.assertEqual(len(cov["pending"]), 3)
		self.assertEqual(self._stored(booking).bon_status, "Belum Dibon")

		# Two of three on a bon → partial, and the third is named as still pending.
		first = make_order(booking, codes[:2])
		cov = self._coverage(booking)
		self.assertEqual((cov["total"], cov["issued"]), (3, 2))
		self.assertEqual(cov["status"], "Sebagian Dibon")
		self.assertEqual(len(cov["pending"]), 1)
		stored = self._stored(booking)
		self.assertEqual(stored.bon_status, "Sebagian Dibon")
		self.assertEqual(stored.bon_summary, "2/3")

		make_order(booking, codes[2:])
		cov = self._coverage(booking)
		self.assertEqual(cov["status"], "Bon Lengkap")
		self.assertEqual(cov["pending"], [])
		self.assertEqual(self._stored(booking).bon_status, "Bon Lengkap")

		# Voiding a bon hands its containers back: they owe a bon again.
		void_order(first, "Order Bongkar")
		cov = self._coverage(booking)
		self.assertEqual((cov["total"], cov["issued"]), (3, 1))
		self.assertEqual(cov["status"], "Sebagian Dibon")
		self.assertEqual(len(cov["pending"]), 2)
		self.assertEqual(self._stored(booking).bon_status, "Sebagian Dibon")


class TestPlanDateCascade(FrappeTestCase):
	"""Tanggal Rencana Kerja on the header → the estimate on each container line.

	Which line field it lands in is the direction's answer, and a line someone edited by
	hand must survive a later change to the header.
	"""

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		purge_mc_data()

	def _booking(self, direction, prefix, plan_date=None, count=2):
		customer = ensure_test_customer(MC_CUSTOMER)
		contract = (
			frappe.db.get_value("Depot Contract", {"customer": customer, "status": "Active"}, "name")
			or _make_contract(customer)
		)
		doc = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": direction,
			"customer": customer,
			"contract": contract,
			"plan_date": plan_date,
			"items": [{"container_no": f"{prefix}{i:04d}"} for i in range(1, count + 1)],
		})
		doc.flags.ignore_validate = False
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		return doc

	def test_tank_in_fills_tanggal_bongkar_and_tank_out_fills_tanggal_muat(self):
		day = add_days(today(), 5)
		bookin = self._booking("Tank In", "MCPLNA0", plan_date=day)
		self.assertTrue(all(str(r.tanggal_bongkar) == day for r in bookin.items))
		# The other direction's estimate is left on its own default — the cascade touches
		# only the field the booking's direction actually uses.
		self.assertTrue(all(str(r.tanggal_muat) == today() for r in bookin.items))

		bookout = self._booking("Tank Out", "MCPLNB0", plan_date=day)
		self.assertTrue(all(str(r.tanggal_muat) == day for r in bookout.items))
		self.assertTrue(all(str(r.tanggal_bongkar) == today() for r in bookout.items))

	def test_a_hand_typed_line_date_survives_a_header_change(self):
		first, later = add_days(today(), 3), add_days(today(), 9)
		doc = self._booking("Tank Out", "MCPLNC0", plan_date=first)
		# One line is moved by hand; the other still follows the header.
		doc.items[0].tanggal_muat = add_days(today(), 20)
		doc.plan_date = later
		doc.save(ignore_permissions=True)
		self.assertEqual(str(doc.items[0].tanggal_muat), add_days(today(), 20))
		self.assertEqual(str(doc.items[1].tanggal_muat), later)

	def test_no_plan_date_leaves_the_lines_on_their_own_default(self):
		"""An empty header cascades nothing — the line keeps the field's own Today default,
		which is what every booking written before this feature carried."""
		doc = self._booking("Tank Out", "MCPLND0")
		self.assertTrue(all(str(r.tanggal_muat) == today() for r in doc.items))
