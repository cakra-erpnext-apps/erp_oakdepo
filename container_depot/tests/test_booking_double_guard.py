"""One container, one open booking.

The status gates never caught a double booking: a Tank In tank sits at ``Booked``
(not in ``PRESENT``) and a Tank Out booking leaves the tank on ``Available``, so in
both directions a second booking submitted cleanly and the gate ended up holding two
live Booking Codes for the same tank.

The guard keys off the Booking Code instead — ``Active`` means "confirmed, no bon
yet". The two release paths (bon issued -> ``Used``; booking cancelled -> voided) must
both stop blocking, so each has its own test.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot.tests.test_api import ensure_test_customer

CUSTOMER = "Double Booking Co"
C_IN = "DBGU1110001"
C_OUT = "DBGU1110002"
CONTAINERS = (C_IN, C_OUT)


def _purge(doctype: str, filters: dict, children: tuple = ()):
	names = frappe.get_all(doctype, filters=filters, pluck="name")
	if not names:
		return
	frappe.db.delete("Notification Log", {"document_type": doctype, "document_name": ("in", names)})
	for child in children:
		frappe.db.delete(child, {"parent": ("in", names)})
	frappe.db.delete(doctype, {"name": ("in", names)})


def _cleanup():
	by_customer = {"customer": CUSTOMER}
	bookings = frappe.get_all("Container Booking", filters=by_customer, pluck="name")
	if bookings:
		frappe.db.delete("Booking Code", {"booking": ("in", bookings)})
	_purge("Container Booking", by_customer, ("Container Booking Item",))
	# Both audit logs, not just movements: submitting a booking writes a Container
	# Activity row too, and leaving those behind strands them on a deleted container.
	for log in ("Container Movement", "Container Activity"):
		frappe.db.delete(log, {"container": ("in", CONTAINERS)})
	_purge("Container", {"name": ("in", CONTAINERS)})
	_purge("Depot Contract", by_customer, ("Tariff Rate",))
	price_lists = frappe.get_all("Price List", filters=by_customer, pluck="name")
	if price_lists:
		frappe.db.delete("Item Price", {"price_list": ("in", price_lists)})
		frappe.db.delete("Price List", {"name": ("in", price_lists)})
	frappe.db.set_value("Customer", CUSTOMER, "default_price_list", None, update_modified=False)
	invoices = frappe.get_all("Sales Invoice", filters=by_customer, pluck="name")
	if invoices:
		frappe.db.sql(
			"DELETE FROM `tabGL Entry` WHERE voucher_type='Sales Invoice' AND voucher_no IN %(n)s",
			{"n": tuple(invoices)},
		)
	_purge("Sales Invoice", by_customer,
		   ("Sales Invoice Item", "Sales Taxes and Charges", "Payment Schedule"))
	if frappe.db.exists("Customer", CUSTOMER):
		frappe.db.delete("Customer", {"name": CUSTOMER})
	frappe.db.commit()


class TestBookingDoubleGuard(FrappeTestCase):
	# Per-method setUp/tearDown: submitting a booking commits (invoice + notifications),
	# bypassing FrappeTestCase's per-test rollback.
	def setUp(self):
		# Purge before creating: _cleanup removes the Customer this test builds on.
		_cleanup()
		self.customer = ensure_test_customer(CUSTOMER)
		self.contract = frappe.get_doc({
			"doctype": "Depot Contract",
			"customer": self.customer,
			"currency": "IDR",
			"status": "Active",
			"payment_type": "TOP",
			"payment_terms": "NET 30",
			"credit_limit": 10_000_000,
			"valid_from": today(),
			"valid_to": add_days(today(), 365),
			"tariff_lines": [{"item": "Lift Off", "rate": 250000}],
		}).insert(ignore_permissions=True).name

	def tearDown(self):
		_cleanup()

	def _book(self, container_no, direction="Tank In", submit=True):
		b = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": direction,
			"customer": self.customer,
			"contract": self.contract,
			"booking_status": "Pending Confirmation",
			"do_reference": "DO-DBG",
			"do_document": "/files/do.pdf",
			"items": [{"container_no": container_no}],
		}).insert(ignore_permissions=True)
		if submit:
			b.submit()
		return b

	def _available_container(self, cno):
		return frappe.get_doc({
			"doctype": "Container",
			"container_no": cno,
			"container_type": "ISO Tank",
			"status": "Available",
			"principal": self.customer,
		}).insert(ignore_permissions=True).name

	def test_second_tank_in_booking_is_blocked(self):
		first = self._book(C_IN)
		# The tank sits at Booked, which the presence gate lets through — this guard is
		# the only thing standing between it and a second live code.
		self.assertEqual(frappe.db.get_value("Container", C_IN, "status"), "Booked")

		with self.assertRaises(frappe.ValidationError) as cm:
			self._book(C_IN)
		self.assertIn(first.name, str(cm.exception))
		self.assertEqual(frappe.db.count("Booking Code", {"container_no": C_IN, "state": "Active"}), 1)

	def test_second_tank_out_booking_is_blocked(self):
		self._available_container(C_OUT)
		first = self._book(C_OUT, "Tank Out")
		# A Tank Out booking leaves the tank Available, so the readiness gate passes too.
		self.assertEqual(frappe.db.get_value("Container", C_OUT, "status"), "Available")

		with self.assertRaises(frappe.ValidationError) as cm:
			self._book(C_OUT, "Tank Out")
		self.assertIn(first.name, str(cm.exception))

	def test_a_consumed_code_no_longer_blocks(self):
		"""Once the bon is issued the code goes Used and the tank is in motion, so the
		next cycle's booking is legitimate."""
		self._book(C_IN)
		frappe.db.set_value(
			"Booking Code", {"container_no": C_IN, "state": "Active"}, "state", "Used",
			update_modified=False,
		)
		# Booked is not PRESENT, so the presence gate stays out of the way here.
		self._book(C_IN)  # must not raise

	def test_a_cancelled_booking_no_longer_blocks(self):
		first = self._book(C_IN)
		first.reload()
		first.cancel()

		self._book(C_IN)  # must not raise

	def test_a_draft_does_not_block(self):
		"""Codes are only issued at submit, so an unsubmitted draft reserves nothing —
		whichever booking submits first wins."""
		self._book(C_IN, submit=False)
		self._book(C_IN)  # must not raise
