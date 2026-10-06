"""Revisi Data on a Container Booking (user, 2026-10-06).

* Before a bon the way back is Kembali ke Draft; Revisi Data only exists once a bon does, so
  the form never offers both.
* Only the header facts move (dates, Reff Doc, shipper, survey, payment type, DO, notes), the
  status stays, and what follows them on a draft follows them here too (bon rows, survey day).
* The invoice locks single fields: Payment Type once one exists, Reff Doc / DO Reference once
  it is submitted (they are printed on it).
* A booking with an invoice is not cancelled — a draft one included.

Self-cleaning: test_booking_bon_sync's purge plus test_booking_charges_open's billing purge.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, today

from container_depot import invoicing
from container_depot.container_depot import revision
from container_depot.container_depot.doctype.container_booking import container_booking
from container_depot.container_depot.doctype.container_booking.container_booking import (
	generate_invoice,
	rollback_to_draft,
	void_draft,
)
from container_depot.container_depot.notify import notify_booking_revision_requested
from container_depot.container_depot.order_generation import make_order
from container_depot.tests.finance_fixture import require_finance
from container_depot.tests.test_booking_bon_sync import PREFIX, VEHICLE, _Base
from container_depot.tests.test_booking_charges_open import LIFT, _purge_billing
from container_depot.tests.test_eir import _make_container


def _revise(b, **values):
	b.reload()
	b.update(values)
	return revision.save_revision(frappe.as_json(b.as_dict()))


class TestBookingRevision(_Base):
	def setUp(self):
		self.started = frappe.utils.now_datetime()
		require_finance(self)
		_purge_billing()
		super().setUp()

	def tearDown(self):
		_purge_billing(self.started)
		super().tearDown()

	def _with_bon(self):
		b = self._tank_in()
		bon = make_order(b.name, [b.items[0].booking_code], vehicle_data=VEHICLE, submit=True)
		b.reload()
		return b, bon

	def test_revisi_data_only_once_a_bon_exists(self):
		b = self._tank_in()
		state = revision.state(b)
		self.assertEqual((state["can_revise"], state["can_answer"]), (0, 1))
		with self.assertRaisesRegex(frappe.ValidationError, "belum punya bon"):
			_revise(b, remarks="x")

		make_order(b.name, [b.items[0].booking_code], vehicle_data=VEHICLE, submit=True)
		self.assertEqual(revision.state(frappe.get_doc("Container Booking", b.name))["can_revise"], 1)
		with self.assertRaisesRegex(frappe.ValidationError, "Revisi Data"):
			container_booking.revert_booking_to_draft(b.name)

	def test_header_facts_change_in_place_and_reach_the_bon(self):
		b, bon = self._with_bon()
		new_day = add_days(today(), 2)
		_revise(b, plan_date=new_day, reff_doc="REF-9", shipper=self.customer, remarks="dikoreksi", do_reference="DO-9")

		b.reload()
		self.assertEqual((b.docstatus, b.booking_status), (1, "Confirmed"))
		self.assertEqual((getdate(b.plan_date), b.reff_doc, b.remarks, b.do_reference), (getdate(new_day), "REF-9", "dikoreksi", "DO-9"))
		self.assertEqual(b.items[0].shipper, self.customer)  # header -> row
		self.assertEqual(self._bon_row(bon).shipper, self.customer)  # row -> bon
		self.assertTrue(frappe.db.exists("Comment", {"reference_name": b.name, "content": ["like", "Revisi Data oleh%"]}))

		with self.assertRaisesRegex(frappe.ValidationError, "tidak boleh mengubah"):
			_revise(b, direction="Tank Out")
		b.reload()
		tank = b.items[0].container_no
		b.items[0].container_no = f"{PREFIX}0000099"
		revision.save_revision(frappe.as_json(b.as_dict()))  # the row keeps what the database says
		self.assertEqual(frappe.db.get_value("Container Booking Item", b.items[0].name, "container_no"), tank)
		b.reload()
		b.append("items", {"container_no": f"{PREFIX}0000098"})
		with self.assertRaises(frappe.ValidationError):  # nor does a row come or go
			revision.save_revision(frappe.as_json(b.as_dict()))
		# Without the revision mark the header is as locked as ever.
		b.reload()
		b.remarks = "lagi"
		with self.assertRaisesRegex(frappe.ValidationError, "yang masih bisa diubah"):
			b.save()

	def test_payment_type_follows_and_the_invoice_locks_fields(self):
		frappe.db.set_value("Depot Contract", self.contract, "payment_type", "Both")
		b, _bon = self._with_bon()
		self.assertEqual(b.payment_type, "Cash")  # a "Both" contract starts at Cash
		_revise(b, payment_type="TOP")
		self.assertEqual(  # TOP is owed until a consolidated bill sweeps it, as submit stamps it
			frappe.db.get_value("Container Booking", b.name, ["payment_type", "payment_status"]), ("TOP", "Unpaid")
		)
		_revise(b, payment_type="Cash")
		self.assertEqual(  # Cash that bills nothing reads Paid
			frappe.db.get_value("Container Booking", b.name, "payment_status"), "Paid"
		)

		b.reload()
		b.append("charges", {"item": LIFT})
		b.save()
		b.reload()
		si = invoicing.create_draft_sales_invoice(b.customer, b._billable_lines(), invoice_type="Booking")
		frappe.db.set_value("Container Booking", b.name, "sales_invoice", si)
		with self.assertRaisesRegex(frappe.ValidationError, "Payment Type"):
			_revise(b, payment_type="TOP")
		_revise(b, reff_doc="REF-DRAFT")  # a draft invoice re-reads it

		frappe.db.set_value("Sales Invoice", si, "docstatus", 1)
		with self.assertRaisesRegex(frappe.ValidationError, "Reff Doc"):
			_revise(b, reff_doc="REF-LATE")
		_revise(b, remarks="catatan tetap bisa")
		frappe.db.set_value("Sales Invoice", si, "docstatus", 0)  # so the purge may drop it

	def test_survey_day_moves_with_the_revision(self):
		tank = _make_container(f"{PREFIX}0000021", status="Available", principal=self.customer)
		b = self._booking(
			"Tank Out", [{"container": tank}], use_survey=1, survey_date=today(), plan_date=add_days(today(), 5)
		)
		survey = frappe.db.get_value("Survey Order", {"booking": b.name}, "name")
		self.assertTrue(survey)
		with patch.object(container_booking, "_bons_raised", return_value=["Order Muat X"]):
			with self.assertRaisesRegex(frappe.ValidationError, "Pick up Date"):
				_revise(b, survey_date=add_days(today(), 6))
			_revise(b, survey_date=add_days(today(), 3))
		b.reload()
		self.assertEqual(getdate(b.items[0].survey_date), getdate(add_days(today(), 3)))
		self.assertEqual(
			getdate(frappe.db.get_value("Survey Order", survey, "survey_date")), getdate(add_days(today(), 3))
		)

	def test_a_request_is_answered_by_tolak_or_by_the_revision(self):
		b, _bon = self._with_bon()
		revision.request(b, "tanggal salah", notify_booking_revision_requested)
		self.assertEqual(frappe.db.get_value("Container Booking", b.name, "revision_requested_by"), "Administrator")
		revision.reject("Container Booking", b.name, "tanggal sudah benar")
		self.assertEqual(frappe.db.get_value("Container Booking", b.name, "revision_requested"), 0)

		revision.request(b, "reff salah", notify_booking_revision_requested)
		_revise(b, reff_doc="REF-OK")
		self.assertEqual(frappe.db.get_value("Container Booking", b.name, "revision_requested"), 0)

	def test_a_booking_with_an_invoice_is_not_cancelled(self):
		frappe.db.set_value("Depot Contract", self.contract, "payment_type", "Cash")
		b = frappe.get_doc({
			"doctype": "Container Booking", "direction": "Tank In", "customer": self.customer,
			"contract": self.contract, "do_reference": "DO-SYNC", "do_document": "/files/do.pdf",
			"plan_date": today(), "items": [{"container_no": f"{PREFIX}0000031"}], "charges": [{"item": LIFT}],
		}).insert(ignore_permissions=True)
		si = generate_invoice(b.name)["sales_invoice"]
		with self.assertRaisesRegex(frappe.ValidationError, "sudah punya invoice"):
			void_draft(b.name)
		self.assertEqual(frappe.db.get_value("Sales Invoice", si, "docstatus"), 0)

		rollback_to_draft(b.name)
		void_draft(b.name)
		self.assertEqual(frappe.db.get_value("Container Booking", b.name, "docstatus"), 2)
