"""Acceptance tests for on-demand consolidated postpaid billing
(``consolidated_billing.bill_customer``).

- A submitted TOP Container Booking is swept into a consolidated draft Sales Invoice
  and linked back (``sales_invoice`` set, ``payment_status`` = Invoiced).
- A Cash booking settles at the booking itself and is NOT swept.
- The sweep is idempotent: a second run finds nothing new.
- **Multi-currency**: a customer with USD + IDR orders gets ONE draft invoice per
  currency, each billed in its own currency (never forced to the company default).

``bill_customer`` returns the list of created Sales Invoice names (``[]`` = nothing).
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, today

from container_depot import invoicing
from container_depot.consolidated_billing import bill_customer
from container_depot.tests.finance_fixture import require_finance
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_container_booking import (
	_cleanup_customer_world,
	_make_active_contract,
)


def _ensure_service_item():
	"""A non-stock service item for the M&R fixture — non-stock so the Repair Order's
	stock guard (``mr.assert_stock_available``) has nothing to check."""
	code = "CB-TEST-MR-SERVICE"
	if not frappe.db.exists("Item", code):
		frappe.get_doc({
			"doctype": "Item", "item_code": code, "item_name": "CB Test M&R Service",
			"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups",
			"stock_uom": "Nos", "is_stock_item": 0, "is_sales_item": 1,
		}).insert(ignore_permissions=True)
	return code


def _cleanup_bookings(customer):
	"""Raw-delete every Container Booking for the customer (+ its items / charges /
	codes), regardless of docstatus, and drop any leftover draft Sales Invoices."""
	bookings = frappe.get_all("Container Booking", filters={"customer": customer}, pluck="name")
	if bookings:
		frappe.db.delete("Booking Code", {"booking": ("in", bookings)})
		frappe.db.delete("Container Booking Item", {"parent": ("in", bookings)})
		frappe.db.delete("Container Booking Charge", {"parent": ("in", bookings)})
		frappe.db.delete("Container Booking", {"name": ("in", bookings)})
	# Pre-arrival (Booked) phantom tanks the booking spawned reserve their number, so a
	# later booking in the same class would collide with them.
	booked = frappe.get_all("Container", filters={"principal": customer, "status": "Booked"}, pluck="name")
	if booked:
		frappe.db.delete("Container Movement", {"container": ("in", booked)})
		frappe.db.delete("Container", {"name": ("in", booked)})
	# Invoices the fixtures raised. Anything a Payment Entry references is left alone —
	# that one carries GL entries, and ripping it out from under them is worse than the
	# stray row. Everything else is a draft (or a forged Cash settlement) and goes.
	paid = set(
		frappe.get_all(
			"Payment Entry Reference",
			filters={"reference_doctype": "Sales Invoice"},
			pluck="reference_name",
		)
	)
	for si in frappe.get_all("Sales Invoice", filters={"customer": customer}, pluck="name"):
		if si in paid:
			continue
		frappe.db.delete("Sales Invoice Item", {"parent": si})
		frappe.db.delete("Sales Invoice", {"name": si})
	frappe.db.commit()


_TANK_SEQ = [0]


def _next_tank():
	"""A fresh tank number per booking — a live booking RESERVES its containers."""
	_TANK_SEQ[0] += 1
	return f"CBTU{_TANK_SEQ[0]:07d}"


def _make_booking(customer, contract, item, payment_type, price, currency=None):
	"""Insert + submit a one-charge Container Booking for ``customer``.

	``currency`` is stamped straight onto the row: a booking derives its currency from the
	price list its contract published, and the multi-currency case here is about what the
	sweep does with two currencies, not about how a booking gets one.

	Cash is pay-first — a Cash booking refuses to submit until its invoice is raised AND
	settled, then auto-submits — so it goes through that door rather than ``submit()``."""
	from container_depot.container_depot.doctype.container_booking.container_booking import (
		generate_invoice,
		sync_bookings_for_invoice,
	)

	doc = frappe.get_doc({
		"doctype": "Container Booking",
		"direction": "Tank In",
		"customer": customer,
		"contract": contract,
		"payment_type": payment_type,
		"do_reference": "DO-CB-TEST",
		"do_document": "/files/do.pdf",
		"items": [{"container_no": _next_tank()}],
		"charges": [{"item": item, "qty": 1, "rate": price}],
	})
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	if payment_type == "Cash":
		generate_invoice(doc.name)
		si = frappe.db.get_value("Container Booking", doc.name, "sales_invoice")
		frappe.db.set_value(
			"Sales Invoice", si, {"docstatus": 1, "status": "Paid", "outstanding_amount": 0}
		)
		sync_bookings_for_invoice(si)
	else:
		doc.submit()
	if currency:
		frappe.db.set_value("Container Booking", doc.name, "currency", currency, update_modified=False)
	doc.reload()
	return doc


class TestConsolidatedBillingBooking(FrappeTestCase):
	"""TOP bookings flow into the consolidated draft; Cash ones stay out."""

	CUSTOMER = "Consolidated Billing TOP Co"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		require_finance(cls)
		cls.item = invoicing.ensure_service_item()
		cls.customer = ensure_test_customer(cls.CUSTOMER)
		_cleanup_bookings(cls.customer)
		_cleanup_customer_world(cls.customer)
		# "Both" so one customer can raise a TOP booking AND a Cash one: the per-order
		# payment_type is what decides whether the sweep takes it, not the contract.
		cls.contract = _make_active_contract(
			cls.customer, payment_type="Both", credit_limit=1_000_000_000, payment_terms="NET 30"
		)

	@classmethod
	def tearDownClass(cls):
		_cleanup_bookings(cls.customer)
		_cleanup_customer_world(cls.customer)
		super().tearDownClass()

	def setUp(self):
		# Each test starts from a clean slate (bookings accrue + commit across tests).
		_cleanup_bookings(self.customer)

	def test_top_booking_swept_into_draft_invoice(self):
		booking = _make_booking(self.customer, self.contract, self.item, "TOP", 500000)
		self.assertFalse(booking.sales_invoice, "TOP booking carries no invoice at submit")

		sis = bill_customer(self.customer)
		self.assertEqual(len(sis), 1, "one consolidated draft Sales Invoice (single currency)")
		si = sis[0]

		booking.reload()
		self.assertEqual(booking.sales_invoice, si, "booking linked to the consolidated invoice")
		self.assertEqual(booking.payment_status, "Invoiced")

		inv = frappe.get_doc("Sales Invoice", si)
		self.assertEqual(inv.docstatus, 0, "consolidated invoice is a draft")
		self.assertEqual(inv.currency, "IDR", "billed in the booking's currency")
		self.assertTrue(
			any(abs(flt(row.rate) - 500000) < 1 for row in inv.items),
			"the booking charge is a line on the consolidated invoice",
		)

		self.assertEqual(bill_customer(self.customer), [], "re-run finds nothing unbilled (idempotent)")

	def test_cash_booking_not_swept(self):
		cash = _make_booking(self.customer, self.contract, self.item, "Cash", 300000)
		own_si = cash.sales_invoice
		self.assertTrue(own_si, "a Cash booking settles at its own invoice")

		self.assertEqual(
			bill_customer(self.customer), [], "a Cash booking is never swept into consolidated billing"
		)
		cash.reload()
		self.assertEqual(cash.sales_invoice, own_si, "Cash booking keeps its own invoice")

	def test_multi_currency_one_invoice_per_currency(self):
		usd = _make_booking(self.customer, self.contract, self.item, "TOP", 500, currency="USD")
		idr = _make_booking(self.customer, self.contract, self.item, "TOP", 700000, currency="IDR")

		sis = bill_customer(self.customer)
		self.assertEqual(len(sis), 2, "one draft invoice per currency")
		currencies = {frappe.db.get_value("Sales Invoice", s, "currency") for s in sis}
		self.assertEqual(currencies, {"USD", "IDR"}, "each invoice billed in its own currency")

		usd.reload()
		idr.reload()
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", usd.sales_invoice, "currency"), "USD",
			"USD booking linked to the USD invoice",
		)
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", idr.sales_invoice, "currency"), "IDR",
			"IDR booking linked to the IDR invoice",
		)
		# The USD charge is billed at face value (conversion_rate 1, no FX to IDR).
		usd_inv = frappe.get_doc("Sales Invoice", usd.sales_invoice)
		self.assertTrue(any(abs(flt(r.rate) - 500) < 1 for r in usd_inv.items))

	def test_discard_draft_rolls_back_orders(self):
		booking = _make_booking(self.customer, self.contract, self.item, "TOP", 500000)
		sis = bill_customer(self.customer)
		self.assertEqual(len(sis), 1)
		si = sis[0]
		booking.reload()
		self.assertEqual(booking.sales_invoice, si)

		# Discard (delete) the generated draft invoice → orders roll back to un-invoiced.
		frappe.delete_doc("Sales Invoice", si, ignore_permissions=True)
		self.assertFalse(frappe.db.exists("Sales Invoice", si), "draft invoice discarded")
		booking.reload()
		self.assertFalse(booking.sales_invoice, "booking link cleared on discard")
		self.assertEqual(booking.payment_status, "Unpaid", "booking rolled back to un-invoiced")

		# The order is billable again — a re-generate resyncs it into a fresh invoice.
		# (The invoice name may coincide with the discarded one: Frappe reverts the
		# naming-series counter when the last document is deleted.)
		sis2 = bill_customer(self.customer)
		self.assertEqual(len(sis2), 1, "order billable again after rollback")
		self.assertTrue(frappe.db.exists("Sales Invoice", sis2[0]))
		booking.reload()
		self.assertEqual(booking.sales_invoice, sis2[0], "booking re-linked to the regenerated invoice")

	def test_discard_one_currency_rolls_back_only_that_currency(self):
		usd = _make_booking(self.customer, self.contract, self.item, "TOP", 500, currency="USD")
		idr = _make_booking(self.customer, self.contract, self.item, "TOP", 700000, currency="IDR")
		sis = bill_customer(self.customer)
		self.assertEqual(len(sis), 2)
		usd.reload()
		idr.reload()
		usd_si, idr_si = usd.sales_invoice, idr.sales_invoice
		self.assertTrue(usd_si and idr_si and usd_si != idr_si)

		frappe.delete_doc("Sales Invoice", usd_si, ignore_permissions=True)
		usd.reload()
		idr.reload()
		self.assertFalse(usd.sales_invoice, "USD booking rolled back on discard")
		self.assertEqual(usd.payment_status, "Unpaid")
		self.assertEqual(idr.sales_invoice, idr_si, "IDR booking untouched by USD discard")

	def test_generated_invoice_items_cannot_be_deleted(self):
		doc = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"contract": self.contract,
			"payment_type": "TOP",
			"do_reference": "DO-CB-TEST",
			"do_document": "/files/do.pdf",
			"items": [{"container_no": _next_tank()}],
			"charges": [
				{"item": self.item, "qty": 1, "rate": 100000},
				{"item": self.item, "qty": 1, "rate": 200000},
			],
		})
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		doc.submit()

		sis = bill_customer(self.customer)
		si = frappe.get_doc("Sales Invoice", sis[0])
		self.assertEqual(len(si.items), 2, "two generated lines")

		# Removing a generated line must be rejected — the invoice mirrors its orders.
		del si.items[-1]
		with self.assertRaises(frappe.ValidationError):
			si.save(ignore_permissions=True)

	def test_generated_invoice_submit_and_pay_reflects_paid(self):
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		booking = _make_booking(self.customer, self.contract, self.item, "TOP", 500000)
		si = frappe.get_doc("Sales Invoice", bill_customer(self.customer)[0])

		# The item-freeze guard must NOT block a legitimate submit.
		si.submit()
		booking.reload()
		self.assertEqual(booking.payment_status, "Invoiced", "submitted invoice → still unsettled")

		pe = get_payment_entry("Sales Invoice", si.name)
		if not pe.paid_to:
			acc = frappe.db.get_value(
				"Account",
				{"company": si.company, "account_type": ["in", ["Bank", "Cash"]], "is_group": 0},
				"name",
			)
			pe.paid_to = acc
			pe.paid_to_account_currency = frappe.db.get_value("Account", acc, "account_currency")
		pe.reference_no = "TEST-PAY"
		pe.reference_date = today()
		pe.insert(ignore_permissions=True)
		pe.submit()

		si.reload()
		booking.reload()
		self.assertEqual(si.status, "Paid", "consolidated invoice marked Paid natively")
		self.assertEqual(booking.payment_status, "Paid", "booking reflects Paid after payment")

	def test_repair_links_invoice_and_rolls_back(self):
		cno = "TESTMR00001"
		frappe.db.delete("Repair Order", {"container": cno})
		if frappe.db.exists("Container", cno):
			frappe.db.delete("Container", cno)
		cont = frappe.get_doc({
			"doctype": "Container", "container_no": cno, "container_type": "ISO Tank",
			"status": "Available", "principal": self.customer,
		})
		cont.flags.ignore_mandatory = True
		cont.insert(ignore_permissions=True)
		# An M&R is billed item by item (so the invoice can charge labour off each
		# item_code), so the fixture needs a real used-item line — a bare total_cost no
		# longer produces anything to bill.
		service = _ensure_service_item()
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": cno, "status": "Draft", "billing_status": "Unbilled",
			"used_items": [{"item": service, "quantity": 1, "item_rate": 100000}],
		})
		ro.flags.ignore_mandatory = True
		ro.insert(ignore_permissions=True)
		# Force it into a completed, unbilled, costed state (bypass the M&R workflow / cost recompute).
		frappe.db.set_value("Repair Order", ro.name, {
			"status": "Completed", "billing_status": "Unbilled",
			"completion_date": today(), "total_cost": 100000, "principal": self.customer,
		}, update_modified=False)

		try:
			sis = bill_customer(self.customer)
			self.assertEqual(len(sis), 1, "repair swept into one invoice")
			si = sis[0]
			self.assertEqual(
				frappe.db.get_value("Repair Order", ro.name, "sales_invoice"), si,
				"repair linked to the generated invoice",
			)
			self.assertEqual(frappe.db.get_value("Repair Order", ro.name, "billing_status"), "Client Billed")

			# Discard the draft → repair rolls back to un-invoiced (link cleared, Unbilled).
			frappe.delete_doc("Sales Invoice", si, ignore_permissions=True)
			self.assertFalse(
				frappe.db.get_value("Repair Order", ro.name, "sales_invoice"),
				"repair link cleared on discard",
			)
			self.assertEqual(frappe.db.get_value("Repair Order", ro.name, "billing_status"), "Unbilled")
		finally:
			frappe.db.delete("Repair Used Item", {"parent": ro.name, "parenttype": "Repair Order"})
			frappe.db.delete("Repair Order", {"name": ro.name})
			frappe.db.delete("Container", cno)
			# The fixture item is created here, so it is removed here — the row above must go
			# first or the Item delete trips its link check.
			if frappe.db.exists("Item", service):
				frappe.delete_doc("Item", service, force=True, ignore_permissions=True)
			frappe.db.commit()


class TestConsolidatedBillingCashContract(FrappeTestCase):
	"""A Cash-contract customer accrues nothing for the consolidated sweep.

	Its bookings are forced to Cash (they settle at the booking), and the contract-level
	accruals — cleaning / M&R / storage — are gated on ``_is_postpaid``, so the monthly
	scheduler bills them instead. Sweeping them here too would double-charge.
	"""

	CUSTOMER = "Consolidated Billing Cash Co"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		require_finance(cls)
		cls.item = invoicing.ensure_service_item()
		cls.customer = ensure_test_customer(cls.CUSTOMER)
		_cleanup_bookings(cls.customer)
		_cleanup_customer_world(cls.customer)
		cls.contract = _make_active_contract(cls.customer, payment_type="Cash")

	@classmethod
	def tearDownClass(cls):
		_cleanup_bookings(cls.customer)
		_cleanup_customer_world(cls.customer)
		super().tearDownClass()

	def setUp(self):
		_cleanup_bookings(self.customer)

	def test_cash_contract_customer_has_nothing_to_sweep(self):
		booking = _make_booking(self.customer, self.contract, self.item, "Cash", 400000)
		self.assertEqual(booking.payment_type, "Cash", "a Cash contract forces the booking to Cash")
		own_si = booking.sales_invoice
		self.assertEqual(bill_customer(self.customer), [], "nothing accrues for a Cash contract")
		booking.reload()
		self.assertEqual(booking.sales_invoice, own_si, "the sweep left the Cash booking alone")
