"""Tests for the Phase-3 critical controllers:

1. TOP credit-block (Container Booking.before_submit).
2. TANK OUT gating (Container Booking.validate when direction == 'Tank Out').
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime, today

from container_depot.container_depot.container_status import GATE_OUT
from container_depot.tests._booking_helpers import cancel_submitted_booking
from container_depot.tests.finance_fixture import require_finance
from container_depot.tests.test_api import ensure_test_customer


CUSTOMER_CASH = "Phase3 Cash Customer"
CUSTOMER_TOP = "Phase3 TOP Customer"
CONTAINER_NO = "TSTU3334440"


def _release_lift_on(bookings):
	"""Drop the lift-on stamp an outbound booking left on its tanks, before the booking row
	itself is deleted.

	These purges are raw ``db.delete`` (a Container Booking refuses ordinary deletion), so
	nothing unwinds the ``Container.lift_on_booking`` back-link the way cancelling would.
	Left behind, it is a Link pointing at a row that no longer exists — and the NEXT save of
	that container, or of anything that saves it, dies on link validation somewhere entirely
	unrelated to the test that caused it.
	"""
	frappe.db.sql(
		"""
		UPDATE `tabContainer` SET lift_on_booking = NULL, target_lift_on = NULL
		WHERE lift_on_booking IN %(bookings)s
		""",
		{"bookings": tuple(bookings)},
	)


def _cleanup_customer_world(customer: str):
	bookings = frappe.get_all("Container Booking", filters={"customer": customer}, pluck="name")
	if bookings:
		frappe.db.delete("Booking Code", {"booking": ("in", bookings)})
		frappe.db.delete("Container Booking Item", {"parent": ("in", bookings)})
		_release_lift_on(bookings)
		# An outbound booking opens a Container Position Survey per tank the moment it is
		# SAVED (provisioning moved to the draft), so a purge that only drops bookings now
		# leaves a survey behind pointing at a container that is about to go too.
		frappe.db.delete("Container Position Survey", {"booking": ("in", bookings)})
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


def _purge_bookings(customer: str):
	"""Drop this customer's bookings between tests.

	A live (non-cancelled) booking now RESERVES its containers — a second booking naming
	the same tank is refused on save (``_validate_no_open_booking``). These classes reuse
	one container number across every test, so each test has to start from a clean sheet
	or it collides with the booking the previous one left behind. Deliberately narrower
	than ``_cleanup_customer_world``: the contract and price list built in setUpClass stay.
	"""
	bookings = frappe.get_all("Container Booking", filters={"customer": customer}, pluck="name")
	if bookings:
		frappe.db.delete("Booking Code", {"booking": ("in", bookings)})
		frappe.db.delete("Container Booking Item", {"parent": ("in", bookings)})
		_release_lift_on(bookings)
		# An outbound booking opens a Container Position Survey per tank the moment it is
		# SAVED (provisioning moved to the draft), so a purge that only drops bookings now
		# leaves a survey behind pointing at a container that is about to go too.
		frappe.db.delete("Container Position Survey", {"booking": ("in", bookings)})
		frappe.db.delete("Container Booking", {"name": ("in", bookings)})
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


def _bill(booking):
	"""Draft -> Pending Payment via the explicit Generate Invoice action, then reload.

	An invoice is no longer born on save, so every test that needs one goes through the
	same door the operator does."""
	from container_depot.container_depot.doctype.container_booking.container_booking import (
		generate_invoice,
	)

	generate_invoice(booking.name)
	booking.reload()
	return booking.sales_invoice


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
		require_finance(cls)
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

	def setUp(self):
		super().setUp()
		_purge_bookings(self.customer)
		_purge_bookings(self.nocon)

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
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			customer_payment_modes,
		)

		self.assertEqual(set(customer_payment_modes(self.customer)), {"Cash", "TOP"})  # Both
		self.assertEqual(customer_payment_modes(self.nocon), [])  # no contract → must create one

	def test_charge_pricing_reads_active_list(self):
		# Rate + currency come from the customer's active (contract-published) price list —
		# the operator never picks a list, only the service on each charge line.
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			charge_pricing,
		)

		hit = charge_pricing(self.customer, "Lift Off")
		self.assertEqual(hit["rate"], 250000)
		self.assertEqual(hit["currency"], "IDR")  # follows the price-list currency
		self.assertEqual(charge_pricing(None, "Lift Off")["rate"], 0)

	def test_currency_follows_price_list(self):
		# The actual bug: a USD price list must format charge rates in USD, not the system
		# default. No exchange-rate conversion — the price-list currency is used as-is.
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			charge_pricing,
		)

		usd_cust = ensure_test_customer("Tank In USD Co")
		_cleanup_customer_world(usd_cust)
		try:
			frappe.get_doc({
				"doctype": "Depot Contract", "customer": usd_cust, "currency": "USD",
				"status": "Active", "payment_type": "Cash",
				"valid_from": today(), "valid_to": add_days(today(), 365),
				"tariff_lines": [{"item": "Lift Off", "rate": 36}],
			}).insert(ignore_permissions=True)
			hit = charge_pricing(usd_cust, "Lift Off")
			self.assertEqual(hit["currency"], "USD")
			self.assertEqual(hit["rate"], 36)
		finally:
			_cleanup_customer_world(usd_cust)

	def test_booking_prices_from_active_list(self):
		b = self._booking(self.customer, charges=[{"item": "Lift Off"}])
		b.insert(ignore_permissions=True)
		self.assertEqual(b.contract, self.contract)      # resolved (hidden) for payment modes
		self.assertEqual(b.price_list, self.price_list)  # auto-resolved from the customer
		self.assertEqual(b.currency, "IDR")              # follows the price-list currency
		self.assertEqual(b.charges[0].rate, 250000)      # seeded from the active price list
		self.assertEqual(b.charges[0].qty, 1)            # = container count
		self.assertEqual(b.charges_total, 250000)
		self.assertTrue(b.branch)                        # branch fell back
		self.assertEqual(b.principal, self.customer)     # principal defaulted to customer

	def test_multiple_charges_total(self):
		# Pricing is a free table now: several services on one booking, each with its own
		# qty and rate, summed into charges_total and billed as separate invoice lines.
		b = self._booking(
			self.customer,
			charges=[{"item": "Lift Off"}, {"item": "Lift Off", "qty": 2, "rate": 1000}],
		)
		b.insert(ignore_permissions=True)
		self.assertEqual(b.charges_total, 250000 + 2000)
		si = frappe.get_doc("Sales Invoice", _bill(b))
		self.assertEqual(len(si.items), 2)

	def test_billing_report_reads_the_booking_amount(self):
		"""Order Billing Status must show a submitted booking at its ``charges_total``.

		Run UNFILTERED on purpose. The report unions five doctypes and each builder names
		its own column list, so a filtered run only proves the one branch it selects — which
		is how the report kept asking for ``lift_amount`` for a whole release after patch
		v0_49 dropped that column, failing with a bare OperationalError for every user.
		Executing with no ``order_type`` is the cheap guard that touches all five.
		"""
		from container_depot.container_depot.report.order_billing_status.order_billing_status import (
			execute,
		)

		# The report only reads submitted bookings, and a submitted Tank In holds its
		# container until a bon is issued — so this one gets a container of its own rather
		# than blocking the shared TANK0000050 for the rest of the class. TOP, because a
		# Cash booking cannot be submitted until its invoice is paid.
		b = self._booking(
			self.customer,
			items=[{"container_no": "TANK0000054", "condition": "EMPTY CLEAN"}],
			charges=[{"item": "Lift Off"}],
			payment_type="TOP",
		)
		b.insert(ignore_permissions=True)
		b.submit()

		_, rows = execute({})
		mine = [r for r in rows if r["order"] == b.name]
		self.assertEqual(len(mine), 1)
		self.assertEqual(mine[0]["order_type"], "Container Booking")
		self.assertEqual(mine[0]["amount"], 250000)
		self.assertEqual(mine[0]["currency"], "IDR")

	def test_hand_set_rate_is_never_reseeded(self):
		# A negotiated one-off price must survive every re-save — the price list only ever
		# seeds an empty rate.
		b = self._booking(self.customer, charges=[{"item": "Lift Off", "rate": 99}])
		b.insert(ignore_permissions=True)
		b.save(ignore_permissions=True)
		b.reload()
		self.assertEqual(b.charges[0].rate, 99)

	def test_changing_customer_clears_charges(self):
		# Each customer has their own rate card and the rate is stored on the line, so the
		# old lines must go rather than bill the previous customer's prices under a new
		# name. The Desk form clears them client-side; this is the server-side backstop.
		b = self._booking(self.customer, charges=[{"item": "Lift Off"}])
		b.insert(ignore_permissions=True)
		self.assertEqual(len(b.charges), 1)
		b.customer = self.nocon
		b.save(ignore_permissions=True)
		self.assertEqual(b.charges, [])
		self.assertEqual(b.charges_total, 0)

	def test_booking_without_charges_bills_nothing(self):
		# "Tanpa price juga bisa": no charge lines -> no invoice, and the Cash payment gate
		# has nothing to hold the submit on.
		b = self._booking(self.customer, charges=[])
		b.insert(ignore_permissions=True)
		self.assertFalse(b.sales_invoice, "a booking with no charges must not raise an invoice")
		self.assertEqual(b.charges_total, 0)
		b.submit()
		self.assertEqual(b.docstatus, 1)

	def test_booking_confirms_without_a_delivery_order(self):
		"""The DO reference is paperwork, not a precondition: a booking may be confirmed
		before it exists (or when the customer never issues one)."""
		b = self._booking(
			self.customer,
			do_reference=None,
			charges=[],
			# Its own tank — a submitted booking holds the container against every other.
			items=[{"container_no": "TANK0000052", "condition": "EMPTY CLEAN"}],
		)
		b.insert(ignore_permissions=True)
		b.submit()
		self.assertEqual(b.docstatus, 1)
		self.assertIsNone(b.do_reference)

	def test_zero_total_charges_raise_no_invoice(self):
		# A line priced at 0 is worth nothing, which is the same as no charge at all: a
		# zero-value invoice would just hand the Cashier something to collect that nobody owes.
		b = self._booking(
			self.customer,
			charges=[{"item": "Lift Off", "rate": 0, "qty": 1}],
			# Its own tank: this test submits, and a submitted booking holds the container
			# against every other booking until a bon is issued.
			items=[{"container_no": "TANK0000051", "condition": "EMPTY CLEAN"}],
		)
		b.insert(ignore_permissions=True)
		self.assertEqual(b.charges_total, 0)
		self.assertFalse(b.sales_invoice, "a zero-total booking must not raise an invoice")
		b.submit()
		self.assertEqual(b.docstatus, 1)

	def test_generate_invoice_moves_to_pending_payment_and_locks(self):
		# The deliberate step: Draft carries nothing, Generate Invoice raises the invoice
		# and freezes the billing facts so the Cashier's amount cannot move under them.
		b = self._booking(self.customer, charges=[{"item": "Lift Off"}])
		b.insert(ignore_permissions=True)
		self.assertEqual(b.booking_status, "Draft")
		self.assertFalse(b.sales_invoice, "a Draft booking generates nothing")

		si = _bill(b)
		self.assertTrue(si)
		self.assertEqual(b.booking_status, "Pending Payment")
		self.assertEqual(frappe.db.get_value("Sales Invoice", si, "net_total"), 250000)

		b.charges[0].rate = 100000
		with self.assertRaises(frappe.ValidationError):
			b.save(ignore_permissions=True)

	def test_rollback_voids_the_invoice_and_reopens_the_booking(self):
		# The way back while nothing has settled: the draft invoice is cancelled, unlinked,
		# and the charges are editable again.
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			rollback_to_draft,
		)

		b = self._booking(self.customer, charges=[{"item": "Lift Off"}])
		b.insert(ignore_permissions=True)
		si = _bill(b)

		rollback_to_draft(b.name)
		b.reload()
		self.assertEqual(b.booking_status, "Draft")
		self.assertFalse(b.sales_invoice, "the voided invoice is unlinked")
		self.assertEqual(frappe.db.get_value("Sales Invoice", si, "docstatus"), 2)

		b.charges[0].rate = 100000
		b.save(ignore_permissions=True)
		self.assertEqual(b.charges_total, 100000)
		# ...and it can be billed again, as a fresh invoice.
		si2 = _bill(b)
		self.assertNotEqual(si2, si)
		self.assertEqual(frappe.db.get_value("Sales Invoice", si2, "net_total"), 100000)

	def test_rollback_refused_once_invoice_submitted(self):
		# A submitted invoice is in the ledger — it must be cancelled through accounting
		# (which reverses its payments) before the booking can move.
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			rollback_to_draft,
		)

		b = self._booking(self.customer, charges=[{"item": "Lift Off"}])
		b.insert(ignore_permissions=True)
		si = _bill(b)
		frappe.db.set_value(
			"Sales Invoice", si, {"docstatus": 1, "status": "Paid", "outstanding_amount": 0}
		)
		with self.assertRaises(frappe.ValidationError):
			rollback_to_draft(b.name)
		b.reload()
		self.assertEqual(b.booking_status, "Pending Payment")
		self.assertEqual(b.sales_invoice, si)

	def test_generate_invoice_refused_for_top_and_for_zero_total(self):
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			generate_invoice,
		)

		zero = self._booking(self.customer, charges=[{"item": "Lift Off", "rate": 0, "qty": 1}])
		zero.insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			generate_invoice(zero.name)

		top = self._booking(
			self.customer,
			charges=[{"item": "Lift Off"}],
			payment_type="TOP",
			# A different tank: the zero-total booking above still holds TANK0000050.
			items=[{"container_no": "TANK0000051", "condition": "EMPTY CLEAN"}],
		)
		top.insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			generate_invoice(top.name)  # TOP is swept by consolidated billing, never here

	def test_zeroing_blocked_when_invoice_submitted_unpaid(self):
		# Submitted-but-unpaid is still submitted: the invoice has hit the ledger and the
		# customer has been billed, so the booking may not quietly drop to zero behind it.
		b = self._booking(self.customer, charges=[{"item": "Lift Off"}])
		b.insert(ignore_permissions=True)
		si = _bill(b)
		frappe.db.set_value("Sales Invoice", si, {"docstatus": 1, "status": "Unpaid"})
		b.reload()
		b.charges[0].rate = 0
		with self.assertRaises(frappe.ValidationError):
			b.save(ignore_permissions=True)
		b.reload()
		self.assertEqual(b.charges_total, 250000, "the booking is left exactly as invoiced")
		self.assertEqual(b.sales_invoice, si)

	def test_clearing_charges_blocked_when_invoice_paid(self):
		# Deleting the rows is the same edit as zeroing them — both must be refused while
		# the invoice is live, or the paid invoice would be orphaned.
		b = self._booking(self.customer, charges=[{"item": "Lift Off"}])
		b.insert(ignore_permissions=True)
		si = _bill(b)
		frappe.db.set_value(
			"Sales Invoice", si, {"docstatus": 1, "status": "Paid", "outstanding_amount": 0}
		)
		b.reload()
		b.charges = []
		with self.assertRaises(frappe.ValidationError):
			b.save(ignore_permissions=True)

	def test_cancelling_the_invoice_unlinks_it_and_frees_the_charges(self):
		# Cancelling the invoice is the other door out of the freeze. The dead link must be
		# DROPPED, not kept: Frappe validates links before validate() and refuses to save
		# any document pointing at a cancelled one, so a kept link would leave the booking
		# permanently unsaveable (CancelledLinkError).
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			resync_booking_on_invoice_cancel,
		)

		b = self._booking(self.customer, charges=[{"item": "Lift Off"}])
		b.insert(ignore_permissions=True)
		si = _bill(b)
		frappe.db.set_value("Sales Invoice", si, {"docstatus": 2, "status": "Cancelled"})
		resync_booking_on_invoice_cancel(frappe.get_doc("Sales Invoice", si))
		b.reload()
		self.assertFalse(b.sales_invoice, "the cancelled invoice is unlinked")
		self.assertEqual(b.payment_status, "Unpaid")

	def test_free_line_kept_next_to_a_paid_one(self):
		# Only a booking whose WHOLE total is zero is unbilled. A free line inside a paid
		# booking still belongs on the invoice.
		b = self._booking(
			self.customer,
			charges=[{"item": "Lift Off"}, {"item": "Lift On", "rate": 0, "qty": 1}],
		)
		b.insert(ignore_permissions=True)
		si = frappe.get_doc("Sales Invoice", _bill(b))
		self.assertEqual(len(si.items), 2)

	def test_charge_edit_blocked_once_invoice_submitted(self):
		# A submitted invoice has hit the ledger: its numbers are frozen and the booking
		# may no longer drift away from them.
		b = self._booking(self.customer, charges=[{"item": "Lift Off"}])
		b.insert(ignore_permissions=True)
		_bill(b)
		frappe.db.set_value(
			"Sales Invoice", b.sales_invoice,
			{"docstatus": 1, "status": "Paid", "outstanding_amount": 0},
		)
		b.reload()
		b.charges[0].rate = 1
		with self.assertRaises(frappe.ValidationError):
			b.save(ignore_permissions=True)

	def test_non_billing_edit_allowed_with_submitted_invoice(self):
		# Only the billing facts are frozen — the paperwork around them stays editable.
		b = self._booking(self.customer, charges=[{"item": "Lift Off"}])
		b.insert(ignore_permissions=True)
		_bill(b)
		frappe.db.set_value(
			"Sales Invoice", b.sales_invoice,
			{"docstatus": 1, "status": "Paid", "outstanding_amount": 0},
		)
		b.reload()
		b.remarks = "gate note"
		b.save(ignore_permissions=True)
		self.assertEqual(b.remarks, "gate note")

	def test_cash_invoice_follows_price_list_and_branch(self):
		# The auto-created Cash invoice bills off the customer's active price list: its
		# currency, the price list itself, the charged Item, and the booking's branch.
		b = self._booking(self.customer, charges=[{"item": "Lift Off"}])
		b.insert(ignore_permissions=True)
		si = frappe.get_doc("Sales Invoice", _bill(b))
		self.assertEqual(si.currency, "IDR")                  # from the price list
		self.assertEqual(si.selling_price_list, self.price_list)
		self.assertEqual(si.branch, b.branch)
		self.assertEqual(si.items[0].item_code, "Lift Off")   # charged Item, not generic service

	def test_void_draft_cancels_invoice_and_marks_cancelled(self):
		# Cancel on a draft voids it without deleting: the document reads Cancelled
		# (docstatus 2), payment status flips to Cancelled, and the auto-created invoice
		# is cancelled but KEPT linked & visible on the booking.
		from container_depot.container_depot.doctype.container_booking.container_booking import void_draft

		b = self._booking(self.customer, charges=[{"item": "Lift Off"}])
		b.insert(ignore_permissions=True)
		si = _bill(b)
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

	def test_void_draft_requires_the_cancel_permission(self):
		"""A read-only account must not be able to void a booking.

		``void_draft`` exists only because a DRAFT cannot go through submit→cancel — not
		because the permission stops applying. It used to check nothing at all: `get_doc`
		does not, and the writes go out through `db_set`/`db.sql`, so a Finance user (read
		on Container Booking, no cancel) could void a booking, cancel its Sales Invoice and
		release its pre-arrival reservations over the API.
		"""
		from container_depot.container_depot.doctype.container_booking.container_booking import void_draft

		b = self._booking(self.customer, charges=[{"item": "Lift Off"}])
		b.insert(ignore_permissions=True)

		email = "cb-readonly@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, ignore_permissions=True, force=True)
		user = frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": "CB ReadOnly",
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
			self.assertTrue(frappe.has_permission("Container Booking", "read"))
			self.assertFalse(frappe.has_permission("Container Booking", "cancel"))
			with self.assertRaises(frappe.PermissionError):
				void_draft(b.name)
		finally:
			frappe.set_user("Administrator")
			frappe.delete_doc("User", email, ignore_permissions=True, force=True)

		b.reload()
		self.assertEqual(b.docstatus, 0, "the refused call must leave the draft alone")
		self.assertNotEqual(b.booking_status, "Cancelled")

	def test_empty_items_rejected_on_draft(self):
		# At least one container row is required even to save a draft. Checked by the
		# controller rather than by a `reqd` field: Frappe pre-fills a blank row in every
		# mandatory table, and the Containers grid is meant to start empty like Charges.
		b = self._booking(self.customer, charges=[{"item": "Lift Off"}], items=[])
		with self.assertRaises(frappe.ValidationError) as ctx:
			b.insert(ignore_permissions=True)
		self.assertIn("minimal satu container", str(ctx.exception).lower())

	def test_status_tag_derived_from_condition(self):
		# The Clean/Dirty gate tag is derived from a line's condition at booking-code
		# issuance (a pure function); it is no longer stored on the line.
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			status_tag_for_condition,
		)

		self.assertEqual(status_tag_for_condition("EMPTY CLEAN"), "Clean")
		self.assertEqual(status_tag_for_condition("EMPTY DIRTY"), "Dirty")
		self.assertEqual(status_tag_for_condition("LADEN"), "Dirty")
		self.assertEqual(status_tag_for_condition(None), "Dirty")

	def test_no_contract_no_charges_submits_free(self):
		# A contract is no longer a hard gate: it only supplies the rate card and the
		# allowed payment modes. A walk-in booking that bills nothing is a legitimate
		# booking, not something to block at submit.
		b = self._booking(self.nocon, items=[{"container_no": "TANK0000053", "condition": "EMPTY CLEAN"}])
		b.insert(ignore_permissions=True)
		self.assertFalse(b.contract)
		self.assertFalse(b.sales_invoice)
		b.submit()
		self.assertEqual(b.docstatus, 1)


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
		require_finance(cls)
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
			"do_reference": "DO-CASH",
			"charges": [{"item": "Lift Off"}],
			"items": [{"container_no": "TANK0000002"}],
		})
		b.insert(ignore_permissions=True)
		# Never billed: submit points at the missing step rather than parking the booking.
		with self.assertRaises(frappe.ValidationError):
			b.submit()
		b.reload()
		self.assertEqual(b.booking_status, "Draft")
		self.assertEqual(b.docstatus, 0)

		# Billed but not yet paid: now it really is awaiting the Cashier, and stays parked
		# at Pending Payment rather than being hard-Blocked.
		_bill(b)
		with self.assertRaises(frappe.ValidationError):
			b.submit()
		b.reload()
		self.assertEqual(b.booking_status, "Pending Payment")
		self.assertEqual(b.docstatus, 0)

	def test_paid_cash_booking_auto_submits(self):
		# Cash is pay-first: once the invoice is Paid, the booking is auto-submitted
		# (confirmed) on the Cashier's behalf — no manual confirmation step.
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			sync_bookings_for_invoice,
		)

		b = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"contract": self.contract,
			"do_reference": "DO-CASH-PAID",
			"charges": [{"item": "Lift Off"}],
			"items": [{"container_no": "CASHPAID001"}],
		}).insert(ignore_permissions=True)
		self.assertEqual(b.booking_status, "Draft", "a fresh booking generates nothing")
		si = _bill(b)
		self.assertTrue(si)
		self.assertEqual(b.booking_status, "Pending Payment")
		# Cashier settles it: invoice submitted + Paid.
		frappe.db.set_value(
			"Sales Invoice", si, {"docstatus": 1, "status": "Paid", "outstanding_amount": 0}
		)
		sync_bookings_for_invoice(si)
		b.reload()
		self.assertEqual(b.docstatus, 1, "paid cash booking is auto-submitted")
		self.assertEqual(b.booking_status, "Confirmed")
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
		require_finance(cls)
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

	def setUp(self):
		super().setUp()
		_purge_bookings(self.customer)

	def _walkin_booking(self):
		# No ``contract`` key at all — this is the walk-in path.
		return frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",  # Tank In = Lift Off
			"customer": self.customer,
			"do_reference": "DO-WALKIN",
			"charges": [{"item": "Lift Off"}],
			"items": [{"container_no": "WALKIN00001"}],
		})

	def test_walkin_rate_resolved_from_price_list(self):
		b = self._walkin_booking()
		b.insert(ignore_permissions=True)
		self.assertFalse(b.contract, "walk-in must carry no contract")
		self.assertEqual(b.payment_type, "Cash", "walk-in defaults to Cash")
		# The charge line seeds from the customer's own Price List, no contract involved.
		self.assertEqual(b.charges[0].rate, self.LIFT_RATE)

	def test_walkin_draft_invoice_priced_from_price_list(self):
		b = self._walkin_booking()
		b.insert(ignore_permissions=True)
		self.assertTrue(_bill(b), "a walk-in Cash booking can be billed too")
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", b.sales_invoice, "net_total"),
			self.LIFT_RATE,  # 1 container x Price List Lift Off rate
		)

	def test_walkin_without_price_list_resolves_to_zero(self):
		# Strip the customer's Price List: with no contract there is no rate card left, so
		# the charge line stays at 0 — the Cashier fills it in on the draft invoice.
		# Graceful, never throws.
		frappe.db.set_value("Customer", self.customer, "default_price_list", None)
		try:
			b = self._walkin_booking()
			b.insert(ignore_permissions=True)
			self.assertEqual(b.charges[0].rate, 0)
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
		require_finance(cls)
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

	def setUp(self):
		super().setUp()
		_purge_bookings(self.customer)

	def _submit_cash_booking(self, container_no, *, bypass_open_booking_guard=False):
		b = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"contract": self.contract,
			"do_reference": "DO-CXL",
			"charges": [{"item": "Lift Off"}],
			"items": [{"container_no": container_no}],
		}).insert(ignore_permissions=True)
		_bill(b)
		# Cashier "acc": mark the draft invoice paid so submit passes.
		if b.sales_invoice:
			frappe.db.set_value(
				"Sales Invoice", b.sales_invoice,
				{"docstatus": 1, "status": "Paid", "outstanding_amount": 0},
			)
		b.reload()
		if bypass_open_booking_guard:
			# ignore_validate skips before_submit (where the guard lives) but still runs
			# on_submit, so Booking Codes are issued exactly as they were historically.
			b.flags.ignore_validate = True
		b.submit()
		return b

	def test_cancel_voids_codes_and_sets_status(self):
		b = self._submit_cash_booking("CXLPHANT001")
		self.assertEqual(b.booking_status, "Confirmed")
		self.assertTrue(frappe.db.exists("Booking Code", {"booking": b.name, "state": "Active"}))
		cancel_submitted_booking(b.name)
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
		cancel_submitted_booking(b.name)
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
		cancel_submitted_booking(b.name)
		self.assertTrue(
			frappe.db.exists("Container", "CXLEXIST001"), "pre-existing tank must not be deleted"
		)
		self.assertEqual(
			frappe.db.get_value("Container", "CXLEXIST001", "status"), GATE_OUT,
			"a tank that never arrived goes back outside the depot, not into the yard",
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
		# Two live bookings can no longer BOTH claim one tank — the second is refused on
		# save (_validate_no_open_booking). The branch under test still has to hold for
		# rows that predate that guard, so the double hold is written straight to the DB
		# instead of through the form.
		b = self._submit_cash_booking("CXLNODEL001")
		frappe.db.set_value(
			"Container Booking Item",
			b.items[0].name,
			{"container": "CXLHELD0001", "container_no": "CXLHELD0001"},
			update_modified=False,
		)
		a.reload()
		cancel_submitted_booking(a.name)
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
		cancel_submitted_booking(b.name)
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
	"""Direction=Tank Out requires every item Container to be Ready."""

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
		frappe.db.delete("Cleaning Order", {"container": cls.container})
		frappe.db.delete("Container", {"container_no": cls.container})
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		super().setUp()
		_purge_bookings(self.customer)

	def _booking(self):
		return frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank Out",
			"customer": self.customer,
			"contract": self.contract,
			"items": [{"container": self.container}],
		})

	def _open_cleaning(self):
		"""An unfinished cleaning on the test container, dropped again by the caller."""
		return frappe.get_doc({
			"doctype": "Cleaning Order",
			"container": self.container,
			"status": "Service Setup",
		}).insert(ignore_permissions=True)

	def test_tank_out_draft_allowed_while_work_is_open(self):
		# A draft outbound booking may always be saved — the yard can prepare the paperwork
		# while cleaning finishes. Only the SUBMIT is gated.
		co = self._open_cleaning()
		try:
			b = self._booking()
			b.insert(ignore_permissions=True)  # must NOT raise
			self.assertEqual(b.direction, "Tank Out")
		finally:
			frappe.delete_doc("Cleaning Order", co.name, force=True, ignore_permissions=True)

	def test_tank_out_submit_is_allowed_while_work_is_open(self):
		"""Unfinished work does NOT hold an outbound booking back any more.

		The booking is how the depot learns a pickup is coming; refusing it until the yard
		had finished meant the cleaning queue heard about the deadline only after it had
		passed. The work is prioritised instead (the tank's target lift-on floats it up every
		worklist) and is still refused where the tank actually moves — the bon and the gate.
		"""
		co = self._open_cleaning()
		try:
			self._booking()._validate_out_ready()  # must NOT raise
		finally:
			frappe.delete_doc("Cleaning Order", co.name, force=True, ignore_permissions=True)

	def test_tank_out_submit_passes_when_no_order_was_ever_raised(self):
		"""The rule is the ABSENCE of open work, not the presence of a finished cleaning.

		A tank that arrived clean and needed nothing done has no order to complete; demanding
		one stranded it in the depot permanently, because there was nothing that could ever
		satisfy the check.
		"""
		self.assertEqual(
			frappe.get_all("Cleaning Order", filters={"container": self.container}), [],
			"this test only means anything with no cleaning on record",
		)
		for status in ("Available", "In_Depot"):
			frappe.db.set_value("Container", self.container, "status", status)
			self._booking()._validate_out_ready()  # must NOT raise
		frappe.db.set_value("Container", self.container, "status", "Available")

	def test_tank_out_submit_blocked_when_tank_is_not_in_the_depot(self):
		"""A different refusal with a different fix: nothing to finish — it is not here."""
		frappe.db.set_value("Container", self.container, "status", "Gate_Out")
		try:
			with self.assertRaises(frappe.ValidationError) as ctx:
				self._booking()._validate_out_ready()
			self.assertIn("tidak ada di depo", str(ctx.exception))
		finally:
			frappe.db.set_value("Container", self.container, "status", "Available")

	def test_open_work_is_reported_as_priority_not_as_a_refusal(self):
		"""Two questions, two helpers, and the split is the point.

		``status_direction_warnings`` answers "what will Submit refuse" and no longer counts
		unfinished work; ``out_work_warnings`` answers "what does the yard still owe on these
		tanks", which is what the booking's lift-on date is about to prioritise. The form
		shows them as two banners because they are opposite messages.
		"""
		co = self._open_cleaning()
		try:
			from container_depot.container_depot.doctype.container_booking.container_booking import (
				out_work_warnings,
				status_direction_warnings,
			)

			rows = [{"container": self.container, "container_no": self.container}]
			self.assertEqual(status_direction_warnings("Tank Out", rows), [])

			pending = out_work_warnings(rows)
			self.assertEqual(len(pending), 1)
			self.assertEqual([o["name"] for o in pending[0]["open_orders"]], [co.name])
			self.assertEqual(pending[0]["open_orders"][0]["label"], "Cleaning")
		finally:
			frappe.delete_doc("Cleaning Order", co.name, force=True, ignore_permissions=True)


class TestTankOutDepotDerivation(FrappeTestCase):
	"""Tank Out never asks for a Depot — the tank is already somewhere and its master says
	where, per row. The header keeps a depot only when every tank agrees; two depots of ONE
	branch ride on one booking, and a tank standing in another Branch is refused."""

	CUSTOMER = "Phase3 TankOutDepot Customer"
	IN_BRANCH = "TankOut Branch A"
	OUT_BRANCH = "TankOut Branch B"
	HERE = "TSTU7000001"  # Available, depot in IN_BRANCH
	ELSEWHERE = "TSTU7000002"  # Available, depot in OUT_BRANCH
	GONE = "TSTU7000003"  # already left, depot in IN_BRANCH
	UNSTAMPED = "TSTU7000004"  # present, but the master never got a depot (legacy data)
	SIBLING = "TSTU7000005"  # Available, in the OTHER depot of the SAME branch

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.customer = ensure_test_customer(cls.CUSTOMER)
		_cleanup_customer_world(cls.customer)
		cls.contract = _make_active_contract(cls.customer, payment_type="Cash")
		cls.depot_here = cls._depot("TOA", cls.IN_BRANCH)
		cls.depot_there = cls._depot("TOB", cls.OUT_BRANCH)
		# A second yard in the SAME branch — the case a single-depot booking used to refuse.
		cls.depot_sibling = cls._depot("TOC", cls.IN_BRANCH)
		cls._container(cls.SIBLING, "Available", cls.depot_sibling)
		cls._container(cls.HERE, "Available", cls.depot_here)
		cls._container(cls.ELSEWHERE, "Available", cls.depot_there)
		cls._container(cls.GONE, "Gate_Out", cls.depot_here)
		cls._container(cls.UNSTAMPED, "Available", None)

	@classmethod
	def tearDownClass(cls):
		_cleanup_customer_world(cls.customer)
		for no in (cls.HERE, cls.ELSEWHERE, cls.GONE, cls.UNSTAMPED, cls.SIBLING):
			frappe.db.delete("Container Movement", {"container": no})
			frappe.db.delete("Container", {"container_no": no})
		for depot in (cls.depot_here, cls.depot_there, cls.depot_sibling):
			frappe.db.delete("Depot", {"name": depot})
		for branch in (cls.IN_BRANCH, cls.OUT_BRANCH):
			frappe.db.delete("Branch", {"name": branch})
		frappe.db.commit()
		super().tearDownClass()

	@classmethod
	def _depot(cls, code: str, branch: str) -> str:
		if not frappe.db.exists("Branch", branch):
			frappe.get_doc({"doctype": "Branch", "branch": branch}).insert(ignore_permissions=True)
		existing = frappe.db.get_value("Depot", {"depot_code": code})
		if existing:
			return existing
		return frappe.get_doc({
			"doctype": "Depot",
			"depot_code": code,
			"depot_name": f"TankOut Depot {code}",
			"branch": branch,
			"is_active": 1,
		}).insert(ignore_permissions=True).name

	@classmethod
	def _container(cls, no: str, status: str, depot: str | None):
		if frappe.db.exists("Container", no):
			frappe.db.set_value("Container", no, {"status": status, "depot": depot}, update_modified=False)
			return
		frappe.get_doc({
			"doctype": "Container",
			"container_no": no,
			"container_type": "ISO Tank",
			"status": status,
			"depot": depot,
			"principal": cls.customer,
		}).insert(ignore_permissions=True)

	def setUp(self):
		super().setUp()
		_purge_bookings(self.customer)

	def _booking(self, containers, **kwargs):
		doc = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank Out",
			"customer": self.customer,
			"principal": self.customer,
			"contract": self.contract,
			"branch": kwargs.pop("branch", self.IN_BRANCH),
			"items": [{"container": c} for c in containers],
		})
		doc.update(kwargs)
		return doc

	def test_depot_derived_from_the_container(self):
		"""No depot typed, and none needed — the tank's master answers."""
		b = self._booking([self.HERE])
		b.insert(ignore_permissions=True)
		self.assertEqual(b.depot, self.depot_here)

	def test_derived_depot_overrides_whatever_was_carried(self):
		"""An outbound booking cannot happen at a depot the tank is not in, so a depot
		coming in from an import / API is corrected rather than trusted."""
		b = self._booking([self.HERE], depot=self.depot_there, branch=self.OUT_BRANCH)
		b.branch = self.IN_BRANCH  # the container's own branch, so only the depot is wrong
		b.insert(ignore_permissions=True)
		self.assertEqual(b.depot, self.depot_here)

	def test_two_depots_of_one_branch_ride_on_one_booking(self):
		"""One customer collecting from a branch that runs two yards is ONE pickup.

		Splitting it made two bookings, two invoices and two sets of paperwork out of a
		single job. Each tank still gates out at its own depot — the gate reads
		``Container.depot``, never the booking's — so nothing downstream needs one answer.
		"""
		b = self._booking([self.HERE, self.SIBLING])
		b.insert(ignore_permissions=True)
		# No single answer, so the header states none rather than picking a side.
		self.assertIsNone(b.depot)
		self.assertEqual(
			sorted(r.depot for r in b.items), sorted([self.depot_here, self.depot_sibling])
		)

	def test_a_tank_in_another_branch_is_still_refused_on_a_split_booking(self):
		"""Branch is the boundary, not depot — and it is checked per row, so a booking that
		deliberately carries no header depot cannot slip past the check."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._booking([self.HERE, self.ELSEWHERE]).insert(ignore_permissions=True)
		self.assertIn("Branch", str(ctx.exception))

	def test_container_outside_the_booking_branch_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._booking([self.ELSEWHERE]).insert(ignore_permissions=True)
		self.assertIn("Branch", str(ctx.exception))

	def test_picker_offers_only_tanks_present_in_this_branch(self):
		"""The Desk container picker, narrowed server-side: a tank that already left or
		sits in another branch's yard is never offered for a Tank Out."""
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			booking_container_query,
		)

		names = [
			r[0]
			for r in booking_container_query(
				"Container", "", "name", 0, 20,
				{"direction": "Tank Out", "principal": self.customer, "branch": self.IN_BRANCH},
			)
		]
		self.assertIn(self.HERE, names)
		self.assertNotIn(self.GONE, names)
		self.assertNotIn(self.ELSEWHERE, names)

	def test_tank_in_picker_stays_open(self):
		"""Inbound tanks are by definition not in the depot — narrowing the picker the
		same way would offer nothing."""
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			booking_container_query,
		)

		names = [
			r[0]
			for r in booking_container_query(
				"Container", "", "name", 0, 20,
				{"direction": "Tank In", "principal": self.customer, "branch": self.IN_BRANCH},
			)
		]
		self.assertIn(self.GONE, names)

	def test_excel_import_reports_the_same_three_refusals(self):
		"""The file is the one way into the grid that skips the picker, so it is judged
		after the fact — with the number and the reason on screen."""
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			_import_block,
		)

		def master(no):
			return frappe.db.get_value(
				"Container", no, ["name", "status", "depot", "principal"], as_dict=True
			)

		def block(no, direction="Tank Out", principal=None, depots=None):
			return _import_block(
				master(no), direction, principal or self.customer, depots or [self.depot_here]
			)

		self.assertIsNone(block(self.HERE))
		self.assertIn("tidak ada di depo", block(self.GONE))
		self.assertIn("di luar Branch", block(self.ELSEWHERE))
		self.assertIn("principal lain", block(self.HERE, principal="Someone Else"))
		# Ownership is the one test that also applies inbound — a tank the master says
		# belongs to someone else is not this booking's to move, either way.
		self.assertIn(
			"principal lain", block(self.HERE, direction="Tank In", principal="Someone Else")
		)
		self.assertIsNone(block(self.GONE, direction="Tank In"))

	def test_a_container_owned_by_someone_else_is_refused(self):
		"""The Principal is who owns the tank — a row naming another owner's container is
		refused on save, whichever door it came through (import, paste, API)."""
		other = ensure_test_customer("Phase3 Other Principal")
		frappe.db.set_value("Container", self.HERE, "principal", other, update_modified=False)
		try:
			with self.assertRaises(frappe.ValidationError) as ctx:
				self._booking([self.HERE]).insert(ignore_permissions=True)
			self.assertIn("bukan milik Principal", str(ctx.exception))
		finally:
			frappe.db.set_value("Container", self.HERE, "principal", self.customer, update_modified=False)

	def test_a_container_with_no_owner_is_adopted_not_refused(self):
		"""A blank owner is not a conflict — the booking stamps its own Principal on it."""
		frappe.db.set_value("Container", self.HERE, "principal", None, update_modified=False)
		try:
			b = self._booking([self.HERE])
			b.insert(ignore_permissions=True)  # must NOT raise
			self.assertEqual(
				frappe.db.get_value("Container", self.HERE, "principal"), self.customer
			)
		finally:
			frappe.db.set_value("Container", self.HERE, "principal", self.customer, update_modified=False)

	def test_container_without_a_depot_leaves_the_header_blank(self):
		"""Legacy tanks were never stamped with a depot (the stamp is written at gate-in), so
		the rows can answer nothing. The booking still saves and is NOT refused for a
		mismatch it never claimed — but no depot is invented for it either: an outbound
		header depot is what the tanks said, or nothing."""
		b = self._booking([self.UNSTAMPED])
		b.insert(ignore_permissions=True)
		self.assertIsNone(b.depot)

	def test_picker_still_offers_a_tank_with_no_depot(self):
		"""Narrowing by branch must not hide tanks the depot really is holding."""
		from container_depot.container_depot.doctype.container_booking.container_booking import (
			booking_container_query,
		)

		names = [
			r[0]
			for r in booking_container_query(
				"Container", "", "name", 0, 20,
				{"direction": "Tank Out", "principal": self.customer, "branch": self.IN_BRANCH},
			)
		]
		self.assertIn(self.UNSTAMPED, names)


class TestContainerReservation(FrappeTestCase):
	"""A live booking RESERVES its containers: nobody else may book them, and dropping a
	row gives the tank straight back."""

	CUSTOMER = "Phase3 Reservation Customer"
	TANK = "RSVU0000001"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.customer = ensure_test_customer(cls.CUSTOMER)
		_cleanup_customer_world(cls.customer)
		cls.contract = _make_active_contract(cls.customer, payment_type="Cash")

	@classmethod
	def tearDownClass(cls):
		_cleanup_customer_world(cls.customer)
		for no in (cls.TANK, "RSVU0000002", "RSVU0000003"):
			frappe.db.delete("Container Movement", {"container": no})
			frappe.db.delete("Container", {"container_no": no})
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		super().setUp()
		_purge_bookings(self.customer)
		self._tank(self.TANK)

	def _tank(self, no):
		if frappe.db.exists("Container", no):
			frappe.db.set_value(
				"Container", no, {"status": GATE_OUT, "created_by_booking": None}, update_modified=False
			)
			return no
		return frappe.get_doc({
			"doctype": "Container",
			"container_no": no,
			"container_type": "ISO Tank",
			"status": GATE_OUT,
			"principal": self.customer,
		}).insert(ignore_permissions=True).name

	def _booking(self, *container_nos):
		return frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"principal": self.customer,
			"contract": self.contract,
			"items": [{"container_no": no} for no in container_nos],
		})

	def test_a_booked_tank_cannot_be_booked_again(self):
		"""The reservation holds from the moment the FIRST booking is saved — a draft has
		no Booking Code yet, so the code-based submit gate never saw it."""
		first = self._booking(self.TANK)
		first.insert(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Container", self.TANK, "status"), "Booked")

		with self.assertRaises(frappe.ValidationError) as ctx:
			self._booking(self.TANK).insert(ignore_permissions=True)
		self.assertIn(first.name, str(ctx.exception))

	def test_a_cancelled_booking_frees_the_tank_for_the_next_one(self):
		first = self._booking(self.TANK)
		first.insert(ignore_permissions=True)
		first.booking_status = "Cancelled"
		first.docstatus = 2
		first.db_update()
		frappe.db.commit()
		self._booking(self.TANK).insert(ignore_permissions=True)  # must NOT raise

	def test_dropping_a_row_releases_the_tank(self):
		"""Removing the row gives the tank back to Gate_Out — where it was reserved from.
		Never to Available: a tank that never arrived is not standing in the yard."""
		other = self._tank("RSVU0000002")
		b = self._booking(self.TANK, other)
		b.insert(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Container", self.TANK, "status"), "Booked")

		b.items = [row for row in b.items if row.container != self.TANK]
		b.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Container", self.TANK, "status"), GATE_OUT)
		self.assertEqual(
			frappe.db.get_value("Container", other, "status"), "Booked",
			"the row that stayed keeps its reservation",
		)

	def test_repointing_a_row_releases_the_tank_it_left(self):
		swapped = self._tank("RSVU0000003")
		b = self._booking(self.TANK)
		b.insert(ignore_permissions=True)

		b.items[0].container = swapped
		b.items[0].container_no = swapped
		b.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Container", self.TANK, "status"), GATE_OUT)
		self.assertEqual(frappe.db.get_value("Container", swapped, "status"), "Booked")

	def test_dropping_a_row_deletes_the_master_it_minted(self):
		"""A phantom exists only because of this booking, so a dropped row takes it with
		it — the same rule cancel applies."""
		phantom = "RSVU0009999"
		frappe.db.delete("Container", {"container_no": phantom})
		b = self._booking(phantom)
		b.insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Container", phantom))

		b.items = []
		with self.assertRaises(frappe.ValidationError):
			b.save(ignore_permissions=True)  # a booking still needs a container
		b.reload()
		b.items[0].container_no = self.TANK
		b.items[0].container = self.TANK
		b.save(ignore_permissions=True)
		self.assertFalse(
			frappe.db.exists("Container", phantom), "the phantom master goes with its row"
		)
