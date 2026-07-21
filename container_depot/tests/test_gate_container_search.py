"""Gate PWA: resolving a container number (not just an exact code) to its active
booking — the single-match and multi-match branches of ``api.gate_lookup``.

A submitted Tank In booking issues one Active Booking Code per container on
``on_submit``; the gate can then be opened by typing/scanning the container number.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot import api
from container_depot.tests.test_api import ensure_test_customer

CUSTOMER = "Gate Search Co"
CONTAINER = "GSCU1112220"


def _insert_contract(customer: str) -> str:
	doc = frappe.get_doc({
		"doctype": "Depot Contract",
		"customer": customer,
		"currency": "IDR",
		"status": "Active",
		"payment_type": "TOP",
		"payment_terms": "NET 30",
		"credit_limit": 1_000_000,
		"valid_from": today(),
		"valid_to": add_days(today(), 365),
		"tariff_lines": [{"item": "Lift Off", "rate": 250000}],
	}).insert(ignore_permissions=True)
	return doc.name


def _cleanup(customer: str):
	bookings = frappe.get_all("Container Booking", filters={"customer": customer}, pluck="name")
	if bookings:
		frappe.db.delete("Booking Code", {"booking": ("in", bookings)})
		frappe.db.delete("Container Booking Item", {"parent": ("in", bookings)})
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
	# Every container this customer owns, not just Booked ones — a gated-in tank has
	# moved on to another status and would otherwise be left behind.
	containers = frappe.get_all("Container", filters={"principal": customer}, pluck="name")
	if containers:
		frappe.db.delete("Container Movement", {"container": ("in", containers)})
		frappe.db.delete("Container", {"name": ("in", containers)})
	# Invoices are raw-deleted (not delete_doc) because a submitted one refuses to go
	# without being cancelled first, and a cancelled one still lingers at docstatus 2.
	invoices = frappe.get_all("Sales Invoice", filters={"customer": customer}, pluck="name")
	if invoices:
		for dt in ("Sales Invoice Item", "Sales Taxes and Charges", "Payment Schedule"):
			frappe.db.delete(dt, {"parent": ("in", invoices)})
		frappe.db.sql(
			"DELETE FROM `tabGL Entry` WHERE voucher_type='Sales Invoice' AND voucher_no IN %(n)s",
			{"n": tuple(invoices)},
		)
		frappe.db.delete("Sales Invoice", {"name": ("in", invoices)})
	# The Customer itself is the last thing to go, so nothing above is orphaned.
	if frappe.db.exists("Customer", customer):
		frappe.db.delete("Customer", {"name": customer})
	frappe.db.commit()


class TestGateContainerSearch(FrappeTestCase):
	# Per-method setUp/tearDown, not setUpClass: submitting a booking commits (invoice
	# + notifications), bypassing FrappeTestCase's per-test rollback, so bookings would
	# otherwise accumulate across methods sharing the same container.
	def setUp(self):
		# Purge before creating, not after: _cleanup removes the Customer itself, so
		# the old order wiped the very customer this test then tried to build on.
		_cleanup(CUSTOMER)
		self.customer = ensure_test_customer(CUSTOMER)
		self.contract = _insert_contract(self.customer)

	def tearDown(self):
		_cleanup(self.customer)

	def _submit_booking(self, container_no: str) -> str:
		b = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"contract": self.contract,
			"booking_status": "Pending Confirmation",
			"do_reference": "DO-GS",
			"do_document": "/files/do.pdf",
			"items": [{"container_no": container_no}],
		}).insert(ignore_permissions=True)
		b.submit()
		return b.name

	def test_container_summary_populated_on_save(self):
		name = self._submit_booking(CONTAINER)
		self.assertEqual(frappe.db.get_value("Container Booking", name, "container_summary"), CONTAINER)

	def test_single_active_booking_resolves_to_detail(self):
		booking = self._submit_booking(CONTAINER)
		res = api.gate_lookup(CONTAINER)
		self.assertTrue(res["valid"])
		self.assertNotIn("choices", res)
		self.assertEqual(res["booking"], booking)
		self.assertTrue(any(c["container_no"] == CONTAINER for c in res["containers"]))

	def test_partial_match_falls_back_and_resolves(self):
		booking = self._submit_booking(CONTAINER)
		res = api.gate_lookup(CONTAINER[:6])  # exact miss -> LIKE fallback, single hit
		self.assertTrue(res["valid"])
		self.assertEqual(res["booking"], booking)
		self.assertTrue(any(c["container_no"] == CONTAINER for c in res["containers"]))

	def test_two_active_bookings_return_choices(self):
		b1 = self._submit_booking(CONTAINER)
		b2 = self._submit_booking(CONTAINER)
		res = api.gate_lookup(CONTAINER)
		self.assertTrue(res["valid"])
		self.assertIn("choices", res)
		names = {c["booking"] for c in res["choices"]}
		self.assertEqual(names, {b1, b2})
		self.assertTrue(all(c["container_no"] == CONTAINER for c in res["choices"]))

	def test_unknown_container_is_invalid(self):
		res = api.gate_lookup("NOSUCH9999999")
		self.assertFalse(res["valid"])
