"""The "Wajibkan Semua Order" switch and the 2026-10-02 rework around it.

* ON (default) keeps every order mandatory; OFF keeps only the backbone — booking, bon, gate,
  EIR-In, EIR-Out, payment — and lets survey, Leak Check, cleaning and M&R wait, their
  statuses untouched.
* Each visit owns its orders: work an earlier stay left open never holds the next one.
* The EIR-Out is born with its Tank Out booking, survey or not; ON makes it wait for the survey.
* An Order Bongkar closes on its last EIR-In and reopens when one is undone.
* The booking's per-tank panel lists Leak Checks, drops the bons, and says "menahan" by the switch.

Self-cleaning: every row created here is hard-deleted in tearDown, the switch put back as found.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime, today

from container_depot.container_depot import order_policy
from container_depot.container_depot import tank_survey as ts
from container_depot.container_depot.container_status import container_open_orders
from container_depot.container_depot.doctype.leak_check.leak_check import (
	has_leak_check_this_visit,
	open_leak_check,
	provision_for_order_bongkar,
)
from container_depot.container_depot.eir import provision_eir_out_for_booking, revert_to_draft
from container_depot.tests._leak_check import make_leak_check
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_eir import _make_container, _make_order_bongkar, _make_order_muat
from container_depot.tests.test_gate_out import _eir_out

PREFIX = "OPOL"
DEPOT = "OAK1"
SETTINGS = "Depot Operation Settings"


def _purge():
	containers = frappe.get_all("Container", filters={"name": ["like", f"{PREFIX}%"]}, pluck="name") or [""]
	bookings = frappe.get_all(
		"Container Booking Item",
		filters={"container": ["in", containers], "parenttype": "Container Booking"},
		pluck="parent",
	) or [""]
	surveys = frappe.get_all("Survey Order", filters={"booking": ["in", bookings]}, pluck="name") or [""]
	bons = {
		dt: frappe.get_all(child, filters={"container": ["in", containers], "parenttype": dt}, pluck="parent") or [""]
		for dt, child in (("Order Bongkar", "Container Booking Item"), ("Order Muat", "Order Container Item"))
	}
	inspections = frappe.get_all("Inspection", filters={"container": ["in", containers]}, pluck="name") or [""]
	leaks = frappe.get_all("Leak Check", filters={"container": ["in", containers]}, pluck="name") or [""]
	for dt, names in (
		("Inspection", inspections), ("Survey Order", surveys), ("Leak Check", leaks),
		("Container Booking", bookings), ("Container", containers), *bons.items(),
	):
		frappe.db.delete("Notification Log", {"document_type": dt, "document_name": ["in", names]})
		frappe.db.delete("Comment", {"reference_doctype": dt, "reference_name": ["in", names]})
	frappe.db.delete("Survey Order Tank", {"parent": ["in", surveys]})
	frappe.db.delete("Survey Order", {"name": ["in", surveys]})
	frappe.db.delete("Leak Check Photo", {"parent": ["in", leaks]})
	for dt, names in bons.items():
		frappe.db.delete("Container Booking Item" if dt == "Order Bongkar" else "Order Container Item", {"parent": ["in", names]})
		frappe.db.delete(dt, {"name": ["in", names]})
	frappe.db.delete("Booking Code", {"booking": ["in", bookings]})
	frappe.db.delete("Container Booking Item", {"parent": ["in", bookings]})
	frappe.db.delete("Container Booking", {"name": ["in", bookings]})
	for dt in ("Inspection", "Cleaning Order", "Repair Order", "Leak Check", "Container Activity",
			   "Container Movement", "Storage Charge", "Container Position"):
		frappe.db.delete(dt, {"container": ["in", containers]})
	frappe.db.delete("Gate Entry", {"container_no": ["like", f"{PREFIX}%"]})
	frappe.db.delete("Container", {"name": ["in", containers]})


class _Base(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		row = frappe.db.sql(
			"SELECT value FROM `tabSingles` WHERE doctype = %s AND field = 'enforce_all_orders'", SETTINGS
		)
		self._switch = row[0][0] if row else None
		self._set(True)

	def tearDown(self):
		frappe.set_user("Administrator")
		_purge()
		frappe.db.delete("Singles", {"doctype": SETTINGS, "field": "enforce_all_orders"})
		if self._switch is not None:
			frappe.db.set_single_value(SETTINGS, "enforce_all_orders", self._switch)
		order_policy.clear_cache()
		frappe.db.commit()
		super().tearDown()

	def _set(self, on: bool):
		frappe.db.set_single_value(SETTINGS, "enforce_all_orders", 1 if on else 0)
		order_policy.clear_cache()

	def _tank(self, suffix, status="In_Depot"):
		return _make_container(f"{PREFIX}{suffix}", status=status, depot=DEPOT)

	def _cleaning(self, container):
		return frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "Service Setup",
		}).insert(ignore_permissions=True).name

	def _booking(self, container, direction="Tank Out", confirmed=True, **extra):
		"""A booking for ``container``; ``confirmed`` stands in for its Submit — a Tank Out
		raises its EIR-Out and survey day only there (user, 2026-10-08)."""
		doc = frappe.get_doc({
			"doctype": "Container Booking", "direction": direction, "depot": DEPOT,
			"plan_date": add_days(today(), 3),
			"items": [{"container": container}],
			**extra,
		})
		doc.flags.ignore_validate = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		if confirmed:
			frappe.db.set_value("Container Booking", doc.name, "docstatus", 1, update_modified=False)
			frappe.db.sql("UPDATE `tabContainer Booking Item` SET docstatus=1 WHERE parent=%s", doc.name)
			doc.reload()
			doc._provision_survey_order()
		return doc.name

	def _left_before(self, container, *, days_ago=1):
		"""Record an earlier stay that ended ``days_ago`` — the line between two visits."""
		ge = frappe.get_doc({
			"doctype": "Gate Entry", "container_no": container, "status": "Gate_Out_Completed",
			"gate_in_timestamp": add_days(now_datetime(), -days_ago - 2),
			"gate_out_timestamp": add_days(now_datetime(), -days_ago),
		})
		ge.flags.ignore_validate = True
		ge.insert(ignore_permissions=True, ignore_mandatory=True)

	def _backdate(self, doctype, name, days=2):
		frappe.db.set_value(doctype, name, "creation", add_days(now_datetime(), -days), update_modified=False)

	def _eir_out_of(self, booking, container):
		return frappe.db.get_value(
			"Inspection", {"container_booking": booking, "container": container, "inspection_type": "EIR-Out"}, "name"
		)


class TestSwitch(_Base):
	def test_every_order_is_mandatory_until_the_switch_is_saved_off(self):
		frappe.db.delete("Singles", {"doctype": SETTINGS, "field": "enforce_all_orders"})
		order_policy.clear_cache()
		self.assertTrue(order_policy.enforce_all())
		self._set(False)
		self.assertFalse(order_policy.enforce_all())
		self._set(True)
		self.assertTrue(order_policy.enforce_all())


class TestWhatHoldsTheExit(_Base):
	def test_off_lets_a_tank_leave_past_open_cleaning_and_no_leak_check(self):
		c = self._tank("0000001")
		co = self._cleaning(c)
		self._set(False)
		_eir_out(c, leak_check=False)
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Gate_Out")
		# Skipped, not settled: the order keeps the status it had.
		self.assertEqual(frappe.db.get_value("Cleaning Order", co, "status"), "Service Setup")

	def test_on_refuses_that_same_departure(self):
		c = self._tank("0000002")
		self._cleaning(c)
		with self.assertRaises(frappe.ValidationError):
			_eir_out(c)
		self.assertNotEqual(frappe.db.get_value("Container", c, "status"), "Gate_Out")

	def test_the_leak_check_holds_nothing_even_when_on(self):
		"""Like the EIR-Out (2026-10-08): a condition record, whatever the switch says."""
		c = self._tank("0000003", status="Available")
		_eir_out(c, leak_check=False)
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Gate_Out")

	def test_a_draft_eir_in_holds_the_tank_either_way(self):
		"""EIR-In is one of the mandatory orders — OFF does not let it wait."""
		c = self._tank("0000004")
		frappe.get_doc({
			"doctype": "Inspection", "inspection_type": "EIR-In", "container": c,
			"inspector": frappe.session.user,
		}).insert(ignore_permissions=True)
		self._set(False)
		with self.assertRaises(frappe.ValidationError):
			_eir_out(c, leak_check=False)

	def test_the_bon_muat_follows_the_switch(self):
		c = self._tank("0000005")
		self._cleaning(c)
		bon = frappe.get_doc({"doctype": "Order Muat", "containers": [{"container": c, "container_no": c}]})
		with self.assertRaisesRegex(frappe.ValidationError, "belum selesai"):
			bon._validate_no_open_work()
		self._set(False)
		bon._validate_no_open_work()


class TestEachVisitOwnsItsOrders(_Base):
	def test_work_an_earlier_stay_left_open_does_not_hold_this_one(self):
		c = self._tank("0000011", status="Available")
		co = self._cleaning(c)
		self._backdate("Cleaning Order", co)
		self.assertEqual([o["name"] for o in container_open_orders(c)], [co])

		self._left_before(c)
		self.assertEqual(container_open_orders(c), [])
		# Still open, and still holding a tank that is away — its retirement waits for it.
		frappe.db.set_value("Container", c, "status", "Gate_Out", update_modified=False)
		self.assertEqual([o["name"] for o in container_open_orders(c)], [co])

	def test_an_earlier_stays_leak_check_does_not_count_for_this_one(self):
		c = self._tank("0000012", status="Available")
		lc = make_leak_check(c)
		self._backdate("Leak Check", lc)
		self.assertTrue(has_leak_check_this_visit(c))
		self._left_before(c)
		self.assertFalse(has_leak_check_this_visit(c))

	def test_each_tank_in_bon_raises_its_own_leak_check(self):
		c = self._tank("0000013")
		customer = ensure_test_customer("Order Policy Test Co")
		first = _make_order_bongkar(customer, c)
		provision_for_order_bongkar(first)
		second = _make_order_bongkar(customer, c)
		provision_for_order_bongkar(second)
		self.assertEqual(frappe.db.count("Leak Check", {"container": c, "status": "Open"}), 2)
		self.assertEqual(
			frappe.db.get_value("Leak Check", open_leak_check(c), "order_bongkar"), second
		)


class TestEirOutBornWithTheBooking(_Base):
	def test_a_surveyed_booking_has_its_eir_out_and_the_survey_claims_it(self):
		c = self._tank("0000021")
		bk = self._booking(c, survey_date=add_days(today(), 1))
		eir = self._eir_out_of(bk, c)
		self.assertTrue(eir)

		order = frappe.db.get_value("Survey Order", {"booking": bk}, "name")
		row = frappe.db.get_value("Survey Order Tank", {"parent": order, "container": c}, "name")
		ts.mark_lowered(row)
		self.assertEqual(ts.finish_survey(row)["eir_out"], eir)
		ts.reopen_survey(row, note="kecepetan")
		# A reopen no longer takes the EIR-Out back.
		self.assertEqual(frappe.db.get_value("Inspection", eir, "docstatus"), 0)
		self.assertEqual(
			frappe.db.count("Inspection", {"container": c, "inspection_type": "EIR-Out", "docstatus": ["!=", 2]}), 1
		)

	def test_on_the_eir_out_waits_for_the_survey_off_it_does_not(self):
		c = self._tank("0000022")
		bk = self._booking(c, survey_date=add_days(today(), 1))
		eir = self._eir_out_of(bk, c)
		_make_order_muat(ensure_test_customer("Order Policy Test Co"), c)
		make_leak_check(c)

		with self.assertRaisesRegex(frappe.ValidationError, "survey"):
			frappe.get_doc("Inspection", eir).submit()
		self._set(False)
		frappe.get_doc("Inspection", eir).submit()
		# The EIR-Out is a record only — the bon is the gate-out (gate.depart_bon).
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "In_Depot")
		order = frappe.db.get_value("Survey Order", {"booking": bk}, "name")
		self.assertEqual(
			frappe.db.get_value("Survey Order Tank", {"parent": order, "container": c}, "status"), ts.WAITING
		)

	def test_a_booking_missing_its_eir_out_gets_one_unless_the_tank_is_gone(self):
		c = self._tank("0000023")
		bk = self._booking(c, survey_date=add_days(today(), 1))
		frappe.db.delete("Inspection", {"name": self._eir_out_of(bk, c)})
		provision_eir_out_for_booking(bk)
		self.assertTrue(self._eir_out_of(bk, c))

		gone = self._tank("0000024", status="Gate_Out")
		bk2 = self._booking(gone)
		self.assertFalse(self._eir_out_of(bk2, gone))

	def test_a_draft_booking_raises_no_eir_out(self):
		c = self._tank("0000026")
		bk = self._booking(c, confirmed=False, survey_date=add_days(today(), 1))
		self.assertFalse(self._eir_out_of(bk, c))
		self.assertFalse(frappe.db.exists("Survey Order", {"booking": bk}))

	def test_a_second_booking_never_takes_a_live_bookings_eir_out(self):
		c = self._tank("0000025")
		first = self._booking(c)
		eir = self._eir_out_of(first, c)
		second = self._booking(c)
		self.assertEqual(frappe.db.get_value("Inspection", eir, "container_booking"), first)
		self.assertFalse(self._eir_out_of(second, c))


class TestBonBongkarCloses(_Base):
	def test_it_closes_on_its_last_eir_in_and_reopens_when_that_is_undone(self):
		from container_depot.container_depot import eir

		c = self._tank("0000031")
		bon = _make_order_bongkar(ensure_test_customer("Order Policy Test Co"), c)
		res = eir.create_eir(
			inspection_type="EIR-In", container=c, tank_status="Empty Clean", referred_voucher=bon, submit=True
		)
		self.assertEqual(frappe.db.get_value("Inspection", res["name"], "referred_voucher"), bon)
		self.assertEqual(frappe.db.get_value("Order Bongkar", bon, "order_status"), "Completed")

		revert_to_draft(res["name"])
		self.assertEqual(frappe.db.get_value("Order Bongkar", bon, "order_status"), "Issued")


class TestBookingPanel(_Base):
	def test_outbound_panel_lists_leak_checks_drops_bons_and_holds_by_the_switch(self):
		from container_depot.container_depot.doctype.container_booking.container_booking import related_orders

		c = self._tank("0000041")
		bk = self._booking(c)
		co = self._cleaning(c)
		lc = make_leak_check(c)
		_make_order_muat(ensure_test_customer("Order Policy Test Co"), c)

		orders = {o["name"]: o for o in related_orders(bk)[0]["orders"]}
		self.assertIn(lc, orders)
		self.assertFalse({"Order Muat", "Order Bongkar"} & {o["doctype"] for o in orders.values()})
		self.assertTrue(orders[co]["blocks"])

		self._set(False)
		orders = {o["name"]: o for o in related_orders(bk)[0]["orders"]}
		self.assertTrue(orders[co]["open"])
		self.assertFalse(orders[co]["blocks"])

	def test_inbound_panel_lists_the_visits_leak_check(self):
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			orders_by_container,
		)

		c = self._tank("0000042")
		bk = self._booking(c, direction="Tank In")
		lc = make_leak_check(c)
		frappe.db.set_value("Leak Check", lc, "booking", bk, update_modified=False)
		names = [o["name"] for o in orders_by_container(bk)[0]["orders"]]
		self.assertIn(lc, names)
