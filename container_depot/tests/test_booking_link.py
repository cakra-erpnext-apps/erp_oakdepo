"""Depot work is filed under the Container Booking whose visit produced it.

The rule under test, in one line: **an EIR reference confers parentage, nothing else does.**
An order raised on its own stands alone rather than being attributed to the container's
most recent booking — a tank on real data appears on dozens of bookings, so a guess would
file work under a visit that never happened.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot.container_depot.booking_link import booking_of_inspection
from container_depot.tests.test_api import ensure_test_customer

CUSTOMER = "Booking Link Test Co"
CONTAINER_NO = "TANK0000077"
OTHER_CONTAINER_NO = "TANK0000078"


def _container(container_no: str, principal: str) -> str:
	existing = frappe.db.get_value("Container", {"container_no": container_no}, "name")
	if existing:
		return existing
	return frappe.get_doc({
		"doctype": "Container",
		"container_no": container_no,
		"container_type": "ISO Tank",
		"status": "In_Depot",
		"principal": principal,
	}).insert(ignore_permissions=True).name


def _booking(customer: str, containers: list[tuple[str, str]]) -> str:
	"""A Container Booking listing ``containers`` as (container, container_no).

	Validation is bypassed (as elsewhere in this suite) because pricing, contract
	resolution and the payment gate are irrelevant here — only the item rows are.
	"""
	doc = frappe.get_doc({
		"doctype": "Container Booking",
		"direction": "Tank In",
		"customer": customer,
		"booking_status": "Confirmed",
		"items": [{"container": c, "container_no": no} for c, no in containers],
	})
	doc.flags.ignore_validate = True
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	return doc.name


def _bon(customer: str, booking: str, container: str, container_no: str) -> str:
	"""A submitted Order Bongkar raised from ``booking``."""
	doc = frappe.get_doc({
		"doctype": "Order Bongkar",
		"shipper": customer,
		"booking": booking,
		"ex_vessel": "MV BOOKING LINK",
		"containers": [{"container": container, "container_no": container_no}],
	})
	doc.flags.ignore_validate = True
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	frappe.db.set_value("Order Bongkar", doc.name, "docstatus", 1, update_modified=False)
	return doc.name


class TestBookingLink(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.customer = ensure_test_customer(CUSTOMER)
		cls.container = _container(CONTAINER_NO, cls.customer)
		cls.other = _container(OTHER_CONTAINER_NO, cls.customer)
		cls.booking = _booking(cls.customer, [(cls.container, CONTAINER_NO)])
		# A second booking that does NOT list the container — the typo case.
		cls.foreign_booking = _booking(cls.customer, [(cls.other, OTHER_CONTAINER_NO)])
		# A two-container booking, for the per-container panel.
		cls.multi = _booking(
			cls.customer, [(cls.container, CONTAINER_NO), (cls.other, OTHER_CONTAINER_NO)]
		)
		cls.bon = _bon(cls.customer, cls.booking, cls.container, CONTAINER_NO)

	@classmethod
	def tearDownClass(cls):
		for doctype in ("Cleaning Order", "Repair Order", "Periodic Test Order", "Inspection"):
			frappe.db.delete(doctype, {"container": ("in", [cls.container, cls.other])})
		bookings = (cls.booking, cls.foreign_booking, cls.multi)
		frappe.db.delete("Order Bongkar", {"booking": ("in", list(bookings))})
		for booking in bookings:
			frappe.db.delete("Container Booking Item", {"parent": booking})
			frappe.db.delete("Container Booking", {"name": booking})
		frappe.db.delete("Container", {"name": ("in", [cls.container, cls.other])})
		frappe.db.commit()
		super().tearDownClass()

	# --- fixtures -----------------------------------------------------------
	def _eir(self, *, voucher: str | None = None) -> str:
		doc = frappe.get_doc({
			"doctype": "Inspection",
			"inspection_type": "EIR-In",
			"container": self.container,
			"voucher_doctype": "Order Bongkar" if voucher else None,
			"referred_voucher": voucher,
		})
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		return doc.name

	def _order(self, doctype: str, **over) -> "frappe.Document":
		doc = frappe.get_doc({"doctype": doctype, "container": self.container, **over})
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		return doc

	# --- the chain ----------------------------------------------------------
	def test_eir_raised_from_a_bon_records_its_booking(self):
		"""The EIR is the root: bon -> booking, stamped so the orders below need not re-walk it."""
		eir = frappe.get_doc("Inspection", self._eir(voucher=self.bon))
		self.assertEqual(eir.container_booking, self.booking)
		self.assertEqual(booking_of_inspection(eir.name), self.booking)

	def test_orders_inherit_the_booking_from_their_eir(self):
		eir = self._eir(voucher=self.bon)
		for doctype in ("Cleaning Order", "Repair Order", "Periodic Test Order"):
			with self.subTest(doctype=doctype):
				order = self._order(doctype, inspection=eir)
				self.assertEqual(order.container_booking, self.booking)

	def test_an_order_without_an_eir_stands_alone(self):
		"""The whole point of the rule. The container IS on a booking, and the order still
		gets no parent — because nothing says THIS work belongs to THAT visit."""
		for doctype in ("Cleaning Order", "Repair Order", "Periodic Test Order"):
			with self.subTest(doctype=doctype):
				order = self._order(doctype)
				self.assertFalse(
					order.container_booking,
					"a standalone order must never be attributed to the container's booking",
				)

	def test_an_eir_without_a_bon_confers_nothing(self):
		"""A surveyor scanning a tank straight from the PWA raises an EIR with no voucher;
		orders below it stay standalone rather than inheriting a blank-then-guessed value."""
		eir = self._eir()
		self.assertFalse(frappe.db.get_value("Inspection", eir, "container_booking"))
		self.assertFalse(self._order("Cleaning Order", inspection=eir).container_booking)

	# --- the hand-set case --------------------------------------------------
	def test_a_hand_set_booking_must_list_the_container(self):
		order = self._order("Cleaning Order")
		order.container_booking = self.foreign_booking
		with self.assertRaises(frappe.ValidationError):
			order.save(ignore_permissions=True)

	def test_a_hand_set_booking_survives_the_next_save(self):
		"""An operator attributing work the automation could not must not be re-derived away."""
		eir = self._eir(voucher=self.bon)
		order = self._order("Cleaning Order", inspection=eir)
		self.assertEqual(order.container_booking, self.booking)
		order.container_booking = None
		order.save(ignore_permissions=True)
		# Cleared, then re-derived from the EIR — clearing is not an edit to preserve.
		self.assertEqual(order.container_booking, self.booking)

	# --- the per-container panel on the booking form ------------------------
	def _panel(self, booking: str) -> dict:
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			orders_by_container,
		)

		return {g["container_no"]: g for g in orders_by_container(booking)}

	def test_panel_groups_the_work_under_the_container_it_was_done_on(self):
		"""The reason this panel exists: on a multi-container booking the Connections tab
		cannot say which EIR belongs to which tank."""
		eir = self._eir(voucher=self.bon)
		frappe.db.set_value("Inspection", eir, "container_booking", self.multi, update_modified=False)
		order = self._order("Cleaning Order", inspection=eir, container_booking=self.multi)

		panel = self._panel(self.multi)
		self.assertEqual(set(panel), {CONTAINER_NO, OTHER_CONTAINER_NO})
		mine = [o["name"] for o in panel[CONTAINER_NO]["orders"]]
		self.assertIn(eir, mine)
		self.assertIn(order.name, mine)
		self.assertEqual(panel[OTHER_CONTAINER_NO]["orders"], [], "the other tank saw no work")

	def test_panel_keeps_a_container_that_has_no_work_yet(self):
		""""Nothing has happened to this tank" is an answer, so the row must not vanish."""
		self.assertIn(OTHER_CONTAINER_NO, self._panel(self.multi))

	def test_panel_orders_a_tank_timeline_across_date_and_datetime_fields(self):
		"""Inspection dates a Date, the work orders a Datetime. Sorting them together used
		to raise TypeError and take the whole panel down with it."""
		eir = self._eir(voucher=self.bon)
		self._order("Cleaning Order", inspection=eir)
		self._order("Repair Order", inspection=eir)

		orders = self._panel(self.booking)[CONTAINER_NO]["orders"]
		self.assertGreaterEqual(len(orders), 3)
		dated = [o["date"] for o in orders if o["date"]]
		self.assertEqual(dated, sorted(dated, key=lambda d: str(d)[:10]))

	def test_panel_counts_unattributed_work_without_claiming_it(self):
		"""A standalone order is surfaced as a candidate to attribute, never folded in."""
		standalone = self._order("Cleaning Order")
		self.assertFalse(standalone.container_booking)

		group = self._panel(self.multi)[CONTAINER_NO]
		self.assertNotIn(standalone.name, [o["name"] for o in group["orders"]])
		self.assertGreaterEqual(group["unlinked"], 1)

	# --- what the Connections badge counts as "open" ------------------------
	def test_open_count_follows_status_not_docstatus(self):
		"""The second number on a Connections link means "not finished yet".

		ERPNext hands every submittable doctype a blanket ``{"docstatus": 0}`` open filter,
		which got Cleaning Order wrong (its life is in ``status``; submitting is a separate
		act) and skipped Repair Order and Periodic Test Order entirely because they are not
		submittable — a booking with repairs in progress showed no badge at all.
		"""
		from frappe.desk.notifications import get_filters_for

		frappe.cache.hdel("notification_config", frappe.session.user)
		for doctype in ("Cleaning Order", "Repair Order", "Periodic Test Order"):
			with self.subTest(doctype=doctype):
				f = get_filters_for(doctype)
				self.assertIn("status", f, f"{doctype} must count open work by status")
				self.assertNotIn("docstatus", f)

	def test_a_finished_order_is_not_counted_open_while_unsubmitted(self):
		"""The concrete case the inherited docstatus rule got wrong."""
		from frappe.desk.notifications import get_open_count

		eir = self._eir(voucher=self.bon)
		done = self._order("Cleaning Order", inspection=eir)
		frappe.db.set_value(
			"Cleaning Order", done.name, {"status": "Completed", "docstatus": 0}, update_modified=False
		)
		frappe.cache.hdel("notification_config", frappe.session.user)

		counts = get_open_count("Container Booking", self.booking)["count"]["external_links_found"]
		cleaning = next(c for c in counts if c["doctype"] == "Cleaning Order")
		self.assertGreaterEqual(cleaning["count"], 1, "it is still linked...")
		self.assertEqual(cleaning["open_count"], 0, "...but nobody has to finish it")

	# --- backfill -----------------------------------------------------------
	def test_backfill_recovers_rows_written_before_the_field_existed(self):
		from container_depot.patches.v0_53.backfill_container_booking import execute

		eir = self._eir(voucher=self.bon)
		order = self._order("Cleaning Order", inspection=eir)
		# Simulate pre-field rows: the links are there, the attribution is not.
		for dt, name in (("Inspection", eir), ("Cleaning Order", order.name)):
			frappe.db.set_value(dt, name, "container_booking", None, update_modified=False)

		execute()

		self.assertEqual(frappe.db.get_value("Inspection", eir, "container_booking"), self.booking)
		self.assertEqual(
			frappe.db.get_value("Cleaning Order", order.name, "container_booking"), self.booking
		)
