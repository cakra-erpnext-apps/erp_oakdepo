"""Phase 9 (B6) tests: Isotank Booking menu refinements.

Covers the post-review decisions:
- Depot is mandatory (Desk) and auto-filled for programmatic callers.
- Contract is optional; a Cash / walk-in booking auto-creates a *draft* Sales
  Invoice on save, stays blocked until the Cashier marks it Paid, then releases
  the Booking Code on submit.
- A single ``container`` input (get-or-create): a new Tank In number spawns a
  Container master in the pre-arrival ``Booked`` state, excluded from live
  inventory until gate-in flips it to ``Gate_In``.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from container_depot.ess import inventory
from container_depot.state_machine import assert_transition, is_allowed
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_isotank_booking import (
	_cleanup_customer_world,
	_make_active_contract,
)


def _ensure_test_depot() -> str:
	"""The seeded primary depot; created defensively for a bare test site."""
	if not frappe.db.exists("Depot", "SUB"):
		frappe.get_doc({
			"doctype": "Depot",
			"depot_code": "SUB",
			"depot_name": "Surabaya",
			"city": "Surabaya",
			"is_active": 1,
		}).insert(ignore_permissions=True)
		frappe.db.commit()
	return "SUB"


class TestDepotMandatory(FrappeTestCase):
	def test_depot_field_is_mandatory(self):
		self.assertEqual(frappe.get_meta("Isotank Booking").get_field("depot").reqd, 1)

	def test_depot_autofilled_for_programmatic_caller(self):
		_ensure_test_depot()
		customer = ensure_test_customer("B6 Depot Customer")
		_cleanup_customer_world(customer)
		try:
			b = frappe.get_doc({
				"doctype": "Isotank Booking",
				"direction": "Tank In",
				"lift_type": "Lift Off",
				"customer": customer,
				"booking_status": "Pending Confirmation",
				"items": [{"container_no": "B6DEPOT0001"}],
			}).insert(ignore_permissions=True)
			self.assertTrue(b.depot, "depot was not auto-filled for a programmatic booking")
		finally:
			_cleanup_customer_world(customer)
			frappe.db.rollback()


class TestLiftTypeDerived(FrappeTestCase):
	"""lift_type is no longer entered separately — it is derived from direction
	(Tank In = Lift Off / drop at depot; Tank Out = Lift On / take from depot)."""

	def test_lift_type_is_read_only(self):
		self.assertEqual(frappe.get_meta("Isotank Booking").get_field("lift_type").read_only, 1)

	def test_direction_maps_to_lift_type(self):
		b = frappe.new_doc("Isotank Booking")
		b.direction = "Tank In"
		b._sync_lift_type()
		self.assertEqual(b.lift_type, "Lift Off")
		b.direction = "Tank Out"
		b._sync_lift_type()
		self.assertEqual(b.lift_type, "Lift On")


class TestBookedTransition(FrappeTestCase):
	def test_booked_to_gatein_allowed(self):
		self.assertTrue(is_allowed("Booked", "Gate_In"))
		assert_transition("Booked", "Gate_In")  # must not raise

	def test_available_to_booked_allowed(self):
		self.assertTrue(is_allowed("Available", "Booked"))


class TestCashContractFlow(FrappeTestCase):
	"""Cash booking with a contract: draft invoice on save, held at Pending
	Payment until paid, booking code released on submit once the Cashier marks
	it Paid."""

	def setUp(self):
		_ensure_test_depot()
		self.customer = ensure_test_customer("B6 Cash Customer")
		_cleanup_customer_world(self.customer)
		# Cash contract; tariff is Lift Off @ 250000 (see _make_active_contract).
		self.contract = _make_active_contract(self.customer, payment_type="Cash")

	def tearDown(self):
		_cleanup_customer_world(self.customer)
		frappe.db.rollback()

	def _booking(self):
		return frappe.get_doc({
			"doctype": "Isotank Booking",
			"direction": "Tank In",  # Tank In -> Lift Off @ 250000 tariff line (derived)
			"customer": self.customer,
			"contract": self.contract,
			"booking_status": "Pending Confirmation",
			"do_reference": "DO-CASH",
			"do_document": "/files/do.pdf",
			"items": [{"container_no": "B6CASH00001"}],
		})

	def test_draft_invoice_autocreated_on_save(self):
		b = self._booking()
		b.insert(ignore_permissions=True)
		self.assertTrue(b.depot, "depot not auto-filled")
		self.assertTrue(b.sales_invoice, "draft Sales Invoice not auto-created on save")
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", b.sales_invoice, "grand_total"),
			250000,  # 1 container x Lift Off 250000
		)

	def test_held_pending_payment_until_invoice_paid(self):
		b = self._booking()
		b.insert(ignore_permissions=True)
		self.assertTrue(b.sales_invoice)
		with self.assertRaises(frappe.ValidationError):
			b.submit()  # draft invoice is not Paid yet
		b.reload()
		# Awaiting the Cashier — parked at Pending Payment, NOT a hard Blocked.
		self.assertEqual(b.booking_status, "Pending Payment")
		self.assertEqual(b.docstatus, 0, "must remain a draft until paid")

	def test_code_released_after_cashier_marks_paid(self):
		b = self._booking()
		b.insert(ignore_permissions=True)
		# Cashier "acc": the linked Sales Invoice becomes submitted + Paid.
		frappe.db.set_value("Sales Invoice", b.sales_invoice, {"docstatus": 1, "status": "Paid"})
		b.submit()
		b.reload()
		self.assertEqual(b.booking_status, "Confirmed")
		self.assertTrue(
			frappe.db.exists("Booking Code", {"booking": b.name, "state": "Active"}),
			"booking code was not issued after payment",
		)


class TestPaymentStatusSync(FrappeTestCase):
	"""payment_status follows the linked Sales Invoice's live settlement — a draft
	Cash booking whose invoice gets paid flips Unpaid → Paid without waiting for
	submit (closes the 'paid the SI but booking still Unpaid' gap). Scoped to
	bookings only."""

	def setUp(self):
		_ensure_test_depot()
		self.customer = ensure_test_customer("B6 PaySync Customer")
		_cleanup_customer_world(self.customer)
		self.contract = _make_active_contract(self.customer, payment_type="Cash")

	def tearDown(self):
		_cleanup_customer_world(self.customer)
		frappe.db.rollback()

	def _draft_cash_booking(self):
		return frappe.get_doc({
			"doctype": "Isotank Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"contract": self.contract,
			"booking_status": "Pending Payment",
			"do_reference": "DO-SYNC",
			"items": [{"container_no": "B6PAYSYNC01"}],
		}).insert(ignore_permissions=True)

	def _mark_invoice_paid(self, si):
		frappe.db.set_value(
			"Sales Invoice", si, {"docstatus": 1, "status": "Paid", "outstanding_amount": 0}
		)

	def test_unpaid_while_invoice_is_draft(self):
		b = self._draft_cash_booking()
		self.assertTrue(b.sales_invoice, "draft Sales Invoice not linked")
		self.assertEqual(b.payment_status, "Unpaid")  # draft invoice → still Unpaid

	def test_sync_flips_to_paid_when_invoice_paid(self):
		from container_depot.operations.doctype.isotank_booking.isotank_booking import (
			sync_bookings_for_invoice,
		)

		b = self._draft_cash_booking()
		self._mark_invoice_paid(b.sales_invoice)
		sync_bookings_for_invoice(b.sales_invoice)
		b.reload()
		self.assertEqual(b.payment_status, "Paid")

	def test_payment_entry_hook_flips_booking(self):
		from container_depot.operations.doctype.isotank_booking.isotank_booking import (
			on_payment_entry_change,
		)

		b = self._draft_cash_booking()
		self._mark_invoice_paid(b.sales_invoice)
		# Stand in for a submitted Payment Entry that settles the invoice.
		fake_pe = frappe._dict(
			references=[frappe._dict(reference_doctype="Sales Invoice", reference_name=b.sales_invoice)]
		)
		on_payment_entry_change(fake_pe)
		b.reload()
		self.assertEqual(b.payment_status, "Paid")

	def test_before_save_picks_up_paid_invoice(self):
		b = self._draft_cash_booking()
		self._mark_invoice_paid(b.sales_invoice)
		b.save(ignore_permissions=True)  # before_save defensive sync
		b.reload()
		self.assertEqual(b.payment_status, "Paid")


class TestDiscardCleansInvoice(FrappeTestCase):
	"""Discarding / cancelling a Cash booking removes its auto-created *unpaid
	draft* Sales Invoice (an orphan with no ledger impact); a submitted / paid
	invoice is left untouched."""

	def setUp(self):
		_ensure_test_depot()
		self.customer = ensure_test_customer("B6 Discard Customer")
		_cleanup_customer_world(self.customer)
		self.contract = _make_active_contract(self.customer, payment_type="Cash")

	def tearDown(self):
		_cleanup_customer_world(self.customer)
		frappe.db.rollback()

	def _draft(self, cn):
		return frappe.get_doc({
			"doctype": "Isotank Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"contract": self.contract,
			"booking_status": "Pending Payment",
			"do_reference": "DO-DISC",
			"items": [{"container_no": cn}],
		}).insert(ignore_permissions=True)

	def test_discard_removes_unpaid_draft_invoice(self):
		b = self._draft("B6DISC00001")
		si = b.sales_invoice
		self.assertTrue(si and frappe.db.exists("Sales Invoice", si), "draft invoice not created")
		b.delete(ignore_permissions=True)  # discard the draft booking
		self.assertFalse(frappe.db.exists("Sales Invoice", si), "orphan draft invoice not cleaned up")

	def test_paid_invoice_survives_discard(self):
		b = self._draft("B6DISC00002")
		si = b.sales_invoice
		# Pretend the Cashier submitted + paid it.
		frappe.db.set_value("Sales Invoice", si, {"docstatus": 1, "status": "Paid", "outstanding_amount": 0})
		b.delete(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Sales Invoice", si), "submitted/paid invoice must not be auto-deleted")


class TestWalkInNoContract(FrappeTestCase):
	"""A walk-in Cash booking with NO contract must still save (depot auto-filled,
	payment_type defaults to Cash) rather than erroring on a missing contract."""

	def setUp(self):
		_ensure_test_depot()
		self.customer = ensure_test_customer("B6 WalkIn Customer")
		_cleanup_customer_world(self.customer)

	def tearDown(self):
		_cleanup_customer_world(self.customer)
		frappe.db.rollback()

	def test_walk_in_saves_without_contract(self):
		b = frappe.get_doc({
			"doctype": "Isotank Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"booking_status": "Pending Confirmation",
			"items": [{"container_no": "B6WALKIN001"}],
		})
		b.insert(ignore_permissions=True)  # must not raise "no Active contract"
		self.assertEqual(b.payment_type, "Cash")
		self.assertTrue(b.depot)


class TestContainerSingleInput(FrappeTestCase):
	"""Single container input: get-or-create + pre-arrival Booked + inventory
	exclusion + gate-in transition."""

	CN = "B6SINGLE001"

	def setUp(self):
		_ensure_test_depot()
		self.customer = ensure_test_customer("B6 Single Customer")
		_cleanup_customer_world(self.customer)
		self._purge_container()

	def tearDown(self):
		self._purge_container()
		_cleanup_customer_world(self.customer)
		frappe.db.rollback()

	def _purge_container(self):
		frappe.db.delete("Container Movement", {"container": self.CN})
		frappe.db.delete("Container", {"container_no": self.CN})
		frappe.db.commit()

	def _booking(self):
		return frappe.get_doc({
			"doctype": "Isotank Booking",
			"direction": "Tank In",
			"lift_type": "Lift Off",
			"customer": self.customer,
			"booking_status": "Pending Confirmation",
			"items": [{"container_no": self.CN}],
		})

	def test_getorcreate_makes_booked_master(self):
		b = self._booking()
		b.insert(ignore_permissions=True)
		b.reload()
		link = b.items[0].container
		self.assertTrue(link, "container link was not resolved from the typed number")
		self.assertEqual(frappe.db.get_value("Container", link, "status"), "Booked")

	def test_no_duplicate_master_on_rebooking(self):
		self._booking().insert(ignore_permissions=True)
		self._booking().insert(ignore_permissions=True)
		self.assertEqual(frappe.db.count("Container", {"container_no": self.CN}), 1)

	def test_booked_excluded_until_gatein(self):
		b = self._booking()
		b.insert(ignore_permissions=True)
		link = b.items[0].container

		# Pre-arrival: must not appear in live inventory.
		res = inventory.get_tank_list(search=self.CN)
		self.assertEqual(res["total"], 0, "a Booked tank leaked into live inventory")

		# Gate-in flips Booked -> Gate_In (exercises the state-machine edge with
		# NO automation flag set).
		c = frappe.get_doc("Container", link)
		c.status = "Gate_In"
		c.eir_in_date = now_datetime()
		c.save(ignore_permissions=True)

		res2 = inventory.get_tank_list(search=self.CN)
		self.assertEqual(res2["total"], 1, "gated-in tank is missing from inventory")
