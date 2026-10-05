"""Booking charges stay open until an invoice carries them (user 2026-10-05).

* After Confirmed and after a bon, charges and rates may still change, priced as on a draft.
* An invoice closes them: TOP once a consolidated bill holds the booking, Cash once its own
  invoice exists — a draft one is voided by Batalkan Invoice to reopen them.
* A Confirmed Cash booking whose charges change with no invoice owes them again: Unpaid,
  then Regenerate Invoice and the Cashier. Charges that bill nothing read Paid.
* Finance off never invoices, so the charges never close — and on a Cash booking nothing
  about the charges stands in the way, from draft through a closed bon. The one gate left is
  the hand-set payment label (Tandai Lunas), which a charge edit never touches.

Self-cleaning: reuses test_booking_bon_sync's fixtures and purge, plus the charge rows, the
draft invoices and the Version rows this module adds.
"""

from __future__ import annotations

import frappe

from container_depot import invoicing
from container_depot.container_depot.doctype.charge_template.charge_template import get_charges
from container_depot.container_depot.doctype.container_booking.container_booking import (
	cancel_draft_invoice,
	regenerate_invoice,
	set_payment_status,
)
from container_depot.container_depot.order_generation import make_order
from container_depot.tests.finance_fixture import require_finance
from container_depot.tests.test_booking_bon_sync import CUSTOMER, PREFIX, VEHICLE, _Base

LIFT = "Lift Off"  # priced at 250000 by test_container_booking._make_active_contract


def _purge_billing(since=None):
	contracts = frappe.get_all("Depot Contract", filters={"customer": CUSTOMER}, pluck="name") or [""]
	frappe.db.delete("Notification Log", {"document_type": "Depot Contract", "document_name": ["in", contracts]})
	if since:  # the fixture's do_document is a path with no file behind it
		frappe.db.delete("Error Log", {"method": "Error Attaching File", "creation": [">=", since]})
	bookings = frappe.get_all("Container Booking", filters={"customer": CUSTOMER}, pluck="name") or [""]
	invoices = frappe.get_all("Sales Invoice", filters={"customer": CUSTOMER}, pluck="name") or [""]
	for table in frappe.get_meta("Sales Invoice").get_table_fields():
		frappe.db.delete(table.options, {"parent": ["in", invoices], "parenttype": "Sales Invoice"})
	frappe.db.delete("Sales Invoice", {"name": ["in", invoices]})
	frappe.db.delete("Container Booking Charge", {"parent": ["in", bookings]})
	templates = frappe.get_all("Booking Charge Template", filters={"customer": CUSTOMER}, pluck="name") or [""]
	frappe.db.delete("Booking Charge Template Item", {"parent": ["in", templates]})
	frappe.db.delete("Booking Charge Template", {"name": ["in", templates]})
	frappe.db.delete("Version", {"ref_doctype": "Container Booking", "docname": ["in", bookings]})
	for dt, names in (("Sales Invoice", invoices), ("Container Booking", bookings)):
		frappe.db.delete("Comment", {"reference_doctype": dt, "reference_name": ["in", names]})
	frappe.db.commit()


class TestChargesOpenUntilInvoiced(_Base):
	def setUp(self):
		self.started = frappe.utils.now_datetime()
		require_finance(self)
		_purge_billing()
		super().setUp()

	def tearDown(self):
		_purge_billing(self.started)
		super().tearDown()

	def _add_lift(self, b):
		b.append("charges", {"item": LIFT})
		b.save()
		b.reload()
		return b

	def _cash(self):
		frappe.db.set_value("Depot Contract", self.contract, "payment_type", "Cash")
		b = self._tank_in()
		self.assertEqual((b.payment_type, b.payment_status, b.sales_invoice), ("Cash", "Paid", None))
		return b

	def test_top_charges_stay_open_after_a_bon_until_billed(self):
		b = self._tank_in()
		make_order(b.name, [b.items[0].booking_code], vehicle_data=VEHICLE, submit=True)
		b = self._add_lift(frappe.get_doc("Container Booking", b.name))
		self.assertEqual((b.charges[0].rate, b.charges[0].qty, b.charges_total), (250000, 1, 250000))
		self.assertEqual(b.payment_status, "Unpaid")  # TOP is never asked about money here

		si = invoicing.create_draft_sales_invoice(b.customer, b._billable_lines(), invoice_type="Booking")
		frappe.db.set_value("Container Booking", b.name, "sales_invoice", si)  # what bill_customer does
		b.reload()
		b.charges[0].rate = 1
		with self.assertRaisesRegex(frappe.ValidationError, "sudah masuk tagihan"):
			b.save()

	def test_cash_charges_added_after_confirm_are_owed_again(self):
		b = self._add_lift(self._cash())
		self.assertEqual(b.payment_status, "Unpaid")
		self.assertTrue(frappe.db.exists("Comment", {"reference_name": b.name, "content": ["like", "%Regenerate Invoice%"]}))
		b.charges = []
		b.save()
		self.assertEqual(frappe.db.get_value("Container Booking", b.name, "payment_status"), "Paid")

	def test_cash_draft_invoice_locks_until_batalkan_invoice(self):
		b = self._add_lift(self._cash())
		si = regenerate_invoice(b.name)
		b.reload()
		b.charges[0].rate = 100
		with self.assertRaisesRegex(frappe.ValidationError, "Batalkan Invoice"):
			b.save()

		cancel_draft_invoice(b.name)
		self.assertEqual(frappe.db.get_value("Sales Invoice", si, "docstatus"), 2)
		b.reload()
		self.assertEqual((b.sales_invoice, b.payment_status), (None, "Unpaid"))
		b.charges[0].rate = 100
		b.save()
		self.assertEqual(frappe.db.get_value("Container Booking", b.name, "charges_total"), 100)

	def test_customer_and_header_stay_frozen_after_submit(self):
		b = self._tank_in()
		b.customer = frappe.db.get_value("Customer", {"name": ["!=", CUSTOMER]}, "name")
		with self.assertRaisesRegex(frappe.ValidationError, "yang masih bisa diubah"):
			b.save()

	def test_finance_off_never_closes_the_charges(self):
		b = self._add_lift(self._tank_in())
		si = invoicing.create_draft_sales_invoice(b.customer, b._billable_lines(), invoice_type="Booking")
		frappe.db.set_value("Container Booking", b.name, "sales_invoice", si)
		require_finance(self, enabled=False)
		b.reload()
		b.charges[0].rate = 5
		b.save()
		self.assertEqual(frappe.db.get_value("Container Booking", b.name, "charges_total"), 5)


class TestFinanceOffCash(_Base):
	def setUp(self):
		self.started = frappe.utils.now_datetime()
		require_finance(self, enabled=False)
		_purge_billing()
		super().setUp()
		frappe.db.set_value("Depot Contract", self.contract, "payment_type", "Cash")

	def tearDown(self):
		_purge_billing(self.started)
		super().tearDown()

	def _draft(self):
		return frappe.get_doc({
			"doctype": "Container Booking", "direction": "Tank In", "customer": self.customer,
			"contract": self.contract, "do_reference": "DO-OFF", "do_document": "/files/do.pdf",
			"plan_date": frappe.utils.today(), "items": [{"container_no": f"{PREFIX}0000001"}],
			"charges": [{"item": LIFT}],
		}).insert(ignore_permissions=True)

	def test_charges_never_stand_in_the_way(self):
		b = self._draft()
		self.assertEqual((b.payment_type, b.charges_total), ("Cash", 250000))
		b.charges[0].rate = 200000
		b.save()

		set_payment_status(b.name, "Paid")  # Tandai Lunas: the hand-set label, no invoice
		b.reload()
		b.submit()
		self.assertIsNone(b.sales_invoice)

		# Confirmed: a template line in, a rate changed — then a bon, closed even.
		tpl = frappe.get_doc({
			"doctype": "Booking Charge Template", "template_name": "BSY Off Lift", "customer": self.customer,
			"direction": "Tank In", "items": [{"item": LIFT}],
		}).insert(ignore_permissions=True)
		rows = get_charges("Booking Charge Template", tpl.name, "Container Booking", customer=b.customer, direction="Tank In")["rows"]
		b.reload()
		b.append("charges", rows[0])
		b.charges[0].rate = 150000
		b.save()
		bon = make_order(b.name, [b.items[0].booking_code], vehicle_data=VEHICLE, submit=True)
		frappe.db.set_value("Order Bongkar", bon, "order_status", "Completed")
		b.reload()
		b.remove(b.charges[1])
		b.save()

		b.reload()
		self.assertEqual((b.charges_total, b.payment_status, b.sales_invoice), (150000, "Paid", None))
		self.assertFalse(frappe.db.exists("Sales Invoice", {"customer": self.customer}))

	def test_the_only_gate_is_the_paid_label(self):
		b = self._draft()
		with self.assertRaisesRegex(frappe.ValidationError, "Tandai Lunas"):
			b.submit()
