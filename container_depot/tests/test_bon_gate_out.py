"""The bon muat is the gate-out (user, 2026-10-08).

* The Order Muat submit sends every tank on it out, dated by Tanggal Muat; Kembalikan ke Draft
  brings them back.
* The EIR-Out and the Leak Check only record the tank's condition: finished before the bon or
  after the tank has left, they never hold or move it — no Hold, no Ready To Load on the bon.
* A Tank Out booking raises its EIR-Outs and its survey day at Confirm, not from the draft.
* Truck / driver stay in step across the booking line, the bon, the EIR-Out and the Gate Entry.

Self-cleaning through test_booking_bon_sync's ``_purge``.
"""

from __future__ import annotations

import frappe
from frappe.utils import today

from container_depot.container_depot import eir
from container_depot.container_depot.bon_revision import save_bon_revision
from container_depot.container_depot.doctype.container_booking.container_booking import revert_booking_to_draft
from container_depot.container_depot.order_generation import make_order, revert_order_to_draft
from container_depot.tests.test_booking_bon_sync import PREFIX, _Base
from container_depot.tests.test_eir import _make_container

TRUCK = {"truck_plate": "B 1001 AA", "driver": "Budi", "driver_name": "Budi", "driver_phone": "0811"}


class TestBonGateOut(_Base):
	def _out(self, **extra):
		tank = _make_container(f"{PREFIX}0000021", status="Available", principal=self.customer)
		b = self._booking("Tank Out", [{"container": tank}], use_survey=0, **extra)
		return b, tank

	def _eir_out(self, tank):
		return frappe.db.get_value("Inspection", {"container": tank, "inspection_type": "EIR-Out"}, "name")

	def _bon(self, b, day="2026-09-10"):
		return make_order(b.name, [b.items[0].booking_code], vehicle_data={**TRUCK, "tanggal_muat": day}, submit=True)

	def _gate(self):
		return frappe.db.get_value(
			"Gate Entry", {"container_no": f"{PREFIX}0000021"},
			["name", "status", "order_muat", "eir_reference", "truck_plate", "driver_name"], as_dict=True,
		)

	def test_a_draft_booking_raises_nothing_confirm_does_and_back_to_draft_withdraws(self):
		tank = _make_container(f"{PREFIX}0000021", status="Available", principal=self.customer)
		b = frappe.get_doc({
			"doctype": "Container Booking", "direction": "Tank Out", "customer": self.customer,
			"contract": self.contract, "do_reference": "DO-SYNC", "do_document": "/files/do.pdf",
			"plan_date": today(), "use_survey": 1, "survey_date": today(), "items": [{"container": tank}],
		}).insert(ignore_permissions=True)
		self.assertFalse(self._eir_out(tank))
		self.assertFalse(frappe.db.exists("Survey Order", {"booking": b.name}))

		b.submit()
		self.assertTrue(self._eir_out(tank))
		self.assertTrue(frappe.db.exists("Survey Order", {"booking": b.name, "docstatus": ["!=", 2]}))

		revert_booking_to_draft(b.name)
		self.assertFalse(self._eir_out(tank))

	def test_eir_out_first_then_the_bon_takes_the_tank_out(self):
		b, tank = self._out()
		name = self._eir_out(tank)
		frappe.get_doc("Inspection", name).submit()
		# Finished, yet the tank has not moved: only the bon sends it out.
		self.assertEqual(frappe.db.get_value("Container", tank, "status"), "Available")
		self.assertFalse(frappe.db.get_value("Inspection", name, "out_outcome"))

		bon = self._bon(b)
		self.assertEqual(frappe.db.get_value("Container", tank, "status"), "Gate_Out")
		self.assertEqual(str(frappe.db.get_value("Container", tank, "out_date")), "2026-09-10")
		self.assertEqual(frappe.db.get_value("Order Muat", bon, "order_status"), "Completed")
		# The finished EIR-Out was adopted by the bon, like a draft would be.
		row = frappe.db.get_value("Inspection", name, ["referred_voucher", "truck_no", "driver"], as_dict=True)
		self.assertEqual((row.referred_voucher, row.truck_no, row.driver), (bon, "B 1001 AA", "Budi"))
		ge = self._gate()
		self.assertEqual((ge.status, ge.order_muat, ge.eir_reference), ("Gate_Out_Completed", bon, name))

	def test_the_bon_first_and_the_eir_out_finished_after_the_tank_left(self):
		b, tank = self._out()
		bon = self._bon(b)
		self.assertEqual(frappe.db.get_value("Container", tank, "status"), "Gate_Out")

		name = self._eir_out(tank)
		self.assertIn(name, [i.name for i in eir.list_pending_eir_out(page_length=50)["items"]])
		frappe.get_doc("Inspection", name).submit()
		self.assertEqual(frappe.db.get_value("Container", tank, "status"), "Gate_Out")
		self.assertEqual(self._gate().eir_reference, name)

		# Reverting it does not bring the tank back — it never moved the tank.
		eir.revert_to_draft(name)
		self.assertEqual(frappe.db.get_value("Container", tank, "status"), "Gate_Out")
		self.assertFalse(self._gate().eir_reference)
		self.assertEqual(self._gate().status, "Gate_Out_Completed")

		revert_order_to_draft(bon, "Order Muat")
		self.assertEqual(frappe.db.get_value("Container", tank, "status"), "Available")
		self.assertEqual(self._gate().status, "Gate_In_Completed")

	def test_a_finding_on_the_eir_out_holds_nothing(self):
		b, tank = self._out()
		doc = frappe.get_doc("Inspection", self._eir_out(tank))
		masters = eir.get_eir_masters()
		doc.append("damage_log", {
			"component": "Frame",
			"damage_type": next(d["code"] for d in masters["damage_codes"] if d["code"] != "v"),
			"damage_description": "temuan saat load-out", "severity": "Minor",
		})
		doc.save(ignore_permissions=True)
		doc.submit()
		bon = self._bon(b)
		self.assertEqual(frappe.db.get_value("Container", tank, "status"), "Gate_Out")
		self.assertEqual(frappe.db.get_value("Order Muat", bon, "order_status"), "Completed")

	def test_no_leak_check_does_not_hold_the_bon(self):
		"""The Leak Check is like the EIR-Out: a condition record, never the gate."""
		tank = _make_container(f"{PREFIX}0000021", status="Available", principal=self.customer)
		b = self._booking("Tank Out", [{"container": tank}], use_survey=0)
		self._bon(b)
		self.assertEqual(frappe.db.get_value("Container", tank, "status"), "Gate_Out")

	def test_truck_and_driver_stay_in_step_everywhere(self):
		b, tank = self._out()
		name = self._eir_out(tank)
		frappe.get_doc("Inspection", name).submit()
		bon = self._bon(b)

		# Revisi Bon → booking line → bon, the SUBMITTED EIR-Out and the departure's gate log.
		line = frappe.db.get_value("Container Booking Item", {"parent": b.name}, "name")
		save_bon_revision("Order Muat", bon, lines=[{"name": line, "driver": "Citra", "truck_plate": "B 2002 BB"}])
		self.assertEqual(frappe.db.get_value("Inspection", name, ["truck_no", "driver"]), ("B 2002 BB", "Citra"))
		self.assertEqual((self._gate().truck_plate, self._gate().driver_name), ("B 2002 BB", "Citra"))

		# A correction on the gate log (a draft for the whole visit) → back to the booking line,
		# and on to the bon and the EIR-Out.
		ge = frappe.get_doc("Gate Entry", self._gate().name)
		ge.driver_name = "Dewi"
		ge.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Container Booking Item", line, "driver"), "Dewi")
		self.assertEqual(frappe.db.get_value("Order Muat", bon, "driver_name"), "Dewi")
		self.assertEqual(frappe.db.get_value("Inspection", name, "driver"), "Dewi")
