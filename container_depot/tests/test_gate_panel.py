"""Gate PWA panel data — what the operator is shown before waving a tank through.

Three things the panel is built from beyond the booking header:

* ``finance_enabled`` — with finance off there is no invoice, so the payment rows must
  disappear rather than display a "Unpaid" that means nothing.
* ``open_orders`` per container — the work still holding the tank, i.e. the reason a
  gate-out would be refused, named so the operator can go and close it.
* the Shipper / Angkutan / EMKL picker options — ``shipper`` is a Link to Customer on
  both bon doctypes, so the gate must offer the master, not free text.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot import api, finance
from container_depot.tests.finance_fixture import require_finance
from container_depot.tests.test_api import ensure_test_customer

CUSTOMER = "Gate Panel Co"
EMKL = "Gate Panel EMKL"
CONTAINER = "GPCU3334440"


def _cleanup():
	for customer in (CUSTOMER, EMKL):
		bookings = frappe.get_all("Container Booking", filters={"customer": customer}, pluck="name")
		if bookings:
			frappe.db.delete("Booking Code", {"booking": ("in", bookings)})
			frappe.db.delete("Container Booking Item", {"parent": ("in", bookings)})
			frappe.db.delete("Container Booking Charge", {"parent": ("in", bookings)})
			frappe.db.delete("Container Booking", {"name": ("in", bookings)})
		contracts = frappe.get_all("Depot Contract", filters={"customer": customer}, pluck="name")
		if contracts:
			frappe.db.delete("Tariff Rate", {"parent": ("in", contracts)})
			frappe.db.delete("Depot Contract", {"name": ("in", contracts)})
		price_lists = frappe.get_all("Price List", filters={"customer": customer}, pluck="name")
		if price_lists:
			frappe.db.delete("Item Price", {"price_list": ("in", price_lists)})
			frappe.db.delete("Price List", {"name": ("in", price_lists)})
		frappe.db.set_value("Customer", customer, "default_price_list", None, update_modified=False)
		containers = frappe.get_all("Container", filters={"principal": customer}, pluck="name")
		if containers:
			frappe.db.delete("Cleaning Order", {"container": ("in", containers)})
			for log in ("Container Movement", "Container Activity"):
				frappe.db.delete(log, {"container": ("in", containers)})
			frappe.db.delete("Container", {"name": ("in", containers)})
		invoices = frappe.get_all("Sales Invoice", filters={"customer": customer}, pluck="name")
		if invoices:
			for dt in ("Sales Invoice Item", "Sales Taxes and Charges", "Payment Schedule"):
				frappe.db.delete(dt, {"parent": ("in", invoices)})
			frappe.db.sql(
				"DELETE FROM `tabGL Entry` WHERE voucher_type='Sales Invoice' AND voucher_no IN %(n)s",
				{"n": tuple(invoices)},
			)
			frappe.db.delete("Sales Invoice", {"name": ("in", invoices)})
		if frappe.db.exists("Customer", customer):
			frappe.db.delete("Customer", {"name": customer})
	frappe.db.commit()


class TestGatePanel(FrappeTestCase):
	# Per-method, not per-class: submitting a booking commits, so FrappeTestCase's
	# rollback cannot undo it and rows would pile up across methods.
	def setUp(self):
		require_finance(self)
		_cleanup()
		self.customer = ensure_test_customer(CUSTOMER)
		self.contract = frappe.get_doc({
			"doctype": "Depot Contract",
			"customer": self.customer,
			"currency": "IDR",
			"status": "Active",
			"payment_type": "TOP",
			"payment_terms": "NET 30",
			"credit_limit": 1_000_000,
			"valid_from": today(),
			"valid_to": add_days(today(), 365),
			"tariff_lines": [{"item": "Lift Off", "rate": 250000}],
		}).insert(ignore_permissions=True).name
		self.booking = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"contract": self.contract,
			"booking_status": "Pending Confirmation",
			"items": [{"container_no": CONTAINER}],
		}).insert(ignore_permissions=True)
		self.booking.submit()
		self.container = frappe.db.get_value("Container", {"container_no": CONTAINER}, "name")

	def tearDown(self):
		_cleanup()

	def _detail(self) -> dict:
		return api.gate_lookup(self.booking.name)

	def _open_cleaning(self):
		"""An unfinished cleaning on the test container, dropped again by the caller."""
		return frappe.get_doc({
			"doctype": "Cleaning Order",
			"container": self.container,
			"status": "Service Setup",
		}).insert(ignore_permissions=True)

	# --- finance state -----------------------------------------------------------

	def test_detail_reports_the_finance_state(self):
		"""The panel cannot ask the switch itself — it only sees this payload."""
		self.assertTrue(self._detail()["finance_enabled"])

	def test_detail_reports_finance_off(self):
		frappe.db.set_single_value("Depot Finance Settings", "enable_finance", 0)
		finance.clear_cache()
		self.assertFalse(self._detail()["finance_enabled"])

	# --- open orders -------------------------------------------------------------

	def test_container_carries_no_open_orders_when_nothing_holds_it(self):
		"""Readiness is the ABSENCE of open work — a tank nobody raised an order for is
		free to go, and the gate must not invent a blocker for it."""
		self.assertEqual(self._detail()["containers"][0]["open_orders"], [])

	def test_container_names_the_order_holding_it(self):
		co = self._open_cleaning()
		try:
			open_orders = self._detail()["containers"][0]["open_orders"]
			self.assertEqual([o["name"] for o in open_orders], [co.name])
			self.assertEqual(open_orders[0]["label"], "Cleaning")
			self.assertEqual(open_orders[0]["status"], "Service Setup")
		finally:
			frappe.delete_doc("Cleaning Order", co.name, force=True, ignore_permissions=True)

	# --- shipper picker ----------------------------------------------------------

	def _shippers(self) -> list[dict]:
		return api.gate_shipper_options()["shippers"]

	def test_shipper_options_lead_with_the_emkl_flagged_customers(self):
		emkl = ensure_test_customer(EMKL)
		frappe.db.set_value("Customer", emkl, "is_transporter", 1)
		rows = self._shippers()
		flagged = [r for r in rows if r["is_transporter"]]
		self.assertIn(emkl, [r["name"] for r in flagged])
		# Flagged first, so the picker's EMKL group renders at the top.
		self.assertEqual(rows[: len(flagged)], flagged)

	def test_shipper_options_keep_the_unflagged_customers(self):
		"""A booking line's shipper defaults to the booking's own Customer, which is
		usually a tank owner and not flagged. Filtering those out would make the
		pre-filled value unselectable — and a depot that has ticked nobody would meet an
		empty picker at the gate."""
		names = [r["name"] for r in self._shippers()]
		self.assertIn(self.customer, names)

	def test_shipper_options_skip_disabled_customers(self):
		frappe.db.set_value("Customer", self.customer, "disabled", 1)
		try:
			self.assertNotIn(self.customer, [r["name"] for r in self._shippers()])
		finally:
			frappe.db.set_value("Customer", self.customer, "disabled", 0)
