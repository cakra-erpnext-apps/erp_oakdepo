"""Yard Placement Rule master + the 'needs move' (status/zone mismatch) flag.

Each rule maps a Container status to a LIST of allowed Yard Zone categories (first =
recommended target). ``operations.yard`` layers the master over the built-in
defaults; ``ess.inventory.get_tank_list`` flags a container whose current zone
category is outside ALL allowed categories for its status.
"""

from __future__ import annotations

import unittest
import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.ess.inventory import get_tank_list
from container_depot.operations import yard
from container_depot.tests.test_eir import _make_container


class TestYardPlacementRules(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._containers = []

	def tearDown(self):
		for c in self._containers:
			frappe.db.delete("Container", {"name": c})
		frappe.db.commit()
		super().tearDown()

	def _container(self, cno, **kw):
		c = _make_container(cno, **kw)
		self._containers.append(c)
		return c

	def _set_categories(self, status, categories):
		"""Replace a rule's allowed categories; returns the originals for restore."""
		rule = frappe.get_doc("Yard Placement Rule", status)
		orig = [c.category for c in rule.allowed_categories]
		rule.set("allowed_categories", [{"category": c} for c in categories])
		rule.flags.ignore_permissions = True
		rule.save()
		return orig

	@unittest.skip("Yard zones / inventory-stage buckets removed in Phase 2 status refactor")
	def test_default_primary_category(self):
		# Seeded default: In_Depot -> Empty Dirty Queue.
		self.assertEqual(yard.allowed_category_for_status("In_Depot"), "Empty Dirty Queue")

	@unittest.skip("Yard zones / inventory-stage buckets removed in Phase 2 status refactor")
	def test_master_override_changes_allowed(self):
		orig = self._set_categories("In_Depot", ["Cleaning Bay"])
		try:
			self.assertEqual(yard.allowed_categories_for_status("In_Depot"), ["Cleaning Bay"])
		finally:
			self._set_categories("In_Depot", orig)

	@unittest.skip("Yard zones / inventory-stage buckets removed in Phase 2 status refactor")
	def test_needs_move_flag_detects_mismatch(self):
		# In_Depot belongs in Empty Dirty Queue, but parked in a Cleaning Bay zone.
		c = self._container("YPRMOVE0001", status="In_Depot", depot="OAK1", yard_zone="OAK1-CBAY")
		row = next((i for i in get_tank_list(needs_move=1)["items"] if i["name"] == c), None)
		self.assertIsNotNone(row)
		self.assertTrue(row["needs_move"])
		self.assertEqual(row["target_category"], "Empty Dirty Queue")

	@unittest.skip("Yard zones / inventory-stage buckets removed in Phase 2 status refactor")
	def test_multi_category_allows_either_zone(self):
		# Allow In_Depot in BOTH Empty Dirty Queue and Cleaning Bay -> a tank in
		# the Cleaning Bay is no longer a mismatch.
		orig = self._set_categories("In_Depot", ["Empty Dirty Queue", "Cleaning Bay"])
		try:
			c = self._container("YPRMULTI001", status="In_Depot", depot="OAK1", yard_zone="OAK1-CBAY")
			self.assertCountEqual(
				yard.allowed_categories_for_status("In_Depot"), ["Empty Dirty Queue", "Cleaning Bay"]
			)
			self.assertNotIn(c, [i["name"] for i in get_tank_list(needs_move=1)["items"]])
		finally:
			self._set_categories("In_Depot", orig)

	def test_correctly_placed_not_flagged(self):
		# In_Depot belongs in a Cleaning Bay zone — no mismatch.
		c = self._container("YPROK000001", status="In_Depot", depot="OAK1", yard_zone="OAK1-CBAY")
		self.assertNotIn(c, [i["name"] for i in get_tank_list(needs_move=1)["items"]])
