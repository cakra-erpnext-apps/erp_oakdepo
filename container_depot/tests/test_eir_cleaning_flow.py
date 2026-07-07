"""Wiring: an Empty-Dirty EIR-In auto-creates a Pending Cleaning Order (so the
cleaning team is notified) and queues the container for cleaning. A clean tank does
not. Idempotent — re-submitting does not duplicate the open order.

EIR submit drives the container + creates a Cleaning Order, so created docs are
removed explicitly after each test.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.operations import eir
from container_depot.tests.test_eir import _make_container


class TestEirCleaningFlow(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._containers = []
		self._inspections = []

	def tearDown(self):
		for c in self._containers:
			frappe.db.delete("Notification Log", {"document_type": "Cleaning Order", "document_name": ["like", "%"]})
			frappe.db.delete("Cleaning Order", {"container": c})
			frappe.db.delete("Container Activity", {"container": c})
			frappe.db.delete("Container", {"name": c})
		for ins in self._inspections:
			frappe.db.delete("Inspection", {"name": ins})
		frappe.db.commit()
		super().tearDown()

	def _eir_in(self, cno, *, tank_status):
		c = _make_container(cno)
		self._containers.append(c)
		res = eir.create_eir(inspection_type="EIR-In", container=c, tank_status=tank_status, submit=True)
		self._inspections.append(res["name"])
		return c, res["name"]

	def test_empty_dirty_eir_creates_pending_cleaning_order(self):
		c, eir_name = self._eir_in("DIRTYEIR001", tank_status="Empty Dirty")
		orders = frappe.get_all(
			"Cleaning Order", filters={"container": c}, fields=["name", "status", "inspection"]
		)
		self.assertEqual(len(orders), 1)
		self.assertEqual(orders[0].status, "Pending")
		# EIR -> Cleaning Order: the order carries its source EIR.
		self.assertEqual(orders[0].inspection, eir_name)
		container = frappe.db.get_value("Container", c, ["status", "cleaning_status"], as_dict=True)
		self.assertEqual(container.status, "In_Depot")
		self.assertEqual(container.cleaning_status, "Pending")

	def test_empty_clean_eir_creates_no_cleaning_order(self):
		c, _ = self._eir_in("CLEANEIR001", tank_status="Empty Clean")
		self.assertEqual(frappe.db.count("Cleaning Order", {"container": c}), 0)
		# Empty-clean EIR-In with no follow-up orders → tank is immediately Available.
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Available")

	def test_cleaning_order_creation_is_idempotent(self):
		c = _make_container("DIRTYEIR002")
		self._containers.append(c)
		for _ in range(2):
			res = eir.create_eir(inspection_type="EIR-In", container=c, tank_status="Empty Dirty", submit=True)
			self._inspections.append(res["name"])
		# Only one open Cleaning Order despite two Empty-Dirty EIRs.
		self.assertEqual(frappe.db.count("Cleaning Order", {"container": c}), 1)
