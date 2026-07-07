"""Tests for TANK OUT — the gate-out / load-complete action (PRO-OPS-009 §5.2 step 5).

Covers the happy path (Available -> Gate_Out with Movement + Activity +
Gate Entry stamping + inventory bucket), idempotency, the readiness guard, and the
Available source. Each test is self-contained; FrappeTestCase rolls back per test and
tearDown deletes any throwaway rows defensively (mark_gate_out never commits).
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot.ess.inventory import derive_status
from container_depot.operations.gate import mark_gate_out
from container_depot.tests.test_api import ensure_test_customer

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
	cert = frappe.get_doc({
		"doctype": "Cleaning Certificate", "container": container,
		"clean_date": today(), "valid_until": add_days(today(), 20),
	}).insert(ignore_permissions=True, ignore_mandatory=True)
	frappe.db.set_value("Cleaning Certificate", cert.name, "docstatus", 1, update_modified=False)
	doc = frappe.new_doc("Inspection")
	doc.inspection_type = "EIR-Out"
	doc.container = container
	doc.inspector = frappe.session.user
	doc.exterior_condition = "Clean"
	doc.seals_intact = 1
	doc.cleaning_cert = cert.name
	doc.cleaning_cert_valid_until = add_days(today(), 20)
	doc.insert(ignore_permissions=True)
	doc.submit()  # EIR-Out submit only stamps eir_out_date — container status is preserved.
	return doc.name


class TestGateOut(FrappeTestCase):
	def tearDown(self):
		frappe.db.delete("Container Activity", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Container Movement", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Gate Entry", {"container_no": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Inspection", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Cleaning Certificate", {"container": ["like", f"{PREFIX}%"]})
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
