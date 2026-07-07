"""Tests for the home-dashboard aggregate endpoint
(``container_depot.ess.inventory.get_dashboard_summary``).

The endpoint is a pure aggregation over existing, separately-tested read
functions, so these tests focus on:
* the response **shape** (every KPI section + key is present),
* **status counts** and **yard occupancy** are correct when scoped to a fresh
  test depot (exact assertions are safe there), and
* **today's activity** and **pending-task** counts move by the right delta when a
  fixture is added (delta assertions, because those counts are instance-wide for
  an unrestricted user on the shared site).

FrappeTestCase wraps each test in a transaction and rolls it back, so the
per-test fixtures (created without commit) vanish automatically. A defensive
``tearDownClass`` removes any row that slipped through a nested commit.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from container_depot.ess.inventory import BUCKETS, get_dashboard_summary
from container_depot.tests.test_api import ensure_test_branch, ensure_test_customer

DEPOT = "DASHT"
ZONE = "DASH-Z1"
PREFIX = "DASH"


def _teardown():
	names = frappe.get_all("Container", filters={"container_no": ["like", f"{PREFIX}%"]}, pluck="name")
	if names:
		for dt in ["Container Movement", "Container Activity", "Cleaning Order", "Repair Order", "Inspection"]:
			frappe.db.delete(dt, {"container": ["in", names]})
		frappe.db.delete("Container", {"name": ["in", names]})
	if frappe.db.exists("Depot", DEPOT):
		frappe.db.delete("Depot", {"name": DEPOT})
	frappe.db.commit()


class TestDashboardSummary(FrappeTestCase):
	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		_teardown()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		# Some controllers (Container/Cleaning Order) commit, so per-test rollback
		# isn't enough to isolate the exact-count tests — clear the prefix first.
		_teardown()
		frappe.get_doc(
			{"doctype": "Depot", "depot_code": DEPOT, "depot_name": "Dashboard Test Depot", "branch": ensure_test_branch()}
		).insert(ignore_permissions=True)
		self.principal = ensure_test_customer("Dashboard Test Principal")

	def _container(self, no, status):
		frappe.get_doc({
			"doctype": "Container",
			"container_no": no,
			"container_type": "ISO Tank",
			"status": status,
			"depot": DEPOT,
			"principal": self.principal,
		}).insert(ignore_permissions=True)
		return no

	# --- shape -------------------------------------------------------------
	def test_summary_shape(self):
		res = get_dashboard_summary()
		self.assertTrue(res["success"])
		for key in ("counts", "periodic_test_due", "total", "today", "pending"):
			self.assertIn(key, res)
		# Yard occupancy was removed in the Phase 2 status/zone refactor.
		self.assertNotIn("yard", res)
		self.assertEqual(set(res["counts"]), set(BUCKETS))
		for key in ("gate_in", "gate_out", "eir"):
			self.assertIn(key, res["today"])
		for key in ("eir_in", "eir_out", "cleaning", "mr_open", "mr_approval"):
			self.assertIn(key, res["pending"])

	# --- status buckets (exact, depot-scoped) ------------------------------
	def test_status_counts_scoped(self):
		# No orders on any of them -> all fall in the `available` bucket (order-state driven).
		self._container("DASH0000001", "Available")
		self._container("DASH0000002", "In_Depot")
		self._container("DASH0000003", "In_Depot")
		res = get_dashboard_summary(depot=DEPOT)
		self.assertEqual(res["total"], 3)
		self.assertEqual(res["counts"]["available"], 3)
		self.assertEqual(res["counts"]["draft"], 0)
		self.assertEqual(res["counts"]["pending"], 0)
		self.assertEqual(res["counts"]["in_progress"], 0)
		self.assertEqual(res["counts"]["gate_out"], 0)

	# --- today's activity (delta, instance-wide) ---------------------------
	def test_today_activity_delta(self):
		c = self._container("DASH0000010", "Available")
		before = get_dashboard_summary()["today"]
		frappe.get_doc(
			{
				"doctype": "Container Activity",
				"container": c,
				"activity_type": "Gate In",
				"activity_time": now_datetime(),
				"depot": DEPOT,
			}
		).insert(ignore_permissions=True)
		after = get_dashboard_summary()["today"]
		self.assertEqual(after["gate_in"], before["gate_in"] + 1)
		self.assertEqual(after["gate_out"], before["gate_out"])  # unrelated type untouched

	# --- pending tasks (delta, instance-wide) ------------------------------
	def test_pending_counts_delta(self):
		c = self._container("DASH0000020", "Available")
		before = get_dashboard_summary()["pending"]

		frappe.get_doc(
			{"doctype": "Inspection", "container": c, "inspection_type": "EIR-In", "inspector": "Administrator"}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{"doctype": "Inspection", "container": c, "inspection_type": "EIR-Out", "inspector": "Administrator"}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{"doctype": "Cleaning Order", "container": c, "status": "Pending"}
		).insert(ignore_permissions=True)
		ro = frappe.get_doc(
			{"doctype": "Repair Order", "container": c, "status": "Draft", "billing_status": "Unbilled"}
		).insert(ignore_permissions=True)
		# Flip to Pending Approval via db (bypass the workflow transition guard).
		frappe.db.set_value("Repair Order", ro.name, "status", "Pending Approval", update_modified=False)

		after = get_dashboard_summary()["pending"]
		self.assertEqual(after["eir_in"], before["eir_in"] + 1)
		self.assertEqual(after["eir_out"], before["eir_out"] + 1)
		self.assertEqual(after["cleaning"], before["cleaning"] + 1)
		self.assertEqual(after["mr_open"], before["mr_open"] + 1)
		self.assertEqual(after["mr_approval"], before["mr_approval"] + 1)

	# --- auth guard --------------------------------------------------------
	def test_guest_is_rejected(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				get_dashboard_summary()
		finally:
			frappe.set_user("Administrator")
