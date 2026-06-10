"""Tests for the three Phase-3 critical controllers:

1. TOP credit-block (Container Booking.before_submit).
2. TANK OUT gating (Container Booking.validate when direction == 'Tank Out').
3. 72h Booking Code expiry (container_depot.tasks.expire_booking_codes).
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, now_datetime, today

from container_depot.tasks import expire_booking_codes
from container_depot.tests.test_api import ensure_test_customer


CUSTOMER_CASH = "Phase3 Cash Customer"
CUSTOMER_TOP = "Phase3 TOP Customer"
CONTAINER_NO = "TSTU3334440"


def _cleanup_customer_world(customer: str):
	bookings = frappe.get_all("Container Booking", filters={"customer": customer}, pluck="name")
	if bookings:
		frappe.db.delete("Booking Code", {"booking": ("in", bookings)})
		frappe.db.delete("Container Booking Item", {"parent": ("in", bookings)})
		frappe.db.delete("Container Booking", {"name": ("in", bookings)})
	contracts = frappe.get_all("Depot Contract", filters={"customer": customer}, pluck="name")
	if contracts:
		frappe.db.delete("Tariff Rate", {"parent": ("in", contracts)})
		frappe.db.delete("Depot Contract", {"name": ("in", contracts)})
	# Price Lists an Active contract published for this customer (+ their Item Prices).
	# Deleting the contract above orphans them; drop them too or they leak into the site
	# and clutter the Base Price List picker.
	price_lists = frappe.get_all("Price List", filters={"customer": customer}, pluck="name")
	if price_lists:
		frappe.db.delete("Item Price", {"price_list": ("in", price_lists)})
		frappe.db.delete("Price List", {"name": ("in", price_lists)})
	frappe.db.set_value("Customer", customer, "default_price_list", None, update_modified=False)
	# Auto-created draft Cash invoices (B6) — drop drafts so they don't accumulate.
	frappe.db.delete("Sales Invoice", {"customer": customer, "docstatus": 0})
	# Pre-arrival (Booked) phantom containers spawned by booking resolution (B6).
	booked = frappe.get_all("Container", filters={"principal": customer, "status": "Booked"}, pluck="name")
	if booked:
		frappe.db.delete("Container Movement", {"container": ("in", booked)})
		frappe.db.delete("Container", {"name": ("in", booked)})
	frappe.db.commit()


def _make_active_contract(customer: str, *, payment_type: str, credit_limit=0, payment_terms=None) -> str:
	doc = frappe.get_doc({
		"doctype": "Depot Contract",
		"customer": customer,
		"currency": "IDR",
		"status": "Active",
		"payment_type": payment_type,
		"payment_terms": payment_terms,
		"credit_limit": credit_limit,
		"valid_from": today(),
		"valid_to": add_days(today(), 365),
		"tariff_lines": [{"item": "Lift Off", "rate": 250000}],
	}).insert(ignore_permissions=True)
	return doc.name


class TestTankInFlow(FrappeTestCase):
	"""Tank In / Lift Off: pricing + payment mode come from the customer's contract,
	branch/principal fall back for programmatic callers, the Booking Code's Clean/Dirty
	tag is derived from the line condition, and a booking can't be confirmed without a
	contract."""

	CUSTOMER = "Tank In Flow Co"
	NOCON = "Tank In No-Contract Co"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.customer = ensure_test_customer(cls.CUSTOMER)
		cls.nocon = ensure_test_customer(cls.NOCON)
		_cleanup_customer_world(cls.customer)
		_cleanup_customer_world(cls.nocon)
		cls.contract = _make_active_contract(
			cls.customer, payment_type="Both", credit_limit=1_000_000, payment_terms="NET 30"
		)
		cls.price_list = frappe.db.get_value("Depot Contract", cls.contract, "generated_price_list")

	@classmethod
	def tearDownClass(cls):
		_cleanup_customer_world(cls.customer)
		_cleanup_customer_world(cls.nocon)
		super().tearDownClass()

	def _booking(self, customer, **over):
		doc = {
			"doctype": "Container Booking",
			"customer": customer,
			"do_reference": "DO-TI",
			"items": [{"container_no": "TANK0000050", "condition": "EMPTY CLEAN"}],
		}
		doc.update(over)
		return frappe.get_doc(doc)

	def test_customer_payment_modes_follow_contract(self):
		from container_depot.operations.doctype.container_booking.container_booking import (
			customer_payment_modes,
		)

		self.assertEqual(set(customer_payment_modes(self.customer)), {"Cash", "TOP"})  # Both
		self.assertEqual(customer_payment_modes(self.nocon), [])  # no contract → must create one

	def test_lift_rate_for_reads_active_list(self):
		# Rate + currency come from the customer's active (contract-published) price list —
		# the operator never picks a list, only the lift service.
		from container_depot.operations.doctype.container_booking.container_booking import (
			lift_rate_for,
		)

		hit = lift_rate_for(self.customer, "Lift Off")
		self.assertEqual(hit["rate"], 250000)
		self.assertEqual(hit["currency"], "IDR")  # follows the price-list currency
		self.assertEqual(lift_rate_for(None, "Lift Off")["rate"], 0)

	def test_currency_follows_price_list(self):
		# The actual bug: a USD price list must format Lift Rate in USD, not the system
		# default. No exchange-rate conversion — the price-list currency is used as-is.
		from container_depot.operations.doctype.container_booking.container_booking import (
			lift_rate_for,
		)

		usd_cust = ensure_test_customer("Tank In USD Co")
		_cleanup_customer_world(usd_cust)
		try:
			c = frappe.get_doc({
				"doctype": "Depot Contract", "customer": usd_cust, "currency": "USD",
				"status": "Active", "payment_type": "Cash",
				"valid_from": today(), "valid_to": add_days(today(), 365),
				"tariff_lines": [{"item": "Lift Off", "rate": 36}],
			}).insert(ignore_permissions=True)
			hit = lift_rate_for(usd_cust, "Lift Off")
			self.assertEqual(hit["currency"], "USD")
			self.assertEqual(hit["rate"], 36)
		finally:
			_cleanup_customer_world(usd_cust)

	def test_booking_prices_from_active_list(self):
		b = self._booking(self.customer, lift_item="Lift Off")
		b.insert(ignore_permissions=True)
		self.assertEqual(b.contract, self.contract)      # resolved (hidden) for payment modes
		self.assertEqual(b.price_list, self.price_list)  # auto-resolved from the customer
		self.assertEqual(b.lift_rate, 250000)            # from the active price list
		self.assertEqual(b.currency, "IDR")              # follows the price-list currency
		self.assertTrue(b.branch)                        # branch fell back
		self.assertEqual(b.principal, self.customer)     # principal defaulted to customer

	def test_cash_invoice_follows_price_list_and_branch(self):
		# The auto-created Cash invoice bills off the customer's active price list: its
		# currency, the price list itself, the lift Item, and the booking's branch.
		b = self._booking(self.customer, lift_item="Lift Off")
		b.insert(ignore_permissions=True)
		self.assertTrue(b.sales_invoice, "Cash booking must auto-create a draft invoice")
		si = frappe.get_doc("Sales Invoice", b.sales_invoice)
		self.assertEqual(si.currency, "IDR")                  # from the price list
		self.assertEqual(si.selling_price_list, self.price_list)
		self.assertEqual(si.branch, b.branch)
		self.assertEqual(si.items[0].item_code, "Lift Off")   # lift Item, not generic service

	def test_void_draft_cancels_invoice_and_marks_cancelled(self):
		# Cancel on a draft voids it without deleting: the document reads Cancelled
		# (docstatus 2), payment status flips to Cancelled, and the auto-created invoice
		# is cancelled but KEPT linked & visible on the booking.
		from container_depot.operations.doctype.container_booking.container_booking import void_draft

		b = self._booking(self.customer, lift_item="Lift Off")
		b.insert(ignore_permissions=True)
		si = b.sales_invoice
		self.assertTrue(si and frappe.db.exists("Sales Invoice", si))
		void_draft(b.name)
		b.reload()
		self.assertEqual(b.docstatus, 2, "voided booking reads as Cancelled, not Draft")
		self.assertEqual(b.booking_status, "Cancelled")
		self.assertEqual(b.payment_status, "Cancelled")
		self.assertEqual(b.sales_invoice, si, "cancelled invoice stays linked & visible")
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", si, "docstatus"), 2,
			"the draft invoice is cancelled (kept), not deleted",
		)

	def test_empty_items_rejected_on_draft(self):
		# At least one container row is required even to save a draft.
		b = self._booking(self.customer, lift_item="Lift Off", items=[])
		with self.assertRaises(frappe.exceptions.MandatoryError):
			b.insert(ignore_permissions=True)

	def test_status_tag_derived_from_condition(self):
		# The Clean/Dirty gate tag is derived from a line's condition at booking-code
		# issuance (a pure function); it is no longer stored on the line.
		from container_depot.operations.doctype.container_booking.container_booking import (
			status_tag_for_condition,
		)

		self.assertEqual(status_tag_for_condition("EMPTY CLEAN"), "Clean")
		self.assertEqual(status_tag_for_condition("EMPTY DIRTY"), "Dirty")
		self.assertEqual(status_tag_for_condition("LADEN"), "Dirty")
		self.assertEqual(status_tag_for_condition(None), "Dirty")

	def test_no_contract_blocks_submit(self):
		b = self._booking(self.nocon, items=[{"container_no": "TANK0000053", "condition": "EMPTY CLEAN"}])
		b.insert(ignore_permissions=True)  # draft is allowed while the contract is set up
		with self.assertRaises(frappe.ValidationError):
			b.submit()  # confirmation needs a contract / price list


class TestTopAccrual(FrappeTestCase):
	"""TOP is now postpaid/accrual (B7): bookings submit freely (no credit gate),
	carry NO per-transaction Sales Invoice, and accrue ``payment_status=Unpaid``
	until the depot runs consolidated billing."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.customer = ensure_test_customer(CUSTOMER_TOP)
		_cleanup_customer_world(cls.customer)
		# Tiny credit limit on purpose — TOP no longer gates on it.
		cls.contract = _make_active_contract(
			cls.customer, payment_type="TOP", credit_limit=1, payment_terms="NET 30"
		)

	@classmethod
	def tearDownClass(cls):
		_cleanup_customer_world(cls.customer)
		super().tearDownClass()

	def _booking(self):
		return frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"contract": self.contract,
			"booking_status": "Pending Confirmation",
			"do_reference": "DO-TOP",
			"do_document": "/files/do.pdf",
			"items": [{"container_no": "TANK0000001"}],
		})

	def test_top_submits_freely_and_accrues(self):
		b = self._booking()
		b.insert(ignore_permissions=True)
		b.submit()  # no credit gate, no Blocked
		b.reload()
		self.assertEqual(b.docstatus, 1)
		self.assertFalse(b.sales_invoice, "TOP booking must NOT create a per-transaction invoice")
		self.assertEqual(b.payment_status, "Unpaid")
		self.assertTrue(frappe.db.exists("Booking Code", {"booking": b.name}))


class TestCashPaidInvoice(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.customer = ensure_test_customer(CUSTOMER_CASH)
		_cleanup_customer_world(cls.customer)
		cls.contract = _make_active_contract(cls.customer, payment_type="Cash")

	@classmethod
	def tearDownClass(cls):
		_cleanup_customer_world(cls.customer)
		super().tearDownClass()

	def test_cash_booking_held_pending_payment_without_invoice(self):
		b = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"contract": self.contract,
			"booking_status": "Pending Confirmation",
			"do_reference": "DO-CASH",
			"items": [{"container_no": "TANK0000002"}],
		})
		b.insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			b.submit()
		b.reload()
		# Cash awaiting payment is parked at Pending Payment, not hard-Blocked.
		self.assertEqual(b.booking_status, "Pending Payment")
		self.assertEqual(b.docstatus, 0)

	def test_paid_cash_booking_advances_to_pending_confirmation(self):
		# Cash is pay-first: once the invoice is Paid, the booking advances from Pending
		# Payment to Pending Confirmation (still a draft) so the admin verifies + submits
		# by hand. It is NOT auto-submitted.
		from container_depot.operations.doctype.container_booking.container_booking import (
			sync_bookings_for_invoice,
		)

		b = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"contract": self.contract,
			"do_reference": "DO-CASH-PAID",
			"items": [{"container_no": "CASHPAID001"}],
		}).insert(ignore_permissions=True)
		si = b.sales_invoice
		self.assertTrue(si, "Cash booking must auto-create a draft invoice")
		self.assertEqual(b.booking_status, "Pending Payment")
		# Cashier settles it: invoice submitted + Paid.
		frappe.db.set_value(
			"Sales Invoice", si, {"docstatus": 1, "status": "Paid", "outstanding_amount": 0}
		)
		sync_bookings_for_invoice(si)
		b.reload()
		self.assertEqual(b.docstatus, 0, "booking is NOT auto-submitted")
		self.assertEqual(b.booking_status, "Pending Confirmation")
		self.assertEqual(b.payment_status, "Paid")


class TestWalkInPriceListPricing(FrappeTestCase):
	"""Walk-in (no contract): the booking's default rate is resolved from the
	customer's Price List instead of a contract tariff. The lift service name
	(``Lift Off`` for Tank In) doubles as the catalog Item code."""

	CUSTOMER = "Phase11 WalkIn Customer"
	PRICE_LIST = "ZZ WalkIn PL"
	LIFT_RATE = 175000.0  # IDR, matches the company currency so net_total is clean

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.customer = ensure_test_customer(cls.CUSTOMER)
		# Walk-in has NO contract — _cleanup_customer_world clears any lingering one.
		_cleanup_customer_world(cls.customer)

		# Per-principal selling Price List the walk-in customer defaults to.
		if not frappe.db.exists("Price List", cls.PRICE_LIST):
			frappe.get_doc({
				"doctype": "Price List",
				"price_list_name": cls.PRICE_LIST,
				"currency": "IDR",
				"selling": 1,
				"buying": 0,
				"enabled": 1,
			}).insert(ignore_permissions=True)
		# "Lift Off" is a seeded catalog Item; create a minimal stand-in if the
		# service-item seed has not run in this site.
		if not frappe.db.exists("Item", "Lift Off"):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": "Lift Off",
				"item_name": "Lift Off",
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name")
				or "All Item Groups",
				"stock_uom": "Nos",
				"is_stock_item": 0,
				"is_sales_item": 1,
			}).insert(ignore_permissions=True)
		if not frappe.db.exists("Item Price", {"item_code": "Lift Off", "price_list": cls.PRICE_LIST}):
			frappe.get_doc({
				"doctype": "Item Price",
				"item_code": "Lift Off",
				"price_list": cls.PRICE_LIST,
				"price_list_rate": cls.LIFT_RATE,
				"selling": 1,
			}).insert(ignore_permissions=True)
		frappe.db.set_value("Customer", cls.customer, "default_price_list", cls.PRICE_LIST)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		_cleanup_customer_world(cls.customer)
		frappe.db.set_value("Customer", cls.customer, "default_price_list", None)
		frappe.db.delete("Item Price", {"item_code": "Lift Off", "price_list": cls.PRICE_LIST})
		frappe.db.delete("Price List", {"name": cls.PRICE_LIST})
		frappe.db.commit()
		super().tearDownClass()

	def _walkin_booking(self):
		# No ``contract`` key at all — this is the walk-in path.
		return frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",  # Tank In -> derived lift_type "Lift Off"
			"customer": self.customer,
			"booking_status": "Pending Confirmation",
			"do_reference": "DO-WALKIN",
			"items": [{"container_no": "WALKIN00001"}],
		})

	def test_walkin_rate_resolved_from_price_list(self):
		b = self._walkin_booking()
		b.insert(ignore_permissions=True)
		self.assertFalse(b.contract, "walk-in must carry no contract")
		self.assertEqual(b.payment_type, "Cash", "walk-in defaults to Cash")
		# Resolver picks the customer's Price List rate for the derived service.
		self.assertEqual(b._resolve_service_rate("Lift Off"), self.LIFT_RATE)

	def test_walkin_draft_invoice_priced_from_price_list(self):
		b = self._walkin_booking()
		b.insert(ignore_permissions=True)
		self.assertTrue(b.sales_invoice, "walk-in Cash booking must auto-create a draft invoice")
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", b.sales_invoice, "net_total"),
			self.LIFT_RATE,  # 1 container x Price List Lift Off rate
		)

	def test_walkin_without_price_list_resolves_to_zero(self):
		# Strip the customer's Price List: with no contract, the resolver falls
		# back to the Selling Settings default list (where the lift service has no
		# Item Price) and returns 0 — the Cashier fills the rate in. Graceful,
		# never throws. (We assert the resolver, not the invoice net_total, which
		# is subject to ERPNext's own price-list lookup on the generic line item.)
		frappe.db.set_value("Customer", self.customer, "default_price_list", None)
		try:
			b = self._walkin_booking()
			b.insert(ignore_permissions=True)
			self.assertEqual(b._resolve_service_rate("Lift Off"), 0)
		finally:
			frappe.db.set_value("Customer", self.customer, "default_price_list", self.PRICE_LIST)


class TestBookingCancel(FrappeTestCase):
	"""Cancelling a submitted booking unwinds everything it created: status →
	Cancelled, Active Booking Codes voided, auto-created phantom containers
	deleted, and pre-existing tanks merely flipped to Booked reverted."""

	CUSTOMER = "Phase11 Cancel Customer"
	CONTAINERS = ("CXLPHANT001", "CXLEXIST001", "CXLHELD0001", "CXLNODEL001")

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.customer = ensure_test_customer(cls.CUSTOMER)
		_cleanup_customer_world(cls.customer)
		cls.contract = _make_active_contract(cls.customer, payment_type="Cash")

	@classmethod
	def tearDownClass(cls):
		_cleanup_customer_world(cls.customer)
		for cn in cls.CONTAINERS:
			frappe.db.delete("Container Movement", {"container": cn})
			frappe.db.delete("Container", {"container_no": cn})
		frappe.db.commit()
		super().tearDownClass()

	def _submit_cash_booking(self, container_no):
		b = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"contract": self.contract,
			"booking_status": "Pending Confirmation",
			"do_reference": "DO-CXL",
			"items": [{"container_no": container_no}],
		}).insert(ignore_permissions=True)
		# Cashier "acc": mark the auto-created draft invoice paid so submit passes.
		if b.sales_invoice:
			frappe.db.set_value(
				"Sales Invoice", b.sales_invoice,
				{"docstatus": 1, "status": "Paid", "outstanding_amount": 0},
			)
		b.reload()
		b.submit()
		return b

	def test_cancel_voids_codes_and_sets_status(self):
		b = self._submit_cash_booking("CXLPHANT001")
		self.assertEqual(b.booking_status, "Confirmed")
		self.assertTrue(frappe.db.exists("Booking Code", {"booking": b.name, "state": "Active"}))
		b.cancel()
		b.reload()
		self.assertEqual(b.booking_status, "Cancelled")
		self.assertFalse(
			frappe.db.exists("Booking Code", {"booking": b.name, "state": "Active"}),
			"Active booking codes must be voided on cancel",
		)

	def test_cancel_deletes_phantom_container(self):
		b = self._submit_cash_booking("CXLPHANT001")
		self.assertTrue(frappe.db.exists("Container", "CXLPHANT001"))
		self.assertEqual(
			frappe.db.get_value("Container", "CXLPHANT001", "created_by_booking"), b.name,
			"pre-arrival phantom must be stamped with its booking",
		)
		b.cancel()
		self.assertFalse(
			frappe.db.exists("Container", "CXLPHANT001"),
			"auto-created phantom container must be deleted on cancel",
		)

	def test_cancel_reverts_preexisting_container(self):
		# A tank that already exists (NOT created by the booking).
		if not frappe.db.exists("Container", "CXLEXIST001"):
			frappe.get_doc({
				"doctype": "Container",
				"container_no": "CXLEXIST001",
				"container_type": "ISO Tank",
				"status": "Available",
				"principal": self.customer,
			}).insert(ignore_permissions=True)
		b = self._submit_cash_booking("CXLEXIST001")
		self.assertEqual(frappe.db.get_value("Container", "CXLEXIST001", "status"), "Booked")
		self.assertFalse(frappe.db.get_value("Container", "CXLEXIST001", "created_by_booking"))
		b.cancel()
		self.assertTrue(
			frappe.db.exists("Container", "CXLEXIST001"), "pre-existing tank must not be deleted"
		)
		self.assertEqual(
			frappe.db.get_value("Container", "CXLEXIST001", "status"), "Available",
			"flipped pre-existing tank must revert to Available on cancel",
		)

	def test_cancel_leaves_container_held_by_other_booking(self):
		if not frappe.db.exists("Container", "CXLHELD0001"):
			frappe.get_doc({
				"doctype": "Container",
				"container_no": "CXLHELD0001",
				"container_type": "ISO Tank",
				"status": "Available",
				"principal": self.customer,
			}).insert(ignore_permissions=True)
		a = self._submit_cash_booking("CXLHELD0001")
		b = self._submit_cash_booking("CXLHELD0001")  # second live booking on same tank
		a.cancel()
		self.assertEqual(
			frappe.db.get_value("Container", "CXLHELD0001", "status"), "Booked",
			"a tank still reserved by another live booking must stay Booked",
		)
		self.assertEqual(b.docstatus, 1)

	def test_cancel_keeps_cancelled_invoice_linked(self):
		# Cancelling a confirmed booking cancels its invoice but keeps it linked & visible,
		# and flags payment status Cancelled.
		b = self._submit_cash_booking("CXLPHANT001")
		si = b.sales_invoice
		self.assertTrue(si)
		b.cancel()
		b.reload()
		self.assertEqual(b.sales_invoice, si, "the cancelled invoice stays linked for audit")
		self.assertEqual(b.payment_status, "Cancelled")

	def test_booking_cannot_be_deleted(self):
		# A booking is never permanently deleted — only voided/cancelled.
		b = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"contract": self.contract,
			"do_reference": "DO-CXL-DR",
			"items": [{"container_no": "CXLNODEL001"}],
		}).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Container Booking", b.name, ignore_permissions=True)


class TestTankOutGating(FrappeTestCase):
	"""Direction=Tank Out requires every item Container to be Ready + have a
	valid Cleaning Certificate."""

	CUSTOMER = "Phase3 TankOut Customer"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.customer = ensure_test_customer(cls.CUSTOMER)
		_cleanup_customer_world(cls.customer)
		cls.contract = _make_active_contract(cls.customer, payment_type="Cash")
		# Seed a Container in the ready pool (Available).
		if not frappe.db.exists("Container", CONTAINER_NO):
			frappe.get_doc({
				"doctype": "Container",
				"container_no": CONTAINER_NO,
				"container_type": "ISO Tank",
				"status": "Available",
				"principal": cls.customer,
			}).insert(ignore_permissions=True)
		cls.container = CONTAINER_NO

	@classmethod
	def tearDownClass(cls):
		_cleanup_customer_world(cls.customer)
		# Clean up cleaning certs + container created here.
		frappe.db.delete("Cleaning Certificate", {"container": cls.container})
		frappe.db.delete("Container", {"container_no": cls.container})
		frappe.db.commit()
		super().tearDownClass()

	def _booking(self):
		return frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank Out",
			"customer": self.customer,
			"contract": self.contract,
			"booking_status": "Pending Confirmation",
			"items": [{"container": self.container}],
		})

	def test_tank_out_blocked_without_clean_cert(self):
		frappe.db.delete("Cleaning Certificate", {"container": self.container})
		frappe.db.commit()
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._booking().insert(ignore_permissions=True)
		self.assertIn("Cleaning Certificate", str(ctx.exception))

	def test_tank_out_blocked_with_expired_cert(self):
		frappe.db.delete("Cleaning Certificate", {"container": self.container})
		cert = frappe.get_doc({
			"doctype": "Cleaning Certificate",
			"container": self.container,
			"clean_date": add_days(today(), -90),
			"valid_until": add_days(today(), -1),  # expired yesterday
			"cleaning_method": "Steam Wash",
		})
		cert.insert(ignore_permissions=True)
		cert.submit()
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._booking().insert(ignore_permissions=True)
		self.assertIn("expired", str(ctx.exception).lower())

	def test_tank_out_passes_with_valid_cert(self):
		frappe.db.delete("Cleaning Certificate", {"container": self.container})
		cert = frappe.get_doc({
			"doctype": "Cleaning Certificate",
			"container": self.container,
			"clean_date": now_datetime(),
			"cleaning_method": "Hot Water",
		})
		cert.insert(ignore_permissions=True)
		cert.submit()  # default valid_until = today + 30
		b = self._booking()
		b.insert(ignore_permissions=True)  # should NOT raise
		self.assertEqual(b.direction, "Tank Out")

	def test_tank_out_blocked_when_container_not_ready(self):
		frappe.db.set_value("Container", self.container, "status", "Repair_In_Progress")
		try:
			frappe.db.delete("Cleaning Certificate", {"container": self.container})
			cert = frappe.get_doc({
				"doctype": "Cleaning Certificate",
				"container": self.container,
				"clean_date": now_datetime(),
				"cleaning_method": "Hot Water",
			})
			cert.insert(ignore_permissions=True)
			cert.submit()
			with self.assertRaises(frappe.ValidationError) as ctx:
				self._booking().insert(ignore_permissions=True)
			self.assertIn("Ready", str(ctx.exception))
		finally:
			frappe.db.set_value("Container", self.container, "status", "Available")


class TestBookingCodeExpiry(FrappeTestCase):
	"""Scheduler-style expiry: Active codes whose expires_at < now → Expired."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.customer = ensure_test_customer("Phase3 Expiry Customer")
		_cleanup_customer_world(cls.customer)
		cls.contract = _make_active_contract(cls.customer, payment_type="Cash")

	@classmethod
	def tearDownClass(cls):
		_cleanup_customer_world(cls.customer)
		super().tearDownClass()

	def test_expire_booking_codes_flips_stale(self):
		# Create a booking + code with expires_at in the past.
		from container_depot.operations.doctype.booking_code.booking_code import (
			CODE_TTL_HOURS,
			generate_code,
		)
		b = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"contract": self.contract,
			"booking_status": "Pending Confirmation",
			"items": [{"container_no": "TANK0000099"}],
		}).insert(ignore_permissions=True)
		code = frappe.get_doc({
			"doctype": "Booking Code",
			"code": generate_code(),
			"booking": b.name,
			"direction": "Tank In",
			"container_no": "TANK0000099",
			"state": "Active",
			"issued_at": add_to_date(now_datetime(), hours=-(CODE_TTL_HOURS + 1)),
			"expires_at": add_to_date(now_datetime(), hours=-1),
		}).insert(ignore_permissions=True)

		expired = expire_booking_codes()
		self.assertGreaterEqual(expired, 1)
		code.reload()
		self.assertEqual(code.state, "Expired")

	def test_expire_booking_codes_leaves_active_alone(self):
		from container_depot.operations.doctype.booking_code.booking_code import (
			generate_code,
		)
		b = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"contract": self.contract,
			"booking_status": "Pending Confirmation",
			"items": [{"container_no": "TANK0000098"}],
		}).insert(ignore_permissions=True)
		code = frappe.get_doc({
			"doctype": "Booking Code",
			"code": generate_code(),
			"booking": b.name,
			"direction": "Tank In",
			"container_no": "TANK0000098",
			"state": "Active",
			"issued_at": now_datetime(),
			"expires_at": add_to_date(now_datetime(), hours=+5),
		}).insert(ignore_permissions=True)
		expire_booking_codes()
		code.reload()
		self.assertEqual(code.state, "Active")
