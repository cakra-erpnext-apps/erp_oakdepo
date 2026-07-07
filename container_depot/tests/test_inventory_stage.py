"""Tests for the derived Container.inventory_stage (Container Inventory monitoring).

The stage is a legible grouping of the ~20 raw statuses, kept in step by
``Container.before_save`` and (for the one direct set_value site) the booking
cancel path.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.operations.doctype.container_booking.container_booking import void_draft
from container_depot.state_machine import (
	INVENTORY_STAGES,
	STAGE_BY_STATUS,
	stage_for_status,
)
from container_depot.tests._booking_helpers import make_contract
from container_depot.tests.test_api import ensure_test_customer


def _all_statuses():
	# Presence-based status set: Booked / In_Depot / Available / Gate_Out.
	return set(STAGE_BY_STATUS.keys())


def _make_container(cno, status="Available", principal=None):
	return frappe.get_doc({
		"doctype": "Container",
		"container_no": cno,
		"container_type": "ISO Tank",
		"status": status,
		"principal": principal or ensure_test_customer("InvStage Test Principal"),
	}).insert(ignore_permissions=True)


class TestInventoryStage(FrappeTestCase):
	def test_every_status_maps_to_a_known_stage(self):
		# Guards drift: a new raw status with no stage would slip through monitoring.
		for status in _all_statuses():
			stage = stage_for_status(status)
			self.assertIn(stage, INVENTORY_STAGES, f"{status} -> {stage} not a known stage")

	def test_stage_follows_status_on_save(self):
		c = _make_container("INVSTAGE001", status="Available")
		self.assertEqual(c.inventory_stage, "Ready")  # Available -> Ready
		c.status = "In_Depot"
		c.save(ignore_permissions=True)
		self.assertEqual(c.inventory_stage, "In Depot")
		c.status = "Gate_Out"
		c.save(ignore_permissions=True)
		self.assertEqual(c.inventory_stage, "Departed")

	def test_gate_out_is_departed(self):
		c = _make_container("INVSTAGE002", status="Gate_Out")
		self.assertEqual(c.inventory_stage, "Departed")

	def test_booking_phantom_is_prearrival(self):
		# A pre-announced tank (phantom Container created by the booking) is Booked.
		customer = ensure_test_customer("InvStage Phantom Cust")
		make_contract(customer)
		booking = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": customer,
			"booking_status": "Confirmed",
			"items": [{"container_no": "INVPHANTOM1"}],
		}).insert(ignore_permissions=True)
		phantom = frappe.db.get_value(
			"Container", {"created_by_booking": booking.name}, ["status", "inventory_stage"], as_dict=True
		)
		self.assertEqual(phantom.status, "Booked")
		self.assertEqual(phantom.inventory_stage, "Pre-Arrival")

	def test_cancel_reverts_preexisting_container_stage(self):
		# A pre-existing tank flipped to Booked by a booking returns to Ready on cancel
		# (exercises the one direct set_value site in container_booking.py).
		customer = ensure_test_customer("InvStage Revert Cust")
		make_contract(customer)
		container = _make_container("INVREVERT01", status="Available").name
		booking = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": customer,
			"booking_status": "Confirmed",
			"items": [{"container": container, "container_no": "INVREVERT01"}],
		}).insert(ignore_permissions=True)
		flipped = frappe.db.get_value("Container", container, ["status", "inventory_stage"], as_dict=True)
		self.assertEqual(flipped.status, "Booked")
		self.assertEqual(flipped.inventory_stage, "Pre-Arrival")

		void_draft(booking.name)
		reverted = frappe.db.get_value("Container", container, ["status", "inventory_stage"], as_dict=True)
		self.assertEqual(reverted.status, "Available")
		self.assertEqual(reverted.inventory_stage, "Ready")
