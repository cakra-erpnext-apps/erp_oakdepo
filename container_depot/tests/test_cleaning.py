"""Cleaning Order flow (container_depot.cleaning): the order carries the chosen services
(tariff + manhour), the remarks and the surveyor's signature.

Flow: order (Pending) -> start_cleaning (In_Progress) -> save_cleaning_order(submit) ->
Completed, which parks the tank in the Cleaning Bay. The submitted Completed order is
itself the TANK OUT proof. A normal order cannot be submitted before it is started.

Submitting a Cleaning Order commits (controller drives the container), so created docs
are removed explicitly after each test.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot import cleaning
from container_depot.container_depot.exceptions import AlreadySettled
from container_depot.tests.test_eir import _make_container


class TestCleaningOrderFlow(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._containers = []
		self._orders = []

	def tearDown(self):
		for o in self._orders:
			frappe.db.delete("Cleaning Order", {"name": o})
		for c in self._containers:
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
	def test_detail_remarks_start_blank(self):
		# No boiler-plate template is pre-filled into Catatan/remarks on a fresh order.
		c = self._container("CLNREM00001")
		co = self._order(c)
		d = cleaning.get_cleaning_order_detail(co)
		self.assertEqual(d["remarks"], "")

	def test_detail_returns_tank_spec(self):
		c = self._container("CLNDET00001", container_type="ISO Tank", tare_weight=3800, capacity=26000)
		co = self._order(c)
		d = cleaning.get_cleaning_order_detail(co)
		self.assertEqual(d["container"], c)
		self.assertEqual(d["tank_type"], "ISO Tank")
		self.assertEqual(d["tare"], 3800)
		self.assertEqual(d["capacity"], 26000)
		self.assertEqual(str(d["date_of_issue"]), frappe.utils.today())

	def test_detail_carries_cleaning_instructions(self):
		"""Instruksi yang ditulis Admin Ops di order harus sampai ke PWA operator."""
		co = self._order(self._container("CLNINSTR001"))
		frappe.db.set_value("Cleaning Order", co, "cleaning_instructions", "Bilas 2x, jangan pakai deterjen.")
		self.assertEqual(
			cleaning.get_cleaning_order_detail(co)["cleaning_instructions"],
			"Bilas 2x, jangan pakai deterjen.",
		)

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

	def test_start_then_submit_completes(self):
		# OAK1 has a seeded Cleaning Bay zone (OAK1-CBAY).
		c = self._container("CLNFULL0001", status="In_Depot", depot="OAK1")
		co = self._order(c)
		cleaning.start_cleaning(co)
		res = cleaning.save_cleaning_order(
			cleaning_order=co, cleaning_type="Steam Wash", remarks="bersih", submit=True,
		)
		self.assertEqual(res["docstatus"], 1)
		self.assertEqual(res["status"], "Completed")

		cont = frappe.db.get_value("Container", c, ["status"], as_dict=True)
		self.assertEqual(cont.status, "Available")
		# The submitted Completed order IS the TANK OUT proof Order Muat gates on.
		self.assertTrue(frappe.db.exists(
			"Cleaning Order", {"container": c, "status": "Completed", "docstatus": 1}
		))
		self.assertEqual(frappe.db.get_value("Cleaning Order", co, "remarks"), "bersih")

	def test_finished_order_refuses_a_late_save_as_AlreadySettled(self):
		# The offline queue's worst case: the surveyor signed off in a dead spot, and by the
		# time the handset found signal somebody had already completed the same order on the
		# Desk. The refusal has to be `AlreadySettled` and not a plain ValidationError —
		# Frappe puts the class name in the response as `exc_type`, and that is what tells
		# the PWA to park the row as "sudah ditangani" instead of retrying it for ever.
		# See container_depot/exceptions.py and frontend/src/data/outbox.js.
		c = self._container("CLNSETTLED1", status="In_Depot", depot="OAK1")
		co = self._order(c)
		cleaning.start_cleaning(co)
		cleaning.save_cleaning_order(cleaning_order=co, cleaning_type="Steam Wash", submit=True)

		with self.assertRaises(AlreadySettled):
			cleaning.save_cleaning_order(cleaning_order=co, remarks="dari HP yang offline")
		# Still a ValidationError, so every existing caller and test keeps working.
		with self.assertRaises(frappe.ValidationError):
			cleaning.start_cleaning(co)

	def test_save_draft_keeps_order_open(self):
		c = self._container("CLNDRAFT001", status="In_Depot")
		co = self._order(c)
		cleaning.start_cleaning(co)
		res = cleaning.save_cleaning_order(cleaning_order=co, remarks="draft note", submit=False)
		self.assertEqual(res["docstatus"], 0)
		self.assertEqual(frappe.db.get_value("Cleaning Order", co, "remarks"), "draft note")
