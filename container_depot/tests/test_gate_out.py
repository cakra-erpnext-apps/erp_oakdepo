"""Tests for TANK OUT — the departure, which is the bon muat's submit (user, 2026-10-08).

Submitting an Order Muat is what declares its tanks gone (``gate.depart_bon``): Container ->
Gate_Out, Movement + Activity, Gate Entry stamped, bon Completed. The EIR-Out only records the
tank's condition and does not gate it (see test_bon_gate_out for the full booking -> bon flow).
These cover the departure itself, its refusals (open work, no Leak Check this visit) and its
undo (``gate.reverse_bon_departures``). The bons here are raw-submitted (``_make_order_muat``),
so the departure is driven by hand exactly as ``OrderMuat.on_submit`` does it.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.ess.inventory import derive_status
from container_depot.container_depot.gate import depart_bon, reverse_bon_departures
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests._leak_check import drop_leak_checks, make_leak_check
from container_depot.tests.test_eir import _make_order_muat

PREFIX = "GOTU"


def _container(no, status):
	frappe.get_doc({
		"doctype": "Container",
		"container_no": no,
		"container_type": "ISO Tank",
		"status": status,
		"principal": ensure_test_customer("Gate Out Test Principal"),
	}).insert(ignore_permissions=True)
	return no


def _depart(*containers, leak_check=True):
	"""A submitted bon carrying ``containers``, and its departure (``OrderMuat.on_submit``)."""
	shipper = ensure_test_customer("Gate Out Test Principal")
	bon = frappe.get_doc({
		"doctype": "Order Muat", "emkl": shipper,
		"containers": [{"container": c, "container_no": c} for c in containers],
	})
	bon.flags.ignore_validate = True
	bon.insert(ignore_permissions=True, ignore_mandatory=True)
	frappe.db.set_value("Order Muat", bon.name, "docstatus", 1, update_modified=False)
	if leak_check:
		for c in containers:
			make_leak_check(c)
	doc = frappe.get_doc("Order Muat", bon.name)
	depart_bon(doc)
	return doc


def _eir_out(container, *, leak_check=True):
	"""A tank's whole Tank Out for suites that only need it gone: its EIR-Out recorded, then
	its bon sends it out. Returns the EIR-Out."""
	doc = frappe.new_doc("Inspection")
	doc.inspection_type = "EIR-Out"
	doc.container = container
	doc.inspector = frappe.session.user
	doc.insert(ignore_permissions=True)
	doc.submit()
	_depart(container, leak_check=leak_check)
	return doc.name


class TestGateOut(FrappeTestCase):
	def tearDown(self):
		frappe.db.delete("Container Activity", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Container Movement", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Gate Entry", {"container_no": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Inspection", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Order Container Item", {"container": ["like", f"{PREFIX}%"]})
		drop_leak_checks(["like", f"{PREFIX}%"])
		frappe.db.delete("Container", {"name": ["like", f"{PREFIX}%"]})

	def test_the_bon_takes_the_tank_out(self):
		c = _container(f"{PREFIX}9990001", "Available")
		bon = _depart(c)

		doc = frappe.get_doc("Container", c)
		self.assertEqual(doc.status, "Gate_Out")
		self.assertEqual(doc.inventory_stage, "Departed")
		self.assertEqual(derive_status(doc.status), "gate_out")
		self.assertTrue(
			frappe.db.exists("Container Movement", {"container": c, "to_status": "Gate_Out"})
		)
		self.assertTrue(
			frappe.db.exists("Container Activity", {"container": c, "activity_type": "Gate Out", "to_status": "Gate_Out"})
		)
		ge = frappe.db.get_value(
			"Gate Entry", {"container_no": c}, ["status", "gate_out_timestamp", "order_muat"], as_dict=True,
		)
		self.assertEqual((ge.status, ge.order_muat), ("Gate_Out_Completed", bon.name))
		self.assertTrue(ge.gate_out_timestamp)
		self.assertEqual(frappe.db.get_value("Order Muat", bon.name, "order_status"), "Completed")
		frappe.db.delete("Order Muat", {"name": bon.name})

	def test_open_work_refuses_the_departure(self):
		"""A draft EIR-In is still open work, so the bon cannot send the tank out."""
		c = _container(f"{PREFIX}9990003", "In_Depot")
		draft = frappe.new_doc("Inspection")
		draft.inspection_type = "EIR-In"
		draft.container = c
		draft.inspector = frappe.session.user
		draft.insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			_depart(c)
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "In_Depot")
		self.assertFalse(frappe.db.exists("Container Movement", {"container": c, "to_status": "Gate_Out"}))

	def test_the_leak_check_holds_nothing_and_can_follow_the_departure(self):
		"""Same as the EIR-Out (user, 2026-10-08): a condition record, not a gate. The bon sends
		the tank out without one, and the open one is still finished afterwards."""
		c = _container(f"{PREFIX}9990009", "Available")
		pending = frappe.get_doc({
			"doctype": "Leak Check", "container": c, "photos": [{"photo": "/files/leak-test.jpg", "is_leak": 1}],
		}).insert(ignore_permissions=True)

		_depart(c, leak_check=False)
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Gate_Out")

		pending.reload()
		pending.submit()
		self.assertEqual(frappe.db.get_value("Leak Check", pending.name, ["status", "has_leak"]), ("Completed", 1))

	def test_leak_check_needs_a_photo(self):
		c = _container(f"{PREFIX}9990010", "Available")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Leak Check", "container": c, "photos": []}).insert(ignore_permissions=True)

	def test_a_second_departure_of_a_departed_tank_is_a_no_op(self):
		c = _container(f"{PREFIX}9990004", "Available")
		bon = _depart(c)
		depart_bon(bon)  # must not raise, must not move anything
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Gate_Out")

	def test_undoing_the_bon_brings_every_tank_back(self):
		a = _container(f"{PREFIX}9990005", "Available")
		b = _container(f"{PREFIX}9990006", "Available")
		bon = _depart(a, b)
		self.assertEqual(frappe.db.get_value("Order Muat", bon.name, "order_status"), "Completed")

		self.assertEqual(sorted(reverse_bon_departures(bon)), sorted([a, b]))
		for c in (a, b):
			self.assertEqual(frappe.db.get_value("Container", c, "status"), "Available")
			row = frappe.db.get_value("Gate Entry", {"container_no": c}, ["status", "gate_out_timestamp"], as_dict=True)
			self.assertNotEqual(row.status, "Gate_Out_Completed")
			self.assertFalse(row.gate_out_timestamp)
		frappe.db.delete("Order Muat", {"name": bon.name})
