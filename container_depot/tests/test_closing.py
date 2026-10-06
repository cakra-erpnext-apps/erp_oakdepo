"""Tutup Order (container_depot/container_depot/closing.py).

Nothing here commits: every row goes with FrappeTestCase's class rollback.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, now_datetime

from container_depot.container_depot import closing

_PREFIX = "CLOSET"


class TestCloseOrder(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")

	def _container(self, suffix):
		principal = frappe.db.get_value("Customer", {"disabled": 0}) or frappe.get_doc(
			{"doctype": "Customer", "customer_name": f"{_PREFIX} Principal"}
		).insert(ignore_permissions=True).name
		return frappe.get_doc({
			"doctype": "Container", "container_no": f"{_PREFIX}{suffix}",
			"container_type": "ISO Tank", "status": "In_Depot", "principal": principal,
		}).insert(ignore_permissions=True).name

	def _cleaning(self, container, plan_date=None):
		return frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "Pending",
			"plan_date": plan_date or getdate(),
		}).insert(ignore_permissions=True)

	def _left(self, container, when):
		"""A finished visit: the tank gated out at ``when``."""
		frappe.get_doc({
			"doctype": "Gate Entry", "container_no": container, "status": "Gate_Out_Completed",
			"gate_in_timestamp": add_days(when, -1), "gate_out_timestamp": when,
			"creation": when, "modified": when,
		}).db_insert()

	def test_only_administrator(self):
		co = self._cleaning(self._container("A1"))
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			closing.close_order("Cleaning Order", co.name, "di luar aplikasi")

	def test_reason_is_required(self):
		co = self._cleaning(self._container("A2"))
		with self.assertRaises(frappe.ValidationError):
			closing.close_order("Cleaning Order", co.name, "  ")

	def test_newest_cleaning_finishes_like_a_submit_and_frees_the_tank(self):
		tank = self._container("C1")
		last_week = add_days(getdate(), -7)
		co = self._cleaning(tank, plan_date=last_week)
		self.assertEqual(frappe.db.get_value("Container", tank, "status"), "In_Depot")

		closing.close_order("Cleaning Order", co.name, "dikerjakan di luar aplikasi")

		co.reload()
		self.assertEqual((co.docstatus, co.status, co.closed_by_admin), (1, "Completed", 1))
		# Dated by the order's own date, not today.
		self.assertEqual(getdate(co.cleaning_end), last_week)
		self.assertEqual(frappe.db.get_value("Container", tank, "status"), "Available")

	def test_older_order_leaves_the_tank_alone(self):
		tank = self._container("C2")
		old = self._cleaning(tank)
		frappe.db.set_value("Cleaning Order", old.name, "creation", add_days(now_datetime(), -10))
		self._left(tank, add_days(now_datetime(), -5))
		self._cleaning(tank)  # this visit's work, still open

		closing.close_order("Cleaning Order", old.name, "dikerjakan di luar aplikasi")

		self.assertEqual(frappe.db.get_value("Cleaning Order", old.name, "status"), "Completed")
		# The tank is still held by this visit's open cleaning.
		self.assertEqual(frappe.db.get_value("Container", tank, "status"), "In_Depot")

	def test_repair_order_completes_on_its_own_date(self):
		tank = self._container("R1")
		plan = add_days(getdate(), -3)
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": tank, "job_type": "Repair",
			"status": "Draft", "billing_status": "Unbilled", "plan_date": plan,
		}).insert(ignore_permissions=True)

		closing.close_order("Repair Order", ro.name, "dikerjakan di luar aplikasi")

		ro.reload()
		self.assertEqual((ro.status, ro.closed_by_admin), ("Completed", 1))
		self.assertEqual(getdate(ro.completion_date), plan)

	def test_leak_check_closes_without_a_photo(self):
		tank = self._container("L1")
		lc = frappe.get_doc({"doctype": "Leak Check", "container": tank, "status": "Open"})
		lc.db_insert()

		closing.close_order("Leak Check", lc.name, "dicek di luar aplikasi")

		self.assertEqual(
			frappe.db.get_value("Leak Check", lc.name, ["docstatus", "status", "closed_by_admin"]),
			(1, "Completed", 1),
		)

	def test_older_eir_is_finished_on_paper_only(self):
		tank = self._container("E1")
		eir = frappe.get_doc({
			"doctype": "Inspection", "inspection_type": "EIR-Out", "container": tank,
			"inspector": "Administrator", "status": "Draft", "eir_date": add_days(getdate(), -9),
			"creation": add_days(now_datetime(), -9), "modified": add_days(now_datetime(), -9),
		})
		eir.db_insert()
		self._left(tank, add_days(now_datetime(), -5))

		closing.close_order("Inspection", eir.name, "dikerjakan di luar aplikasi")

		self.assertEqual(
			frappe.db.get_value("Inspection", eir.name, ["docstatus", "status", "closed_by_admin"]),
			(1, "Submitted", 1),
		)
		# No gate-out ran for a visit that is over: the tank is still in the yard.
		self.assertIn(frappe.db.get_value("Container", tank, "status"), ("In_Depot", "Available"))
		self.assertFalse(frappe.db.exists("Gate Entry", {"eir_reference": eir.name}))

	def test_survey_order_closes_only_the_picked_tanks(self):
		a, b = self._container("S1"), self._container("S2")
		so = frappe.get_doc({
			"doctype": "Survey Order", "booking": "CLOSET-BKG", "status": "Scheduled",
			"survey_date": add_days(getdate(), -2),
			"tanks": [{"container": a, "status": "Waiting Lowering"},
				  {"container": b, "status": "Waiting Lowering"}],
		})
		so.db_insert()
		for row in so.tanks:
			row.update({"parent": so.name, "parenttype": "Survey Order", "parentfield": "tanks"})
			row.db_insert()
		picked = so.tanks[0].name

		closing.close_order("Survey Order", so.name, "disurvey di luar aplikasi", rows=[picked])

		rows = {r.name: r for r in frappe.get_all(
			"Survey Order Tank", filters={"parent": so.name},
			fields=["name", "status", "closed_by_admin", "surveyed_on"],
		)}
		self.assertEqual((rows[picked].status, rows[picked].closed_by_admin), ("Survey Done", 1))
		self.assertEqual(getdate(rows[picked].surveyed_on), add_days(getdate(), -2))
		other = so.tanks[1].name
		self.assertEqual((rows[other].status, rows[other].closed_by_admin), ("Waiting Lowering", 0))

	def test_a_finished_order_cannot_be_closed_again(self):
		co = self._cleaning(self._container("F1"))
		closing.close_order("Cleaning Order", co.name, "dikerjakan di luar aplikasi")
		with self.assertRaises(frappe.ValidationError):
			closing.close_order("Cleaning Order", co.name, "lagi")

	def test_bon_closes_its_own_open_orders_first(self):
		"""A bon is not Completed over open work: its Leak Check closes with it."""
		tank = self._container("B1")
		bon = frappe.get_doc({
			"doctype": "Order Bongkar", "docstatus": 1, "order_status": "Issued",
			"booking": "CLOSET-BKG", "creation": now_datetime(), "modified": now_datetime(),
		})
		bon.db_insert()
		lc = frappe.get_doc({"doctype": "Leak Check", "container": tank, "status": "Open",
				     "order_bongkar": bon.name})
		lc.db_insert()

		res = closing.close_order("Order Bongkar", bon.name, "dikerjakan di luar aplikasi")

		self.assertEqual(frappe.db.get_value("Leak Check", lc.name, "status"), "Completed")
		self.assertEqual([c["name"] for c in res["children"]], [lc.name])
		self.assertEqual(
			frappe.db.get_value("Order Bongkar", bon.name, ["order_status", "closed_by_admin"]),
			("Completed", 1),
		)
