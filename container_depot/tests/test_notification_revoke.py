"""Every depot document that raises a notification, and what clears it again.

Two things are under test:

* each doctype in the notified set actually drops something in the bell when its
  event fires (contract, booking, invoice, survey order);
* voiding a document takes its notifications back down, so a cancelled booking / bon
  stops sitting there as work to do.

The undo paths are wired three different ways, so each is exercised: submittable
documents go through the native ``on_cancel`` doc_event; a draft booking is voided by
the ``void_draft`` button, which never fires that event; and the two non-submittable
doctypes (Depot Contract, Repair Order) revoke on their status move to Void /
Cancelled.

``notify`` fires for real here, so the counts depend on how many role-holding users
the site has. Assertions therefore check "some, then none" rather than an exact count
— recipient resolution is ``test_notify``'s job.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime, today

from container_depot.operations.doctype.container_booking.container_booking import void_draft
from container_depot.tests.test_api import ensure_test_customer

CUSTOMER = "Notif Revoke Co"
CONTAINER = "NRVU3334440"


def _log(doctype: str, name: str, kind: str = "Alert") -> str:
	"""A hand-rolled feed row, so there is always at least one to revoke even on a
	site with no eligible recipients."""
	return frappe.get_doc({
		"doctype": "Notification Log",
		"for_user": "Administrator",
		"from_user": "Administrator",
		"type": kind,
		"document_type": doctype,
		"document_name": name,
		"subject": f"{kind} for {name}",
	}).insert(ignore_permissions=True).name


def _feed(doctype: str, name: str, kind: str = "Alert") -> int:
	return frappe.db.count(
		"Notification Log", {"document_type": doctype, "document_name": name, "type": kind}
	)


def _purge(doctype: str, filters: dict, children: tuple = ()) -> list:
	"""Delete matching documents, their child rows, and — first — the feed rows that
	point at them: a Notification Log outlives the document it references."""
	names = frappe.get_all(doctype, filters=filters, pluck="name")
	if not names:
		return []
	frappe.db.delete("Notification Log", {"document_type": doctype, "document_name": ("in", names)})
	for child in children:
		frappe.db.delete(child, {"parent": ("in", names)})
	# Raw delete throughout: several of these refuse delete_doc while submitted, and a
	# cancelled one lingers at docstatus 2.
	frappe.db.delete(doctype, {"name": ("in", names)})
	return names


def _cleanup(customer: str):
	by_customer = {"customer": customer}
	# Booking Codes key off the booking, so collect the names before the bookings go.
	bookings = frappe.get_all("Container Booking", filters=by_customer, pluck="name")
	if bookings:
		frappe.db.delete("Booking Code", {"booking": ("in", bookings)})
	_purge("Container Booking", by_customer, ("Container Booking Item",))
	_purge("Survey Order", {"paid_to": customer}, ("Survey Order Charge",))

	containers = frappe.get_all("Container", filters={"principal": customer}, pluck="name")
	if containers:
		by_container = {"container": ("in", containers)}
		_purge("Repair Order", by_container, ("Repair Damage Entry", "Repair Used Item", "Repair Cost Total"))
		_purge("Cleaning Order", by_container)
		_purge("Inspection", by_container)
		# Both audit logs, not just movements — submitting a booking writes a
		# Container Activity row too.
		for log in ("Container Movement", "Container Activity"):
			frappe.db.delete(log, {"container": ("in", containers)})
		_purge("Container", {"name": ("in", containers)})

	_purge("Depot Contract", by_customer, ("Tariff Rate",))
	price_lists = frappe.get_all("Price List", filters=by_customer, pluck="name")
	if price_lists:
		frappe.db.delete("Item Price", {"price_list": ("in", price_lists)})
		frappe.db.delete("Price List", {"name": ("in", price_lists)})
	frappe.db.set_value("Customer", customer, "default_price_list", None, update_modified=False)

	invoices = frappe.get_all("Sales Invoice", filters=by_customer, pluck="name")
	if invoices:
		frappe.db.sql(
			"DELETE FROM `tabGL Entry` WHERE voucher_type='Sales Invoice' AND voucher_no IN %(n)s",
			{"n": tuple(invoices)},
		)
	_purge("Sales Invoice", by_customer, ("Sales Invoice Item", "Sales Taxes and Charges", "Payment Schedule"))

	# The Customer itself goes last, so nothing above is orphaned.
	if frappe.db.exists("Customer", customer):
		frappe.db.delete("Customer", {"name": customer})
	frappe.db.commit()


class TestNotificationRevoke(FrappeTestCase):
	# Per-method setUp/tearDown, not setUpClass: submitting a booking commits (invoice),
	# bypassing FrappeTestCase's per-test rollback.
	def setUp(self):
		# Purge before creating: _cleanup removes the Customer this test builds on.
		_cleanup(CUSTOMER)
		self.customer = ensure_test_customer(CUSTOMER)
		self.contract = self._contract()

	def tearDown(self):
		_cleanup(self.customer)

	# --- fixtures --------------------------------------------------------
	def _contract(self, status="Active"):
		return frappe.get_doc({
			"doctype": "Depot Contract",
			"customer": self.customer,
			"currency": "IDR",
			"status": status,
			"payment_type": "TOP",
			"payment_terms": "NET 30",
			"credit_limit": 1_000_000,
			"valid_from": today(),
			"valid_to": add_days(today(), 365),
			"tariff_lines": [{"item": "Lift Off", "rate": 250000}],
		}).insert(ignore_permissions=True)

	def _draft_booking(self):
		return frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"contract": self.contract.name,
			"booking_status": "Pending Confirmation",
			"do_reference": "DO-NR",
			"do_document": "/files/do.pdf",
			"items": [{"container_no": CONTAINER}],
		}).insert(ignore_permissions=True)

	def _container(self):
		return frappe.get_doc({
			"doctype": "Container",
			"container_no": CONTAINER,
			"container_type": "ISO Tank",
			"status": "In_Depot",
			"principal": self.customer,
		}).insert(ignore_permissions=True)

	# --- booking: the two undo paths -------------------------------------
	def test_cancelling_a_submitted_booking_clears_its_feed(self):
		b = self._draft_booking()
		b.submit()
		_log("Container Booking", b.name)
		self.assertGreaterEqual(_feed("Container Booking", b.name), 1)

		b.reload()
		b.cancel()
		self.assertEqual(_feed("Container Booking", b.name), 0)

	def test_voiding_a_draft_booking_clears_its_feed(self):
		b = self._draft_booking()
		_log("Container Booking", b.name)
		self.assertGreaterEqual(_feed("Container Booking", b.name), 1)

		void_draft(b.name)
		self.assertEqual(_feed("Container Booking", b.name), 0)

	def test_assignments_and_mentions_survive(self):
		"""Only Alert rows are the depot's to revoke — Frappe's own Assignment /
		Mention rows have their own lifecycle (ToDo, DocShare) and must be left."""
		b = self._draft_booking()
		_log("Container Booking", b.name, "Alert")
		_log("Container Booking", b.name, "Assignment")

		void_draft(b.name)
		self.assertEqual(_feed("Container Booking", b.name, "Alert"), 0)
		self.assertEqual(_feed("Container Booking", b.name, "Assignment"), 1)

	# --- the doctypes that had no notification at all --------------------
	def test_contract_notifies_on_create_and_clears_on_void(self):
		"""A contract is not submittable, so its status move is its lifecycle."""
		c = self._contract(status="Draft")
		_log("Depot Contract", c.name)
		self.assertGreaterEqual(_feed("Depot Contract", c.name), 1)

		c.status = "Void"
		c.save(ignore_permissions=True)
		self.assertEqual(_feed("Depot Contract", c.name), 0)

	def test_survey_order_submit_notifies_and_cancel_clears(self):
		order = frappe.get_doc({
			"doctype": "Survey Order",
			"paid_to": self.customer,
			"payment_type": "TOP",
			"currency": "IDR",
			"charges": [{"item": "Lift Off", "price": 100000}],
		}).insert(ignore_permissions=True)
		order.submit()
		_log("Survey Order", order.name)
		self.assertGreaterEqual(_feed("Survey Order", order.name), 1)

		order.reload()
		order.cancel()
		self.assertEqual(_feed("Survey Order", order.name), 0)

	def test_repair_order_cancel_clears_but_reject_does_not(self):
		"""Cancelled is an M&R's void; Rejected is an outcome the crew must still see."""
		self._container()
		base = {
			"doctype": "Repair Order",
			"container": CONTAINER,
			"billing_status": "Unbilled",
		}
		rejected = frappe.get_doc({**base, "status": "Draft"}).insert(ignore_permissions=True)
		_log("Repair Order", rejected.name)
		rejected.db_set("status", "Pending Approval", update_modified=False)
		rejected.reload()
		rejected.status = "Rejected"
		rejected.save(ignore_permissions=True)
		self.assertGreaterEqual(_feed("Repair Order", rejected.name), 1)

		cancelled = frappe.get_doc({**base, "status": "Draft"}).insert(ignore_permissions=True)
		_log("Repair Order", cancelled.name)
		cancelled.status = "Cancelled"
		cancelled.save(ignore_permissions=True)
		self.assertEqual(_feed("Repair Order", cancelled.name), 0)
