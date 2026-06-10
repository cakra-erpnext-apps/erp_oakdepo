"""Phase 8 (B0) tests: canonical Container status state machine + customer type.

Covers the normalised ``Container.status`` enum, the manual-transition guard in
``Container.validate`` (and its automation bypass), and the ``oak_customer_type``
custom field added to Customer.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.state_machine import CONTAINER_TRANSITIONS, assert_transition, is_allowed


class TestContainerStateMachine(FrappeTestCase):
	CONTAINER_NO = "SMTU8880001"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Container", cls.CONTAINER_NO):
			frappe.get_doc({
				"doctype": "Container",
				"container_no": cls.CONTAINER_NO,
				"container_type": "ISO Tank",
				"status": "Available",
			}).insert(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		frappe.db.delete("Container Movement", {"container": cls.CONTAINER_NO})
		frappe.db.delete("Container", {"container_no": cls.CONTAINER_NO})
		frappe.db.commit()
		super().tearDownClass()

	# --- pure predicate / assert helpers -------------------------------------

	def test_is_allowed_predicate(self):
		self.assertTrue(is_allowed(None, "Gate_In"))          # new doc
		self.assertTrue(is_allowed("Gate_In", "Gate_In"))      # no-op
		self.assertTrue(is_allowed("Available", "Gate_In"))    # legal edge
		self.assertTrue(is_allowed("Survey_In_Progress", "Awaiting_MR_Approval"))
		self.assertFalse(is_allowed("Available", "Repair_In_Progress"))  # illegal (no jump into repair)
		self.assertTrue(is_allowed("LegacyUnknown", "Gate_In"))  # unknown source passes

	def test_assert_transition_raises_on_illegal(self):
		with self.assertRaises(frappe.ValidationError):
			assert_transition("Available", "Repair_In_Progress")

	def test_assert_transition_bypassed_by_automation_flag(self):
		frappe.flags.in_status_automation = True
		try:
			# Would be illegal, but the automation flag short-circuits the guard.
			assert_transition("Available", "Repair_In_Progress")
		finally:
			frappe.flags.in_status_automation = False

	# --- enforcement through Container.validate ------------------------------

	def test_legal_transition_saves(self):
		c = frappe.get_doc("Container", self.CONTAINER_NO)
		c.status = "Gate_In"
		c.save(ignore_permissions=True)  # Available -> Gate_In is legal
		self.assertEqual(frappe.db.get_value("Container", self.CONTAINER_NO, "status"), "Gate_In")
		# reset for isolation
		frappe.db.set_value("Container", self.CONTAINER_NO, "status", "Available")

	def test_illegal_transition_blocked(self):
		c = frappe.get_doc("Container", self.CONTAINER_NO)
		c.status = "Repair_In_Progress"  # Available -> Repair_In_Progress is illegal
		with self.assertRaises(frappe.ValidationError):
			c.save(ignore_permissions=True)

	def test_full_release_path_is_walkable(self):
		"""The customer survey->release happy path is a connected chain."""
		path = [
			"Gate_In", "Pending_Survey", "Survey_In_Progress",
			"Available", "Released_Pending_Pickup", "Gate_Out",
		]
		prev = "Available"
		for nxt in path:
			self.assertTrue(is_allowed(prev, nxt), f"{prev} -> {nxt} should be legal")
			prev = nxt

	def test_no_dangling_targets(self):
		"""Every target referenced is itself a known source (no typos / orphans)."""
		known = set(CONTAINER_TRANSITIONS)
		for src, targets in CONTAINER_TRANSITIONS.items():
			for t in targets:
				self.assertIn(t, known, f"{src} -> {t}: target not a known state")


class TestCustomerTypeField(FrappeTestCase):
	def test_oak_customer_type_field_exists(self):
		meta = frappe.get_meta("Customer")
		field = meta.get_field("oak_customer_type")
		self.assertIsNotNone(field, "oak_customer_type custom field missing on Customer")
		self.assertEqual(field.fieldtype, "Select")
		for opt in ("Tank Owner", "Transporter", "Both"):
			self.assertIn(opt, (field.options or ""))
