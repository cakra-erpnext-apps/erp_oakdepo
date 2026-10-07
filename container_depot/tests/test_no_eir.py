"""LADEN tanks taken without an EIR ("Pakai EIR" off), 2026-10-07: no EIR, no Leak Check, no
survey — the bon is the visit, dated by Tanggal Bongkar / Tanggal Muat.

Self-cleaning through test_booking_bon_sync's ``_purge``.
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate

from container_depot import storage
from container_depot.container_depot.order_generation import (
	make_order,
	order_undoable,
	revert_order_to_draft,
	void_order,
)
from container_depot.tests.test_booking_bon_sync import PREFIX, _Base
from container_depot.tests.test_eir import _make_container

TRUCK = {"truck_plate": "B 1001 AA", "driver": "Budi", "driver_phone": "0811"}


def _date(value):
	return str(getdate(value)) if value else None


class TestNoEirIn(_Base):
	def _bon(self, lines, day="2026-09-01"):
		"""``lines`` = [(condition, use_eir)], one tank each."""
		b = self._booking("Tank In", [
			{"container_no": f"{PREFIX}{i:07d}", "condition": cond, "use_eir": use}
			for i, (cond, use) in enumerate(lines, 1)
		])
		codes = [r.booking_code for r in b.items]
		bon = make_order(b.name, codes, vehicle_data={**TRUCK, "tanggal_bongkar_actual": day}, submit=True)
		tanks = [frappe.db.get_value("Container", {"container_no": r.container_no}) for r in b.items]
		return b, bon, tanks

	def test_a_tank_without_eir_comes_in_on_its_bon_date_with_nothing_raised(self):
		b, bon, (bare, empty) = self._bon([("LADEN", 0), ("EMPTY CLEAN", 0)])
		# The switch means nothing on an EMPTY line: it is put back on.
		self.assertEqual(b.items[1].use_eir, 1)

		self.assertFalse(frappe.db.exists("Inspection", {"container": bare}))
		self.assertFalse(frappe.db.exists("Leak Check", {"container": bare}))
		self.assertEqual(frappe.db.get_value("Container", bare, "status"), "Available")
		self.assertEqual(_date(frappe.db.get_value("Container", bare, "in_date")), "2026-09-01")
		self.assertEqual(_date(storage.stay_periods(bare)[-1]["start"]), "2026-09-01")
		# The EMPTY tank beside it is inspected as before, and holds the bon open.
		self.assertTrue(frappe.db.exists("Inspection", {"container": empty, "inspection_type": "EIR-In"}))
		self.assertTrue(frappe.db.exists("Leak Check", {"container": empty}))
		self.assertEqual(frappe.db.get_value("Order Bongkar", bon, "order_status"), "Issued")

		doc = frappe.get_doc("Order Bongkar", bon)
		doc.tanggal_bongkar = "2026-09-03"
		doc.save()
		self.assertEqual(_date(frappe.db.get_value("Container", bare, "in_date")), "2026-09-03")
		self.assertEqual(_date(storage.stay_periods(bare)[-1]["start"]), "2026-09-03")

	def test_a_bon_of_only_bare_tanks_is_done_at_issue_and_can_still_be_voided(self):
		_b, bon, (bare,) = self._bon([("LADEN", 0)])
		doc = frappe.get_doc("Order Bongkar", bon)
		self.assertEqual(doc.order_status, "Completed")
		self.assertTrue(order_undoable(doc))

		revert_order_to_draft(bon, "Order Bongkar")
		void_order(bon, "Order Bongkar")
		self.assertNotIn(frappe.db.get_value("Container", bare, "status"), ("Available", "In_Depot"))

	def test_laden_takes_an_eir_unless_switched_off(self):
		_b, bon, (laden,) = self._bon([("LADEN", 1)])
		self.assertTrue(frappe.db.exists("Inspection", {"container": laden, "inspection_type": "EIR-In"}))
		self.assertEqual(frappe.db.get_value("Order Bongkar", bon, "order_status"), "Issued")

	def test_the_switch_is_locked_once_the_tank_is_on_a_bon(self):
		b, _bon, _tanks = self._bon([("LADEN", 0)])
		b.items[0].use_eir = 1
		with self.assertRaisesRegex(frappe.ValidationError, "Pakai EIR"):
			b.save()


class TestNoEirOut(_Base):
	def _bon(self, day="2026-09-10"):
		tank = _make_container(f"{PREFIX}0000011", status="Available", principal=self.customer)
		b = self._booking(
			"Tank Out", [{"container": tank, "condition": "LADEN", "use_eir": 0}],
			use_survey=1, survey_date="2026-09-09",
		)
		self.assertFalse(frappe.db.exists("Inspection", {"container": tank}))
		self.assertFalse(frappe.db.exists("Survey Order", {"booking": b.name, "docstatus": ["!=", 2]}))
		bon = make_order(b.name, [b.items[0].booking_code], vehicle_data={**TRUCK, "tanggal_muat": day}, submit=True)
		return bon, tank

	def _gate(self):
		return frappe.db.get_value(
			"Gate Entry", {"container_no": f"{PREFIX}0000011"},
			["status", "gate_out_timestamp", "out_date", "order_muat"], as_dict=True,
		)

	def test_the_bon_is_the_gate_out_dated_by_tanggal_muat(self):
		bon, tank = self._bon()
		self.assertEqual(frappe.db.get_value("Container", tank, "status"), "Gate_Out")
		self.assertEqual(_date(frappe.db.get_value("Container", tank, "out_date")), "2026-09-10")
		self.assertEqual((_date(self._gate().out_date), self._gate().order_muat), ("2026-09-10", bon))
		self.assertEqual(frappe.db.get_value("Order Muat", bon, "order_status"), "Completed")

		doc = frappe.get_doc("Order Muat", bon)
		doc.tanggal_muat = "2026-09-12"
		doc.save()
		self.assertEqual(_date(frappe.db.get_value("Container", tank, "out_date")), "2026-09-12")
		self.assertEqual(_date(self._gate().out_date), "2026-09-12")

	def test_back_to_draft_brings_the_tank_back(self):
		bon, tank = self._bon()
		self.assertTrue(order_undoable(frappe.get_doc("Order Muat", bon)))

		revert_order_to_draft(bon, "Order Muat")
		self.assertEqual(frappe.db.get_value("Container", tank, "status"), "Available")
		self.assertIsNone(frappe.db.get_value("Container", tank, "out_date"))
		ge = self._gate()
		self.assertEqual((ge.status, ge.gate_out_timestamp, ge.out_date), ("Gate_In_Completed", None, None))

		frappe.get_doc("Order Muat", bon).submit()  # out again on re-submit
		self.assertEqual(frappe.db.get_value("Container", tank, "status"), "Gate_Out")
