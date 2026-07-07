"""Cleaning Order flow (operations.cleaning): the cleanliness checklist + gas free +
seals now live on the Cleaning Order itself (no separate statement doc).

Flow: order (Pending) -> start_cleaning (In_Progress) -> save_cleaning_order(submit) ->
Completed, which parks the tank in the Cleaning Bay and mints the no-expiry Cleaning
Certificate. A normal order cannot be submitted before it is started.

Submitting a Cleaning Order commits (controller drives the container), so created docs
are removed explicitly after each test.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.api import _latest_valid_cleaning_cert
from container_depot.operations import cleaning
from container_depot.patches.v0_31 import seed_cleaning_checklist
from container_depot.tests.test_eir import _make_container


class TestCleaningOrderFlow(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		seed_cleaning_checklist.execute()  # ensure the 12-row master exists
		self._containers = []
		self._orders = []

	def tearDown(self):
		for o in self._orders:
			cert = frappe.db.get_value("Cleaning Order", o, "cleaning_certificate")
			if cert:
				frappe.db.delete("Cleaning Certificate", {"name": cert})
			frappe.db.delete("Cleaning Order", {"name": o})
		for c in self._containers:
			frappe.db.delete("Cleaning Certificate", {"container": c})
			frappe.db.delete("Cleaning Order", {"container": c})
			frappe.db.delete("Container Activity", {"container": c})
			frappe.db.delete("Container", {"name": c})
		frappe.db.commit()
		super().tearDown()

	def _container(self, cno, **kw):
		c = _make_container(cno, **kw)
		self._containers.append(c)
		return c

	def _order(self, container, **kw):
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "Pending", **kw,
		}).insert(ignore_permissions=True)
		self._orders.append(co.name)
		return co.name

	# --- masters / detail -----------------------------------------------------
	def test_masters_seeded_12(self):
		masters = cleaning.get_cleaning_masters()
		self.assertEqual(len(masters["checklist"]), 12)
		self.assertEqual({r["section"] for r in masters["checklist"]}, {"Exterior", "Interior", "Valves & Fittings"})

	def test_detail_returns_tank_spec(self):
		c = self._container("CLNDET00001", container_type="ISO Tank", tare_weight=3800, capacity=26000)
		co = self._order(c)
		d = cleaning.get_cleaning_order_detail(co)
		self.assertEqual(d["container"], c)
		self.assertEqual(d["tank_type"], "ISO Tank")
		self.assertEqual(d["tare"], 3800)
		self.assertEqual(d["capacity"], 26000)
		self.assertEqual(str(d["date_of_issue"]), frappe.utils.today())

	def test_cargo_history_empty_ok(self):
		c = self._container("CLNCARGO001")
		self.assertEqual(cleaning.cargo_history(c), [])

	# --- lifecycle ------------------------------------------------------------
	def test_start_marks_in_progress(self):
		c = self._container("CLNSTART001", status="In_Depot")
		co = self._order(c)
		cleaning.start_cleaning(co)
		self.assertEqual(frappe.db.get_value("Cleaning Order", co, "status"), "In_Progress")
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "In_Depot")

	def test_cannot_submit_before_start(self):
		c = self._container("CLNNOST0001", status="In_Depot")
		co = self._order(c)
		with self.assertRaises(frappe.ValidationError):
			cleaning.save_cleaning_order(cleaning_order=co, submit=True)
		self.assertEqual(frappe.db.get_value("Cleaning Order", co, "docstatus"), 0)

	def test_start_then_submit_completes_and_mints_cert(self):
		# OAK1 has a seeded Cleaning Bay zone (OAK1-CBAY).
		c = self._container("CLNFULL0001", status="In_Depot", depot="OAK1")
		co = self._order(c)
		cleaning.start_cleaning(co)
		res = cleaning.save_cleaning_order(
			cleaning_order=co, cleaning_type="Steam Wash",
			results=[{"item_code": "06", "result": "No", "note": "faint odour"}], submit=True,
		)
		self.assertEqual(res["docstatus"], 1)
		self.assertEqual(res["status"], "Completed")
		self.assertTrue(res["cleaning_certificate"])

		cont = frappe.db.get_value("Container", c, ["status"], as_dict=True)
		self.assertEqual(cont.status, "Available")
		# The minted cert (no expiry) satisfies the TANK OUT gate.
		self.assertEqual(_latest_valid_cleaning_cert(c), res["cleaning_certificate"])
		# All 12 checklist rows recorded on the order; the "No" line carried its note.
		co_doc = frappe.get_doc("Cleaning Order", co)
		self.assertEqual(len(co_doc.checklist), 12)
		odour = next(r for r in co_doc.checklist if r.checklist_item == "06")
		self.assertEqual(odour.result, "No")
		self.assertEqual(odour.note, "faint odour")

	def test_save_draft_keeps_order_open(self):
		c = self._container("CLNDRAFT001", status="In_Depot")
		co = self._order(c)
		cleaning.start_cleaning(co)
		res = cleaning.save_cleaning_order(cleaning_order=co, gas_free="Yes", o2_percent=20.9, submit=False)
		self.assertEqual(res["docstatus"], 0)
		self.assertEqual(frappe.db.get_value("Cleaning Order", co, "gas_free"), "Yes")
