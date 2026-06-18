"""EIR follow-up logic (operations.eir_followups): detect + create a Cleaning Order
(Empty Dirty) or a Repair Order / M&R (real damage findings) from a submitted EIR.

The logic is NOT wired into on_submit — these tests call it directly. All created
docs are removed after each test (EIR submit commits, so cleanup is explicit)."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.operations import eir, eir_followups
from container_depot.tests.test_eir import _make_container


class TestEirFollowups(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._containers = []
		self._inspections = []

	def tearDown(self):
		for ins in self._inspections:
			frappe.db.delete("Repair Order", {"inspection": ins})
			frappe.db.delete("Inspection", {"name": ins})
		for c in self._containers:
			frappe.db.delete("Cleaning Order", {"container": c})
			frappe.db.delete("Repair Order", {"container": c})
			frappe.db.delete("Container", {"name": c})
		frappe.db.commit()
		super().tearDown()

	def _eir(self, cno, *, tank_status="Empty Clean", lines=None):
		c = _make_container(cno)
		self._containers.append(c)
		res = eir.create_eir(
			inspection_type="EIR-In", container=c, tank_status=tank_status,
			lines=lines or [], submit=True,
		)
		self._inspections.append(res["name"])
		return c, res["name"]

	# --- detection ------------------------------------------------------------
	def test_needs_cleaning_only_when_empty_dirty(self):
		_, dirty = self._eir("FUPCLEAN001", tank_status="Empty Dirty")
		_, clean = self._eir("FUPCLEAN002", tank_status="Empty Clean")
		self.assertTrue(eir_followups.eir_needs_cleaning(dirty))
		self.assertFalse(eir_followups.eir_needs_cleaning(clean))

	def test_needs_mr_only_with_real_damage(self):
		_, dmg = self._eir(
			"FUPMR000001", lines=[{"item_code": "11", "damage_code": "12", "remarks": "broken"}]
		)
		_, none = self._eir("FUPMR000002")  # no findings
		self.assertTrue(eir_followups.eir_needs_mr(dmg))
		self.assertEqual(len(eir_followups.eir_real_damage_rows(dmg)), 1)
		self.assertFalse(eir_followups.eir_needs_mr(none))

	# --- creation -------------------------------------------------------------
	def test_create_cleaning_order_idempotent(self):
		c, dirty = self._eir("FUPCLEAN003", tank_status="Empty Dirty")
		name = eir_followups.create_cleaning_order_from_eir(dirty)
		self.assertTrue(name)
		co = frappe.db.get_value("Cleaning Order", name, ["container", "status"], as_dict=True)
		self.assertEqual(co.container, c)
		self.assertEqual(co.status, "Pending")
		# Idempotent: a second call returns the same open order, not a duplicate.
		self.assertEqual(eir_followups.create_cleaning_order_from_eir(dirty), name)

	def test_no_cleaning_order_when_not_dirty(self):
		_, clean = self._eir("FUPCLEAN004", tank_status="Empty Clean")
		self.assertIsNone(eir_followups.create_cleaning_order_from_eir(clean))

	def test_create_repair_order_idempotent(self):
		c, dmg = self._eir(
			"FUPMR000003", lines=[{"item_code": "11", "damage_code": "12", "remarks": "broken"}]
		)
		name = eir_followups.create_repair_order_from_eir(dmg)
		self.assertTrue(name)
		ro = frappe.db.get_value("Repair Order", name, ["container", "inspection", "status"], as_dict=True)
		self.assertEqual(ro.container, c)
		self.assertEqual(ro.inspection, dmg)
		# EIR damage -> an editable Draft M&R (the team then picks the parts).
		self.assertEqual(ro.status, "Draft")
		# Idempotent: one open M&R per container.
		self.assertEqual(eir_followups.create_repair_order_from_eir(dmg), name)
		# It copied the EIR damage entry into the M&R's read-only Damages snapshot.
		self.assertEqual(frappe.db.count("Repair Damage Entry", {"parent": name}), 1)

	def test_no_repair_order_without_damage(self):
		_, none = self._eir("FUPMR000004")
		self.assertIsNone(eir_followups.create_repair_order_from_eir(none))
