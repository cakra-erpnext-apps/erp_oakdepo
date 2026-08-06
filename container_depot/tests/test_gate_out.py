"""Tests for TANK OUT — the gate-out / load-complete action (PRO-OPS-009 §5.2 step 5).

Covers the happy path (Available -> Gate_Out with Movement + Activity +
Gate Entry stamping + inventory bucket), idempotency, the readiness guard, and the
Available source. Each test is self-contained; FrappeTestCase rolls back per test and
tearDown deletes any throwaway rows defensively (mark_gate_out never commits).
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.ess.inventory import derive_status
from container_depot.operations.gate import list_ready_to_load, mark_gate_out
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


def _clean_eir_out(container):
	"""Submit a clean EIR-Out so the container passes the gate-out readiness gate
	(Fase G: gate-out requires a submitted EIR-Out with out_outcome = Ready To Load)."""
	doc = frappe.new_doc("Inspection")
	doc.inspection_type = "EIR-Out"
	doc.container = container
	doc.inspector = frappe.session.user
	doc.insert(ignore_permissions=True)
	doc.submit()  # EIR-Out submit only stamps eir_out_date — container status is preserved.
	return doc.name


class TestGateOut(FrappeTestCase):
	def tearDown(self):
		frappe.db.delete("Container Activity", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Container Movement", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Gate Entry", {"container_no": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Inspection", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Container", {"name": ["like", f"{PREFIX}%"]})

	def test_gate_out_happy_path(self):
		c = _container(f"{PREFIX}9990001", "Available")
		_clean_eir_out(c)
		res = mark_gate_out(container=c)

		self.assertEqual(res["status"], "Gate_Out")
		self.assertEqual(res["container"], c)
		self.assertTrue(res["gate_entry"])
		self.assertTrue(res["gate_out_timestamp"])

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
		# Gate Entry stamped.
		ge = frappe.db.get_value(
			"Gate Entry", res["gate_entry"], ["status", "gate_out_timestamp"], as_dict=True
		)
		self.assertEqual(ge.status, "Gate_Out_Completed")
		self.assertTrue(ge.gate_out_timestamp)

	def test_gate_out_idempotent(self):
		c = _container(f"{PREFIX}9990002", "Gate_Out")
		res = mark_gate_out(container=c)
		self.assertEqual(res["status"], "Gate_Out")
		self.assertTrue(res.get("already"))
		# No state change, no error.
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Gate_Out")

	def test_gate_out_not_ready(self):
		c = _container(f"{PREFIX}9990003", "In_Depot")
		with self.assertRaises(frappe.ValidationError):
			mark_gate_out(container=c)
		# Nothing changed.
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "In_Depot")
		self.assertFalse(frappe.db.exists("Container Movement", {"container": c, "to_status": "Gate_Out"}))

	def test_gate_out_from_available(self):
		c = _container(f"{PREFIX}9990004", "Available")
		_clean_eir_out(c)
		res = mark_gate_out(container=c)
		self.assertEqual(res["status"], "Gate_Out")
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Gate_Out")


class TestReadyToLoadQueue(FrappeTestCase):
	"""The "Siap Keluar" reminder queue (PWA menu + Desk report) and the bon it closes."""

	def tearDown(self):
		frappe.db.delete("Container Activity", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Container Movement", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Gate Entry", {"container_no": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Inspection", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Order Container Item", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Container", {"name": ["like", f"{PREFIX}%"]})

	def _names(self):
		return [i["container"] for i in list_ready_to_load(page_length=100)["items"]]

	def test_clean_eir_out_puts_the_tank_in_the_queue(self):
		c = _container(f"{PREFIX}9991001", "Available")
		self.assertNotIn(c, self._names())
		_clean_eir_out(c)
		self.assertIn(c, self._names())

	def test_gate_out_clears_the_tank_from_the_queue(self):
		c = _container(f"{PREFIX}9991002", "Available")
		_clean_eir_out(c)
		mark_gate_out(container=c)
		self.assertNotIn(c, self._names())

	def test_queue_row_carries_the_bon_and_vehicle(self):
		shipper = ensure_test_customer("Gate Out Test Principal")
		c = _container(f"{PREFIX}9991003", "Available")
		bon = _make_order_muat(shipper, c, truck="B-7788-QQ", driver="Sopir Uji")
		eir = frappe.get_doc("Inspection", _clean_eir_out(c))
		frappe.db.set_value("Inspection", eir.name, "referred_voucher", bon, update_modified=False)

		row = next(i for i in list_ready_to_load(page_length=100)["items"] if i["container"] == c)
		self.assertEqual(row["order_muat"], bon)
		self.assertEqual(row["truck_no"], "B-7788-QQ")
		self.assertEqual(row["driver"], "Sopir Uji")
		self.assertTrue(row["ready_since"])

	def test_stale_eir_out_from_an_earlier_visit_is_not_queued(self):
		"""A tank that left and came back must not resurface on its OLD clean EIR-Out."""
		c = _container(f"{PREFIX}9991004", "Available")
		_clean_eir_out(c)
		mark_gate_out(container=c)
		# Comes back in: presence restored, but the EIR-Out predates the gate-out.
		frappe.db.set_value("Container", c, "status", "Available", update_modified=False)
		self.assertNotIn(c, self._names())

	def test_gate_out_completes_the_bon_once_its_last_tank_is_out(self):
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
		_clean_eir_out(a)
		_clean_eir_out(b)

		# First tank out — the bon still lists a tank standing in the yard.
		res = mark_gate_out(container=a)
		self.assertFalse(res["order_completed"])
		self.assertEqual(frappe.db.get_value("Order Muat", bon.name, "order_status"), "Ready To Load")

		# Last tank out — the bon is done.
		res = mark_gate_out(container=b)
		self.assertTrue(res["order_completed"])
		self.assertEqual(frappe.db.get_value("Order Muat", bon.name, "order_status"), "Completed")
		frappe.db.delete("Order Muat", {"name": bon.name})

	def test_bon_on_hold_is_never_auto_completed(self):
		shipper = ensure_test_customer("Gate Out Test Principal")
		c = _container(f"{PREFIX}9991007", "Available")
		bon = _make_order_muat(shipper, c)
		frappe.db.set_value("Order Muat", bon, "order_status", "Hold", update_modified=False)
		_clean_eir_out(c)
		mark_gate_out(container=c)
		self.assertEqual(frappe.db.get_value("Order Muat", bon, "order_status"), "Hold")
		frappe.db.delete("Order Muat", {"name": bon})
