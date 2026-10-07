"""Revisi Data on Survey Order, Leak Check and Gate Entry (user, 2026-10-07: every finished
order can be corrected in place).

* The status stays, the locked fields refuse, and a Survey Order keeps its tanks: only their
  notes move.
* Leak Check re-derives its leak flag from the photos.
* The PWA path (``revision.save_fields``) takes only its own few fields.
* Ajukan Revisi / Tolak Revisi go through the shared generic request.

Self-cleaning: test_booking_bon_sync's purge (containers, bookings, surveys, leak checks and
gate entries under its PREFIX).
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, now_datetime, today

from container_depot.container_depot import revision
from container_depot.container_depot.doctype.survey_order.survey_order import refresh_progress
from container_depot.tests.test_booking_bon_sync import PREFIX, _Base
from container_depot.tests.test_eir import _make_container


def _revise(doc, **values):
	doc.reload()
	doc.update(values)
	return revision.save_revision(frappe.as_json(doc.as_dict()))


class TestRevisionMoreOrders(_Base):
	def tearDown(self):
		gates = frappe.get_all("Gate Entry", filters={"container_no": ["like", f"{PREFIX}%"]}, pluck="name") or [""]
		frappe.db.delete("Comment", {"reference_doctype": "Gate Entry", "reference_name": ["in", gates]})
		frappe.db.delete("Notification Log", {"document_type": "Gate Entry", "document_name": ["in", gates]})
		super().tearDown()

	def _finished_survey(self):
		b = self._booking(
			"Tank Out",
			[{"container": _make_container(f"{PREFIX}0000041", status="Available", principal=self.customer)}],
			use_survey=1, survey_date=today(),
		)
		name = frappe.db.get_value("Survey Order", {"booking": b.name})
		for row in frappe.get_all("Survey Order Tank", filters={"parent": name}, pluck="name"):
			frappe.db.set_value("Survey Order Tank", row, "status", "Survey Done")
		refresh_progress(name)
		return frappe.get_doc("Survey Order", name)

	def test_survey_order_notes_and_date_move_tanks_stay(self):
		so = self._finished_survey()
		self.assertEqual((so.docstatus, so.status), (1, "Completed"))
		self.assertEqual(revision.state(so)["can_revise"], 1)

		row = so.tanks[0]
		revision.save_fields("Survey Order", so.name, {"survey_notes": "dikoreksi", "status": "Lowered"}, row=row.name)
		self.assertEqual(
			frappe.db.get_value("Survey Order Tank", row.name, ["survey_notes", "status"]),
			("dikoreksi", "Survey Done"),
		)

		new_day = add_days(today(), -1)
		so.reload()
		so.update({"survey_date": new_day})
		so.tanks[0].status = "Waiting Lowering"  # put back from the database
		revision.save_revision(frappe.as_json(so.as_dict()))
		so.reload()
		self.assertEqual((getdate(so.survey_date), so.docstatus, so.status), (getdate(new_day), 1, "Completed"))
		self.assertEqual(so.tanks[0].status, "Survey Done")

		so.tanks = []
		with self.assertRaisesRegex(frappe.ValidationError, "menambah atau menghapus tank"):
			revision.save_revision(frappe.as_json(so.as_dict()))
		with self.assertRaisesRegex(frappe.ValidationError, "tidak boleh mengubah"):
			_revise(so, booking=self._tank_in().name)

	def test_leak_check_flag_follows_the_photos(self):
		c = _make_container(f"{PREFIX}0000042", status="Available")
		lc = frappe.get_doc({
			"doctype": "Leak Check", "container": c,
			"photos": [{"photo": "/files/leak-test.jpg", "is_leak": 0}],
		}).insert(ignore_permissions=True)
		lc.submit()
		self.assertEqual(lc.has_leak, 0)

		lc.reload()
		lc.photos[0].is_leak = 1
		lc.remarks = "bocor kecil"
		revision.save_revision(frappe.as_json(lc.as_dict()))
		lc.reload()
		self.assertEqual((lc.has_leak, lc.remarks, lc.status, lc.docstatus), (1, "bocor kecil", "Completed", 1))

		with self.assertRaisesRegex(frappe.ValidationError, "tidak boleh mengubah"):
			_revise(lc, recorded_on=add_days(now_datetime(), -3))

	def _gate(self):
		ge = frappe.get_doc({
			"doctype": "Gate Entry", "container_no": f"{PREFIX}0000043", "status": "Gate_In_Completed",
			"truck_plate": "B 1 AA", "driver_name": "Budi", "gate_in_timestamp": now_datetime(),
			"docstatus": 1,
		})
		ge.db_insert()
		return frappe.get_doc("Gate Entry", ge.name)

	def test_gate_entry_truck_moves_times_stay(self):
		ge = self._gate()
		revision.save_fields("Gate Entry", ge.name, {"truck_plate": "B 2 BB", "gate_in_timestamp": "2020-01-01 00:00:00"})
		ge.reload()
		self.assertEqual(ge.truck_plate, "B 2 BB")
		self.assertNotEqual(str(ge.gate_in_timestamp)[:4], "2020")
		with self.assertRaisesRegex(frappe.ValidationError, "tidak boleh mengubah"):
			_revise(ge, gate_in_timestamp="2020-01-01 00:00:00")

	@patch("container_depot.container_depot.notify.notify", return_value=1)
	def test_request_and_reject_through_the_generic_flow(self, _notify):
		ge = self._gate()
		revision.request_generic("Gate Entry", ge.name, "plat salah")
		self.assertEqual(frappe.db.get_value("Gate Entry", ge.name, "revision_requested"), 1)
		self.assertEqual(revision.state(frappe.get_doc("Gate Entry", ge.name))["requested"], 1)
		self.assertEqual(_notify.call_args.kwargs["event_key"], "gate_revision_requested")

		revision.reject("Gate Entry", ge.name, "sudah benar")
		self.assertEqual(frappe.db.get_value("Gate Entry", ge.name, "revision_requested"), 0)
		self.assertEqual(_notify.call_args.kwargs["event_key"], "gate_revision_answered")
