"""Tests for TANK OUT — the departure, which is now the EIR-Out approval itself.

Submitting a clean EIR-Out is what declares a tank gone: ``Inspection.on_submit`` runs the
gate-out (Container -> Gate_Out, Movement + Activity, Gate Entry stamped, bon closed once its
last tank is out). There is no separate "ACC Keluar" step to test any more, so these cover the
consequence of that submit, its refusals (open work, a finding on the checklist) and its undo
(``eir.revert_to_draft``). Each test is self-contained; FrappeTestCase rolls back per test and
tearDown deletes any throwaway rows defensively.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.ess.inventory import derive_status
from container_depot.container_depot import eir
from container_depot.container_depot.eir import revert_to_draft
from container_depot.tests.test_api import ensure_test_customer
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


def _eir_out(container, *, damage=False):
	"""Submit an EIR-Out for the tank — the approval that gates it out when it is clean.

	``damage`` scores it ``Hold Pending Clearance`` instead, which must NOT release the tank.
	"""
	doc = frappe.new_doc("Inspection")
	doc.inspection_type = "EIR-Out"
	doc.container = container
	doc.inspector = frappe.session.user
	if damage:
		# Has Damage is derived from the log (Inspection.sync_has_damage) — the finding is
		# what makes the tank damaged, not the flag.
		masters = eir.get_eir_masters()
		doc.append("damage_log", {
			"component": "Frame",
			"damage_type": next(d["code"] for d in masters["damage_codes"] if d["code"] != "v"),
			"damage_description": "temuan saat load-out",
			"severity": "Minor",
		})
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


class TestGateOut(FrappeTestCase):
	def tearDown(self):
		frappe.db.delete("Container Activity", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Container Movement", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Gate Entry", {"container_no": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Inspection", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Container", {"name": ["like", f"{PREFIX}%"]})

	def test_a_clean_eir_out_takes_the_tank_out(self):
		c = _container(f"{PREFIX}9990001", "Available")
		eir = _eir_out(c)

		doc = frappe.get_doc("Container", c)
		self.assertEqual(doc.status, "Gate_Out")
		self.assertEqual(doc.inventory_stage, "Departed")
		# Live-inventory bucket drops to gate_out.
		self.assertEqual(derive_status(doc.status), "gate_out")

		# Container Movement auto-logged by Container.on_update.
		self.assertTrue(
			frappe.db.exists("Container Movement", {"container": c, "to_status": "Gate_Out"})
		)
		# Container Activity timeline row.
		self.assertTrue(
			frappe.db.exists("Container Activity", {"container": c, "activity_type": "Gate Out", "to_status": "Gate_Out"})
		)
		# Gate Entry stamped, and it points back at the EIR that released the tank.
		ge = frappe.db.get_value(
			"Gate Entry", {"container_no": c},
			["status", "gate_out_timestamp", "eir_reference"], as_dict=True,
		)
		self.assertEqual(ge.status, "Gate_Out_Completed")
		self.assertTrue(ge.gate_out_timestamp)
		self.assertEqual(ge.eir_reference, eir)

	def test_a_finding_holds_the_tank_in_the_depot(self):
		c = _container(f"{PREFIX}9990002", "Available")
		eir = _eir_out(c, damage=True)

		self.assertEqual(frappe.db.get_value("Inspection", eir, "out_outcome"), "Hold Pending Clearance")
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Available")
		self.assertFalse(frappe.db.exists("Container Movement", {"container": c, "to_status": "Gate_Out"}))

	def test_open_work_refuses_the_departure(self):
		"""The review must not sign a departure the yard cannot honour — a draft EIR-In is
		still open work, so submitting the EIR-Out throws instead of releasing the tank."""
		c = _container(f"{PREFIX}9990003", "In_Depot")
		draft = frappe.new_doc("Inspection")
		draft.inspection_type = "EIR-In"
		draft.container = c
		draft.inspector = frappe.session.user
		draft.insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			_eir_out(c)
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "In_Depot")
		self.assertFalse(frappe.db.exists("Container Movement", {"container": c, "to_status": "Gate_Out"}))

	def test_a_second_eir_out_on_a_departed_tank_is_a_no_op(self):
		c = _container(f"{PREFIX}9990004", "Available")
		_eir_out(c)
		_eir_out(c)  # must not raise, must not move anything
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Gate_Out")

	def test_reverting_the_eir_out_brings_the_tank_back(self):
		"""Undoing the approval is the only way to undo a departure — the tank returns to the
		status it left from and its Gate Entry reopens, so the corrected EIR-Out reuses it."""
		c = _container(f"{PREFIX}9990005", "Available")
		eir = _eir_out(c)
		ge = frappe.db.get_value("Gate Entry", {"container_no": c}, "name")

		revert_to_draft(eir)

		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Available")
		self.assertEqual(frappe.db.get_value("Inspection", eir, "docstatus"), 0)
		row = frappe.db.get_value(
			"Gate Entry", ge, ["status", "gate_out_timestamp", "eir_reference"], as_dict=True
		)
		self.assertNotEqual(row.status, "Gate_Out_Completed")
		self.assertFalse(row.gate_out_timestamp)
		self.assertFalse(row.eir_reference)


class TestBonCompletion(FrappeTestCase):
	"""The bon a departure closes — a load is only finished when its LAST tank is out."""

	def tearDown(self):
		frappe.db.delete("Container Activity", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Container Movement", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Gate Entry", {"container_no": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Inspection", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Order Container Item", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Container", {"name": ["like", f"{PREFIX}%"]})

	def test_the_bon_completes_once_its_last_tank_is_out(self):
		shipper = ensure_test_customer("Gate Out Test Principal")
		a = _container(f"{PREFIX}9991005", "Available")
		b = _container(f"{PREFIX}9991006", "Available")
		bon = frappe.get_doc({
			"doctype": "Order Muat", "shipper": shipper,
			"containers": [
				{"container": a, "container_no": a},
				{"container": b, "container_no": b},
			],
		})
		bon.flags.ignore_validate = True
		bon.insert(ignore_permissions=True, ignore_mandatory=True)
		frappe.db.set_value(
			"Order Muat", bon.name,
			{"docstatus": 1, "order_status": "Ready To Load"}, update_modified=False,
		)

		# First tank out — the bon still lists a tank standing in the yard.
		_eir_out(a)
		self.assertEqual(frappe.db.get_value("Order Muat", bon.name, "order_status"), "Ready To Load")

		# Last tank out — the bon is done.
		_eir_out(b)
		self.assertEqual(frappe.db.get_value("Order Muat", bon.name, "order_status"), "Completed")
		frappe.db.delete("Order Muat", {"name": bon.name})

	def test_a_bon_on_hold_is_never_auto_completed(self):
		shipper = ensure_test_customer("Gate Out Test Principal")
		c = _container(f"{PREFIX}9991007", "Available")
		bon = _make_order_muat(shipper, c)
		frappe.db.set_value("Order Muat", bon, "order_status", "Hold", update_modified=False)
		_eir_out(c)
		self.assertEqual(frappe.db.get_value("Order Muat", bon, "order_status"), "Hold")
		frappe.db.delete("Order Muat", {"name": bon})
