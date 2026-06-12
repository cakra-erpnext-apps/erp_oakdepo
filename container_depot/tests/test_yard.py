"""Tests for the Depot Storage feature (Operator Kalmar yard placement).

Covers the status->category recommendation, emptiest-first zone ranking, zone
occupancy, the audited placement (Container Movement + Container sync), the SOP
stacking/capacity guards, and the ESS endpoint shapes + auth guard.

Read-only assertions use shared fixtures built in setUpClass. Every mutating test
is self-contained (own throwaway zone/container, cleaned up in ``finally``) so the
alphabetical test order never pollutes the shared occupancy counts.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.operations.yard import (
	STATUS_TO_CATEGORY,
	place_container,
	recommend_zones,
	zone_occupancy,
)
from container_depot.ess.yard import yard_overview, yard_place, yard_recommend, yard_zone_tanks
from container_depot.tests.test_api import ensure_test_branch

DEPOT = "YZTD"
DEPOT2 = "YZTD2"  # sibling depot in the SAME branch, with NO zones of its own
PREFIX = "YZTU"

# Shared, read-only fixture zones: (code, category, capacity).
ZONES = [
	("YZT-CLEAN-A", "Cleaning Bay", 2),
	("YZT-READY-A", "Ready", 3),
	("YZT-READY-B", "Ready", 3),
]


def _zone(code, category, capacity, depot=DEPOT, block=""):
	frappe.get_doc({
		"doctype": "Yard Zone",
		"zone_code": code,
		"zone_name": code,
		"depot": depot,
		"block": block or None,
		"category": category,
		"capacity": capacity,
		"max_rows": 5,
		"max_rows_full": 6,
		"max_tiers": 5,
		"is_active": 1,
	}).insert(ignore_permissions=True)


def _container(no, status, yard_zone=None, depot=DEPOT):
	frappe.get_doc({
		"doctype": "Container",
		"container_no": no,
		"container_type": "ISO Tank",
		"status": status,
		"depot": depot,
		"yard_zone": yard_zone,
	}).insert(ignore_permissions=True)


def _teardown():
	frappe.db.delete("Container Movement", {"container": ["like", f"{PREFIX}%"]})
	frappe.db.delete("Container", {"name": ["like", f"{PREFIX}%"]})
	frappe.db.delete("Yard Zone", {"name": ["like", "YZT-%"]})
	for dep in (DEPOT, DEPOT2):
		if frappe.db.exists("Depot", dep):
			frappe.db.delete("Depot", {"name": dep})
	frappe.db.commit()


def _build():
	frappe.get_doc({
		"doctype": "Depot",
		"depot_code": DEPOT,
		"depot_name": "Yard Zone Test Depot",
		"branch": ensure_test_branch(),
	}).insert(ignore_permissions=True)
	for code, category, capacity in ZONES:
		_zone(code, category, capacity)
	_container("YZTU0000002", "Available", yard_zone="YZT-READY-A")  # occupies READY-A
	_container("YZTU0000003", "Available")  # recommend target -> Ready
	_container("YZTU0000004", "Gate_Out")  # no placeable category
	_container("YZTU0000010", "Cleaning_In_Progress")  # recommend target -> Cleaning Bay
	# Sibling depot in the same branch, with NO zones — exercises the branch fallback.
	frappe.get_doc({
		"doctype": "Depot",
		"depot_code": DEPOT2,
		"depot_name": "Yard Zone Test Depot 2",
		"branch": ensure_test_branch(),
	}).insert(ignore_permissions=True)
	_container("YZTU0000020", "Available", depot=DEPOT2)  # no zones in its own depot
	frappe.db.commit()


class TestYard(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_teardown()
		_build()

	@classmethod
	def tearDownClass(cls):
		_teardown()
		super().tearDownClass()

	# --- mapping / recommendation (read-only) ---------------------------------
	def test_status_category_mapping(self):
		self.assertEqual(STATUS_TO_CATEGORY["Needs_Cleaning"], "Empty Dirty Queue")
		self.assertEqual(STATUS_TO_CATEGORY["Cleaning_In_Progress"], "Cleaning Bay")
		self.assertEqual(STATUS_TO_CATEGORY["Available"], "Ready")
		self.assertEqual(STATUS_TO_CATEGORY["Repair_In_Progress"], "Workshop")
		self.assertEqual(STATUS_TO_CATEGORY["Pending_Survey"], "Survey")
		self.assertIsNone(STATUS_TO_CATEGORY["Gate_Out"])

	def test_recommend_target_category(self):
		self.assertEqual(recommend_zones("YZTU0000010")["target_category"], "Cleaning Bay")
		self.assertEqual(recommend_zones("YZTU0000003")["target_category"], "Ready")

	def test_recommend_ranks_emptiest_first(self):
		res = recommend_zones("YZTU0000003")
		codes = [z["zone_code"] for z in res["zones"]]
		# Both Ready zones in this depot, emptiest (READY-B, 0/3) ahead of READY-A (1/3).
		self.assertEqual(codes, ["YZT-READY-B", "YZT-READY-A"])
		self.assertTrue(res["zones"][0]["recommended"])
		self.assertEqual(res["zones"][0]["occupied"], 0)
		self.assertEqual(res["zones"][1]["occupied"], 1)

	def test_recommend_empty_for_gateout(self):
		res = recommend_zones("YZTU0000004")
		self.assertIsNone(res["target_category"])
		self.assertEqual(res["zones"], [])
		# Even with no recommendation, every in-scope zone is offered for manual placement.
		self.assertTrue(len(res["all_zones"]) >= 3)

	def test_recommend_branch_fallback(self):
		# YZTU0000020 sits in DEPOT2 (no zones); recommendation falls back to the
		# sibling depot in the same branch (DEPOT).
		res = recommend_zones("YZTU0000020")
		self.assertEqual(res["target_category"], "Ready")
		self.assertEqual({z["zone_code"] for z in res["zones"]}, {"YZT-READY-A", "YZT-READY-B"})
		self.assertTrue(all(not z["same_depot"] for z in res["zones"]))
		# Emptiest sibling zone is the recommended one.
		self.assertEqual(res["zones"][0]["zone_code"], "YZT-READY-B")
		self.assertTrue(res["zones"][0]["recommended"])

	def test_recommend_unknown_container_raises(self):
		with self.assertRaises(frappe.DoesNotExistError):
			recommend_zones("YZTU9999999")

	# --- occupancy (read-only) ------------------------------------------------
	def test_zone_occupancy(self):
		by_code = {z["zone_code"]: z for z in zone_occupancy(depot=DEPOT)}
		self.assertEqual(by_code["YZT-READY-A"]["occupied"], 1)
		self.assertEqual(by_code["YZT-READY-A"]["capacity"], 3)
		self.assertEqual(by_code["YZT-READY-B"]["occupied"], 0)
		self.assertEqual(by_code["YZT-CLEAN-A"]["free"], 2)
		self.assertFalse(by_code["YZT-CLEAN-A"]["is_full"])

	# --- placement (self-contained) -------------------------------------------
	def test_place_creates_movement_and_syncs_container(self):
		_zone("YZT-PLACE-X", "Ready", 3)
		_container("YZTU0000099", "Available")
		try:
			res = place_container("YZTU0000099", "YZT-PLACE-X", row="2", tier=1)
			self.assertTrue(res["success"])
			# Audited movement created (Yard event).
			mv = frappe.get_all(
				"Container Movement",
				filters={"container": "YZTU0000099", "to_zone": "YZT-PLACE-X"},
				fields=["event_type", "to_tier", "to_row"],
			)
			self.assertEqual(len(mv), 1)
			self.assertEqual(mv[0].event_type, "Yard")
			self.assertEqual(mv[0].to_tier, 1)
			# Movement synced the placement back onto the Container.
			c = frappe.db.get_value(
				"Container", "YZTU0000099", ["yard_zone", "tier", "row"], as_dict=True
			)
			self.assertEqual(c.yard_zone, "YZT-PLACE-X")
			self.assertEqual(c.tier, 1)
			self.assertEqual(c.row, "2")
			# Occupancy now reflects the placed tank.
			by_code = {z["zone_code"]: z for z in zone_occupancy(depot=DEPOT)}
			self.assertEqual(by_code["YZT-PLACE-X"]["occupied"], 1)
		finally:
			frappe.db.delete("Container Movement", {"container": "YZTU0000099"})
			frappe.delete_doc("Container", "YZTU0000099", force=True, ignore_permissions=True)
			frappe.delete_doc("Yard Zone", "YZT-PLACE-X", force=True, ignore_permissions=True)
			frappe.db.commit()

	def test_place_rejects_tier_over_limit(self):
		with self.assertRaises(frappe.ValidationError):
			place_container("YZTU0000010", "YZT-CLEAN-A", tier=6)

	def test_place_rejects_row_over_limit(self):
		with self.assertRaises(frappe.ValidationError):
			place_container("YZTU0000010", "YZT-CLEAN-A", row="7")

	def test_place_rejects_full_zone(self):
		_zone("YZT-FULL-X", "Ready", 1)
		_container("YZTU0000098", "Available", yard_zone="YZT-FULL-X")  # fills the single slot
		try:
			with self.assertRaises(frappe.ValidationError):
				place_container("YZTU0000010", "YZT-FULL-X", tier=1)
		finally:
			frappe.db.delete("Container Movement", {"container": "YZTU0000098"})
			frappe.delete_doc("Container", "YZTU0000098", force=True, ignore_permissions=True)
			frappe.delete_doc("Yard Zone", "YZT-FULL-X", force=True, ignore_permissions=True)
			frappe.db.commit()

	def test_place_rejects_unknown_zone(self):
		with self.assertRaises(frappe.ValidationError):
			place_container("YZTU0000010", "NO-SUCH-ZONE")

	# --- ESS endpoints --------------------------------------------------------
	def test_yard_overview_shape(self):
		res = yard_overview(depot=DEPOT)
		self.assertTrue(res["success"])
		self.assertEqual({z["zone_code"] for z in res["zones"]}, {c for c, _, _ in ZONES})
		self.assertIn(DEPOT, [d["code"] for d in res["depots"]])

	def test_yard_recommend_endpoint(self):
		res = yard_recommend("YZTU0000003")
		self.assertTrue(res["success"])
		self.assertEqual(res["target_category"], "Ready")
		self.assertTrue(len(res["zones"]) >= 1)

	def test_yard_zone_tanks_endpoint(self):
		res = yard_zone_tanks("YZT-READY-A")
		self.assertTrue(res["success"])
		self.assertIn("YZTU0000002", [t["container_no"] for t in res["items"]])

	def test_yard_place_rejects_guest(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				yard_place(container_no="YZTU0000010", zone="YZT-CLEAN-A")
		finally:
			frappe.set_user("Administrator")
