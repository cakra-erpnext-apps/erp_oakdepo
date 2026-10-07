"""Revisi Bon, 2026-10-07: every field of an issued bon, for as long as it exists, from the Gate
PWA or the Desk form — written where each field lives (booking line or bon) and copied back.

Self-cleaning through test_booking_bon_sync's ``_purge``.
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate

from container_depot.api import gate_lookup
from container_depot.container_depot.bon_revision import save_bon_revision
from container_depot.container_depot.order_generation import make_order
from container_depot.tests.test_booking_bon_sync import PREFIX, _Base
from container_depot.tests.test_eir import _make_container

TRUCK = {"truck_plate": "B 1001 AA", "driver": "Budi", "driver_phone": "0811"}


def _line(booking):
	return frappe.get_all(
		"Container Booking Item", filters={"parent": booking, "parenttype": "Container Booking"},
		fields=["name", "truck_plate", "condition"],
	)[0]


class TestBonRevision(_Base):
	def _tank_in_bon(self):
		b = self._booking("Tank In", [{"container_no": f"{PREFIX}0000001", "condition": "EMPTY CLEAN"}])
		bon = make_order(
			b.name, [b.items[0].booking_code],
			vehicle_data={**TRUCK, "tanggal_bongkar_actual": "2026-09-01"}, submit=True,
		)
		return b, bon, frappe.db.get_value("Container", {"container_no": f"{PREFIX}0000001"})

	def test_lines_go_to_the_booking_and_the_date_moves_the_day_in(self):
		b, bon, tank = self._tank_in_bon()
		line = _line(b.name)

		save_bon_revision(
			"Order Bongkar", bon,
			header={"tanggal_bongkar": "2026-08-30", "ex_vessel": "MV REVISI"},
			lines=[{"name": line.name, "truck_plate": "B 9 REV", "condition": "EMPTY DIRTY"}],
		)

		self.assertEqual(frappe.db.get_value("Container Booking Item", line.name, "truck_plate"), "B 9 REV")
		row = frappe.get_all("Container Booking Item", filters={"parent": bon, "parenttype": "Order Bongkar"},
			fields=["truck_plate", "condition"])[0]
		self.assertEqual((row.truck_plate, row.condition), ("B 9 REV", "EMPTY DIRTY"))
		self.assertEqual(frappe.db.get_value("Order Bongkar", bon, "ex_vessel"), "MV REVISI")
		self.assertEqual(getdate(frappe.db.get_value("Container", tank, "in_date")), getdate("2026-08-30"))
		self.assertTrue(frappe.db.exists("Comment", {"reference_doctype": "Order Bongkar", "reference_name": bon,
			"content": ["like", "%Revisi Bon%"]}))

	def test_a_completed_bon_is_still_revisable(self):
		tank = _make_container(f"{PREFIX}0000011", status="Available", principal=self.customer)
		b = self._booking("Tank Out", [{"container": tank, "condition": "LADEN", "use_eir": 0}], use_survey=0)
		bon = make_order(b.name, [b.items[0].booking_code], vehicle_data={**TRUCK, "tanggal_muat": "2026-09-10"}, submit=True)
		self.assertEqual(frappe.db.get_value("Order Muat", bon, "order_status"), "Completed")

		save_bon_revision(
			"Order Muat", bon, header={"tanggal_muat": "2026-09-12"},
			lines=[{"name": _line(b.name).name, "truck_plate": "B 7 OUT"}],
		)

		self.assertEqual(frappe.db.get_value("Order Muat", bon, "truck_plate"), "B 7 OUT")
		self.assertEqual(getdate(frappe.db.get_value("Container", tank, "out_date")), getdate("2026-09-12"))

	def test_the_date_is_locked_once_the_visit_storage_is_invoiced(self):
		_b, bon, tank = self._tank_in_bon()
		ge = frappe.db.get_value("Gate Entry", {"order_ref": bon}, "name")
		sc = frappe.db.get_value("Storage Charge", {"gate_entry": ge}, "name")
		frappe.db.set_value("Storage Charge", sc, "sales_invoice", "SINV-TEST-REVBON", update_modified=False)

		with self.assertRaisesRegex(frappe.ValidationError, "sudah masuk invoice"):
			save_bon_revision("Order Bongkar", bon, header={"tanggal_bongkar": "2026-08-25"})
		# ...but the rest of the bon stays correctable.
		save_bon_revision("Order Bongkar", bon, header={"ex_vessel": "MV SALAH KETIK"})
		self.assertEqual(frappe.db.get_value("Order Bongkar", bon, "ex_vessel"), "MV SALAH KETIK")

	def test_the_gate_finds_a_bonned_tank_by_its_number(self):
		b, bon, _tank = self._tank_in_bon()
		found = gate_lookup(f"{PREFIX}0000001")
		self.assertEqual(found.get("booking"), b.name)
		order = next(c["order"] for c in found["containers"] if c["container_no"] == f"{PREFIX}0000001")
		self.assertEqual(order["name"], bon)
