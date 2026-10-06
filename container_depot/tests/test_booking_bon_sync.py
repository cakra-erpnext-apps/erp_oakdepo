"""Booking line <-> bon, 2026-10-02.

* The bon is a copy of its booking lines (2026-10-05): a line edited after Submit reaches the
  bon, the draft EIR and the open gate log; whatever is typed on the bon itself is overwritten
  by the line on save.
* The booking's per-tank panel lists the bons it raised, in its own direction.

Self-cleaning: every row created here is hard-deleted in tearDown.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from container_depot.container_depot.doctype.container_booking.container_booking import (
	orders_by_container,
	related_orders,
	remove_tank,
)
from container_depot.container_depot.order_generation import (
	make_order,
	revert_order_to_draft,
	void_order,
)
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_container_booking import _make_active_contract
from container_depot.tests.test_eir import _make_container

CUSTOMER = "Bon Sync Test Customer"
PREFIX = "BSYU"
VEHICLE = {"truck_plate": "B 1001 AA", "driver": "Budi", "driver_phone": "0811", "condition": "EMPTY CLEAN"}


def _purge():
	bookings = frappe.get_all("Container Booking", filters={"customer": CUSTOMER}, pluck="name") or [""]
	containers = frappe.get_all("Container", filters={"container_no": ["like", f"{PREFIX}%"]}, pluck="name") or [""]
	bons = {
		dt: frappe.get_all(dt, filters={"booking": ["in", bookings]}, pluck="name") or [""]
		for dt in ("Order Bongkar", "Order Muat")
	}
	inspections = frappe.get_all("Inspection", filters={"container": ["in", containers]}, pluck="name") or [""]
	leaks = frappe.get_all("Leak Check", filters={"container": ["in", containers]}, pluck="name") or [""]
	surveys = frappe.get_all("Survey Order", filters={"booking": ["in", bookings]}, pluck="name") or [""]
	for dt, names in (
		("Container Booking", bookings), ("Inspection", inspections), ("Leak Check", leaks),
		("Survey Order", surveys), *bons.items(),
	):
		frappe.db.delete("Notification Log", {"document_type": dt, "document_name": ["in", names]})
		frappe.db.delete("Comment", {"reference_doctype": dt, "reference_name": ["in", names]})
	frappe.db.delete("Container Booking Item", {"parent": ["in", bons["Order Bongkar"]]})
	frappe.db.delete("Order Container Item", {"parent": ["in", bons["Order Muat"]]})
	for dt, names in bons.items():
		frappe.db.delete(dt, {"name": ["in", names]})
	frappe.db.delete("Leak Check Photo", {"parent": ["in", leaks]})
	frappe.db.delete("Survey Order Tank", {"parent": ["in", surveys]})
	frappe.db.delete("Survey Order", {"name": ["in", surveys]})
	frappe.db.delete("Booking Code", {"booking": ["in", bookings]})
	frappe.db.delete("Container Booking Item", {"parent": ["in", bookings]})
	frappe.db.delete("Container Booking", {"name": ["in", bookings]})
	for dt in ("Inspection", "Leak Check", "Cleaning Order", "Repair Order", "Container Activity",
			   "Container Movement", "Storage Charge", "Container Position"):
		frappe.db.delete(dt, {"container": ["in", containers]})
	frappe.db.delete("Gate Entry", {"container_no": ["like", f"{PREFIX}%"]})
	frappe.db.delete("Container", {"name": ["in", containers]})
	frappe.db.delete("Tariff Rate", {"parent": ["in", frappe.get_all(
		"Depot Contract", filters={"customer": CUSTOMER}, pluck="name") or [""]]})
	frappe.db.delete("Depot Contract", {"customer": CUSTOMER})
	frappe.db.commit()


class _Base(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		_purge()
		self.customer = ensure_test_customer(CUSTOMER)
		self.contract = _make_active_contract(self.customer, payment_type="TOP", credit_limit=1, payment_terms="NET 30")

	def tearDown(self):
		frappe.set_user("Administrator")
		_purge()
		super().tearDown()

	def _booking(self, direction, items, **extra):
		b = frappe.get_doc({
			"doctype": "Container Booking", "direction": direction, "customer": self.customer,
			"contract": self.contract, "do_reference": "DO-SYNC", "do_document": "/files/do.pdf",
			"plan_date": today(), "items": items, **extra,
		})
		b.insert(ignore_permissions=True)
		b.submit()
		b.reload()
		return b

	def _tank_in(self, n=1):
		return self._booking("Tank In", [{"container_no": f"{PREFIX}{i:07d}"} for i in range(1, n + 1)])

	def _tank_out(self, n=1):
		tanks = [
			_make_container(f"{PREFIX}{i:07d}", status="Available", principal=self.customer)
			for i in range(11, 11 + n)
		]
		return self._booking("Tank Out", [{"container": t} for t in tanks], use_survey=0)

	def _bon_row(self, bon, doctype="Order Bongkar"):
		child = "Container Booking Item" if doctype == "Order Bongkar" else "Order Container Item"
		return frappe.get_all(child, filters={"parent": bon, "parenttype": doctype}, fields=["*"])[0]

	def _eir(self, bon):
		return frappe.db.get_value("Inspection", {"referred_voucher": bon, "docstatus": 0}, ["name", "driver"], as_dict=True)


class TestLineSync(_Base):
	def test_the_line_is_dated_by_the_live_bon_not_the_voided_one(self):
		b = self._tank_in()
		code = b.items[0].booking_code
		bon = make_order(b.name, [code], vehicle_data={**VEHICLE, "tanggal_bongkar_actual": "2026-09-01"}, submit=True)
		revert_order_to_draft(bon, "Order Bongkar")
		void_order(bon, "Order Bongkar")
		make_order(b.name, [code], vehicle_data={**VEHICLE, "tanggal_bongkar_actual": "2026-09-05"}, submit=True)
		self.assertEqual(
			str(frappe.db.get_value("Container Booking Item", b.items[0].name, "realisation_date")), "2026-09-05"
		)

	def test_a_booking_line_edit_reaches_the_bon_the_eir_and_the_gate_log(self):
		b = self._tank_in()
		bon = make_order(b.name, [b.items[0].booking_code], vehicle_data=VEHICLE, submit=True)
		b.reload()
		b.items[0].driver = "Citra"
		b.items[0].truck_plate = "B 2002 BB"
		b.save()

		row = self._bon_row(bon)
		self.assertEqual((row.driver, row.truck_plate), ("Citra", "B 2002 BB"))
		self.assertEqual(self._eir(bon).driver, "Citra")
		self.assertEqual(frappe.db.get_value("Gate Entry", {"order_ref": bon}, "driver_name"), "Citra")

	def test_anything_else_on_a_submitted_booking_stays_locked(self):
		b = self._tank_in()
		b.remarks = "diubah"
		with self.assertRaisesRegex(frappe.ValidationError, "yang masih bisa diubah"):
			b.save()

	def test_condition_and_cargo_follow_like_the_truck(self):
		# Booked EMPTY CLEAN, found LADEN at the bon (user, 2026-10-05): corrected on the booking.
		b = self._tank_in()
		bon = make_order(b.name, [b.items[0].booking_code], vehicle_data=VEHICLE, submit=True)
		eir = self._eir(bon).name
		b.reload()
		b.items[0].condition = "LADEN"
		b.items[0].emkl = self.customer
		b.save()
		self.assertEqual(self._bon_row(bon).condition, "LADEN")
		self.assertEqual(frappe.db.get_value("Order Bongkar", bon, "emkl"), self.customer)
		self.assertEqual(frappe.db.get_value("Inspection", eir, "tank_status"), "Laden")

	def test_a_line_on_a_closed_bon_is_history(self):
		b = self._tank_in()
		bon = make_order(b.name, [b.items[0].booking_code], vehicle_data=VEHICLE, submit=True)
		frappe.db.set_value("Order Bongkar", bon, "order_status", "Completed")
		b.reload()
		b.items[0].driver = "Citra"
		with self.assertRaisesRegex(frappe.ValidationError, "sudah selesai di bon"):
			b.save()

	def test_the_bon_is_a_copy_of_the_line(self):
		b = self._tank_in()
		bon = make_order(b.name, [b.items[0].booking_code], vehicle_data=VEHICLE, submit=True)
		b.reload()
		self.assertEqual(b.items[0].driver, "Budi")  # Generate wrote it onto the line

		revert_order_to_draft(bon, "Order Bongkar")
		doc = frappe.get_doc("Order Bongkar", bon)
		doc.containers[0].driver = "Dodi"
		doc.containers[0].condition = "LADEN"
		doc.save()
		self.assertEqual((doc.containers[0].driver, doc.containers[0].condition), ("Budi", "EMPTY CLEAN"))
		self.assertEqual(frappe.db.get_value("Container Booking Item", b.items[0].name, "driver"), "Budi")

	def test_the_muat_header_is_shared_by_every_tank_on_it(self):
		b = self._tank_out(2)
		codes = [r.booking_code for r in b.items]
		# The Desk dialog asks `driver`, the Muat header keeps it as `driver_name`.
		bon = make_order(b.name, codes, vehicle_data={**VEHICLE, "driver_name": "Eko"}, submit=True)
		b.reload()
		self.assertEqual([r.driver for r in b.items], ["Eko", "Eko"])

		b.items[0].driver = "Fajar"
		b.save()
		self.assertEqual(frappe.db.get_value("Order Muat", bon, "driver_name"), "Fajar")
		self.assertEqual(
			frappe.db.get_value("Container Booking Item", b.items[1].name, "driver"), "Fajar"
		)
		eir = frappe.db.get_value("Inspection", {"referred_voucher": bon, "container": b.items[1].container}, "driver")
		self.assertEqual(eir, "Fajar")


class TestRemoveTank(_Base):
	def test_only_the_administrator_takes_a_wrong_tank_off_a_frozen_booking(self):
		b = self._tank_in(2)
		first, second = b.items
		bon = make_order(b.name, [first.booking_code], vehicle_data=VEHICLE, submit=True)
		revert_order_to_draft(bon, "Order Bongkar")
		void_order(bon, "Order Bongkar")  # the booking stays frozen: a bon was raised
		make_order(b.name, [second.booking_code], vehicle_data=VEHICLE, submit=True)

		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			remove_tank(b.name, first.name)
		frappe.set_user("Administrator")
		with self.assertRaisesRegex(frappe.ValidationError, "masih di bon"):
			remove_tank(b.name, second.name)

		self.assertEqual(remove_tank(b.name, first.name), first.container_no)
		b.reload()
		self.assertEqual([r.container_no for r in b.items], [second.container_no])
		self.assertEqual(b.container_summary, second.container_no)
		# The master this booking minted for the wrong number goes with it.
		self.assertFalse(frappe.db.exists("Container", first.container))
		self.assertEqual(frappe.db.get_value("Container", second.container, "status"), "In_Depot")
		with self.assertRaisesRegex(frappe.ValidationError, "satu-satunya"):
			remove_tank(b.name, second.name)


	def test_no_tank_is_left_in_a_wrong_status(self):
		# A tank already on file, booked in by mistake: back out to where it came from.
		known = _make_container(f"{PREFIX}0000031", status="Gate_Out", principal=self.customer)
		b = self._booking("Tank In", [{"container": known}, {"container_no": f"{PREFIX}0000032"}])
		self.assertEqual(frappe.db.get_value("Container", known, "status"), "Booked")
		phantom = b.items[1].container
		remove_tank(b.name, b.items[0].name)
		self.assertEqual(frappe.db.get_value("Container", known, "status"), "Gate_Out")
		self.assertEqual(frappe.db.get_value("Container", phantom, "status"), "Booked")

		# A phantom a pickup is already booked on (draft Tank Out) is kept, out of the yard.
		b2 = self._booking("Tank In", [{"container_no": f"{PREFIX}0000033"}, {"container_no": f"{PREFIX}0000034"}])
		held = b2.items[0].container
		frappe.get_doc({
			"doctype": "Container Booking", "direction": "Tank Out", "customer": self.customer,
			"contract": self.contract, "plan_date": today(), "items": [{"container": held}],
		}).insert(ignore_permissions=True)
		remove_tank(b2.name, b2.items[0].name)
		self.assertEqual(frappe.db.get_value("Container", held, "status"), "Gate_Out")

		# Tank Out: the tank is in the yard and stays exactly as it was.
		out = self._tank_out(2)
		remove_tank(out.name, out.items[0].name)
		self.assertEqual(frappe.db.get_value("Container", out.items[0].container, "status"), "Available")
		self.assertFalse(frappe.db.exists(
			"Inspection", {"container": out.items[0].container, "inspection_type": "EIR-Out", "docstatus": 0}
		))


class TestPanelBons(_Base):
	def test_each_panel_lists_the_bons_of_its_own_booking(self):
		b = self._tank_in()
		bon = make_order(b.name, [b.items[0].booking_code], vehicle_data=VEHICLE, submit=True)
		lines = orders_by_container(b.name)[0]["orders"]
		self.assertIn(("Order Bongkar", bon, "Bon Bongkar"), [(o["doctype"], o["name"], o["label"]) for o in lines])

		out = self._tank_out()
		muat = make_order(out.name, [out.items[0].booking_code], vehicle_data=VEHICLE, submit=True)
		docs = related_orders(out.name)[0]["orders"]
		self.assertIn(("Order Muat", muat, "Bon Muat"), [(o["doctype"], o["name"], o["kind"]) for o in docs])
		self.assertNotIn("Order Bongkar", [o["doctype"] for o in docs])
