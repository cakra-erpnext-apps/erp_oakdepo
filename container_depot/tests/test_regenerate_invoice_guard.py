"""`regenerate_invoice` must refuse a TOP booking — the guard protects the monthly bill.

The trap it closes: "submitted, charges > 0, no ``sales_invoice``" is the NORMAL resting
state of a postpaid booking waiting for consolidated billing (``_auto_invoice`` skips TOP
on purpose), and it is indistinguishable from the state Regenerate Invoice was written for
— a Cash booking whose invoice was cancelled. Without a payment_type check the button
appeared on every unbilled TOP booking, and pressing it filled ``sales_invoice`` with a
standalone invoice. That field is exactly what ``consolidated_billing._booking_lines``
requires to be EMPTY, so the charge would leave the customer's monthly statement silently.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot.consolidated_billing import bill_customer
from container_depot.container_depot.doctype.container_booking.container_booking import (
	regenerate_invoice,
)
from container_depot.tests.finance_fixture import require_finance
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_container_booking import (
	_cleanup_customer_world,
	_make_active_contract,
)


class TestRegenerateInvoiceGuard(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		require_finance(cls)
		cls.customer = ensure_test_customer("Regenerate Guard Test Co")
		_cleanup_customer_world(cls.customer)
		cls.contract = _make_active_contract(
			cls.customer, payment_type="TOP", credit_limit=1_000_000_000, payment_terms="NET 30"
		)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		_cleanup_customer_world(cls.customer)
		# …and the Customer itself. _cleanup_customer_world stops at the documents that
		# point AT the customer, so without this every run leaves another test party in
		# the picker for the operator to scroll past.
		try:
			frappe.delete_doc("Customer", cls.customer, ignore_permissions=True, force=True)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
		super().tearDownClass()

	def _top_booking(self, container_no: str):
		"""A submitted TOP booking that bills something and carries no invoice — the exact
		shape that used to light up the Regenerate Invoice button.

		Each test passes its own container: an open booking pins its container, so reusing
		one number would fail the double-booking guard rather than the thing under test.
		"""
		doc = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": self.customer,
			"contract": self.contract,
			"do_reference": "DO-TOP-REGEN",
			"charges": [{"item": "Lift Off"}],
			"items": [{"container_no": container_no}],
		})
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		doc.submit()
		doc.reload()
		self.assertEqual(doc.payment_type, "TOP")
		self.assertFalse(doc.sales_invoice, "a TOP booking accrues unbilled — no invoice yet")
		self.assertGreater(doc.charges_total, 0)
		return doc

	def test_top_booking_cannot_regenerate(self):
		booking = self._top_booking("TANK0008801")
		with self.assertRaises(frappe.ValidationError):
			regenerate_invoice(booking.name)
		booking.reload()
		self.assertFalse(
			booking.sales_invoice,
			"the refusal must leave the booking unlinked — that is what keeps it billable",
		)

	def test_refused_booking_is_still_swept_by_consolidated_billing(self):
		"""Why the guard exists, stated as an outcome rather than an error message."""
		booking = self._top_booking("TANK0008802")
		with self.assertRaises(frappe.ValidationError):
			regenerate_invoice(booking.name)

		invoices = bill_customer(self.customer, add_days(today(), -1), today())
		self.assertTrue(invoices, "the monthly run must still find the booking")
		booking.reload()
		self.assertIn(
			booking.sales_invoice,
			invoices,
			"the charge belongs to the consolidated invoice, not a standalone one",
		)
