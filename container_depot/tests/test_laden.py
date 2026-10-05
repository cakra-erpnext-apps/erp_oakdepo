"""LADEN tanks, 2026-10-05: no EIR, no Leak Check, no survey — the bon dates the visit.

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


class TestLadenIn(_Base):
	def _bon(self, conditions, day="2026-09-01"):
		b = self._booking("Tank In", [{"container_no": f"{PREFIX}{i:07d}"} for i in range(1, len(conditions) + 1)])
		codes = [r.booking_code for r in b.items]
		lines = {c: {"condition": cond} for c, cond in zip(codes, conditions)}
		bon = make_order(
			b.name, codes, vehicle_data={**TRUCK, "lines": lines, "tanggal_bongkar_actual": day}, submit=True
		)
		tanks = [frappe.db.get_value("Container", {"container_no": r.container_no}) for r in b.items]
		return bon, tanks

	def test_a_laden_tank_comes_in_on_its_bon_date_with_nothing_raised(self):
		bon, (laden, empty) = self._bon(["LADEN", "EMPTY CLEAN"])

		self.assertFalse(frappe.db.exists("Inspection", {"container": laden}))
		self.assertFalse(frappe.db.exists("Leak Check", {"container": laden}))
		self.assertEqual(frappe.db.get_value("Container", laden, "status"), "Available")
		self.assertEqual(_date(frappe.db.get_value("Container", laden, "eir_in_date")), "2026-09-01")
		self.assertEqual(_date(frappe.db.get_value("Gate Entry", {"order_ref": bon, "container_no": f"{PREFIX}0000001"}, "gate_in_timestamp")), "2026-09-01")
		self.assertEqual(_date(storage.stay_periods(laden)[-1]["start"]), "2026-09-01")
		# The empty tank beside it is inspected as before, and holds the bon open.
		self.assertTrue(frappe.db.exists("Inspection", {"container": empty, "inspection_type": "EIR-In"}))
		self.assertTrue(frappe.db.exists("Leak Check", {"container": empty}))
		self.assertEqual(frappe.db.get_value("Order Bongkar", bon, "order_status"), "Issued")

		doc = frappe.get_doc("Order Bongkar", bon)
		doc.tanggal_bongkar = "2026-09-03"
		doc.save()
		self.assertEqual(_date(frappe.db.get_value("Container", laden, "eir_in_date")), "2026-09-03")
		self.assertEqual(_date(storage.stay_periods(laden)[-1]["start"]), "2026-09-03")

	def test_an_all_laden_bon_is_done_at_issue_and_can_still_be_voided(self):
		bon, (laden,) = self._bon(["LADEN"])
		doc = frappe.get_doc("Order Bongkar", bon)
		self.assertEqual(doc.order_status, "Completed")
		self.assertTrue(order_undoable(doc))

		revert_order_to_draft(bon, "Order Bongkar")
		doc = frappe.get_doc("Order Bongkar", bon)
		doc.tanggal_bongkar = "2026-09-02"
		doc.save()
		doc.submit()  # the corrected date reaches the arrival
		self.assertEqual(_date(frappe.db.get_value("Container", laden, "eir_in_date")), "2026-09-02")

		revert_order_to_draft(bon, "Order Bongkar")
		void_order(bon, "Order Bongkar")
		self.assertNotIn(frappe.db.get_value("Container", laden, "status"), ("Available", "In_Depot"))


class TestLadenOut(_Base):
	def _bon(self, day="2026-09-10"):
		tank = _make_container(f"{PREFIX}0000011", status="Available", principal=self.customer)
		b = self._booking(
			"Tank Out", [{"container": tank, "condition": "LADEN"}], use_survey=1, survey_date="2026-09-09"
		)
		self.assertFalse(frappe.db.exists("Inspection", {"container": tank}))
		self.assertFalse(frappe.db.exists("Survey Order", {"booking": b.name, "docstatus": ["!=", 2]}))
		bon = make_order(b.name, [b.items[0].booking_code], vehicle_data={**TRUCK, "tanggal_muat": day}, submit=True)
		return bon, tank

	def _gate_out(self, tank):
		return frappe.db.get_value(
			"Gate Entry", {"container_no": f"{PREFIX}0000011"}, ["status", "gate_out_timestamp"], as_dict=True
		)

	def test_a_laden_tank_leaves_on_its_bon_date(self):
		bon, tank = self._bon()
		self.assertEqual(frappe.db.get_value("Container", tank, "status"), "Gate_Out")
		self.assertEqual(_date(frappe.db.get_value("Container", tank, "eir_out_date")), "2026-09-10")
		self.assertEqual(_date(self._gate_out(tank).gate_out_timestamp), "2026-09-10")
		self.assertEqual(frappe.db.get_value("Order Muat", bon, "order_status"), "Completed")

		doc = frappe.get_doc("Order Muat", bon)
		doc.tanggal_muat = "2026-09-12"
		doc.save()
		self.assertEqual(_date(frappe.db.get_value("Container", tank, "eir_out_date")), "2026-09-12")
		self.assertEqual(_date(self._gate_out(tank).gate_out_timestamp), "2026-09-12")

	def test_back_to_draft_brings_the_tank_back(self):
		bon, tank = self._bon()
		self.assertTrue(order_undoable(frappe.get_doc("Order Muat", bon)))

		revert_order_to_draft(bon, "Order Muat")
		self.assertEqual(frappe.db.get_value("Container", tank, "status"), "Available")
		ge = self._gate_out(tank)
		self.assertEqual((ge.status, ge.gate_out_timestamp), ("Gate_In_Completed", None))

		frappe.get_doc("Order Muat", bon).submit()  # out again on re-submit
		self.assertEqual(frappe.db.get_value("Container", tank, "status"), "Gate_Out")
