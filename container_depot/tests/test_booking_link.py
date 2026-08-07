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
		cls.bon = _bon(cls.customer, cls.booking, cls.container, CONTAINER_NO)

	@classmethod
	def tearDownClass(cls):
		for doctype in ("Cleaning Order", "Repair Order", "Periodic Test Order", "Inspection"):
			frappe.db.delete(doctype, {"container": ("in", [cls.container, cls.other])})
		frappe.db.delete("Order Bongkar", {"booking": ("in", [cls.booking, cls.foreign_booking])})
		for booking in (cls.booking, cls.foreign_booking):
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
