"""Phase 8 (B1) tests: new fields on existing doctypes.

Schema-only assertions (run via `bench run-tests`) that the portal-required
fields were added to the existing doctypes with the right type/options.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase


class TestB1Fields(FrappeTestCase):
	def _assert_field(self, doctype, fieldname, fieldtype=None, options_contains=None):
		field = frappe.get_meta(doctype).get_field(fieldname)
		self.assertIsNotNone(field, f"{doctype}.{fieldname} missing")
		if fieldtype:
			self.assertEqual(field.fieldtype, fieldtype, f"{doctype}.{fieldname} wrong type")
		if options_contains:
			for opt in options_contains:
				self.assertIn(opt, (field.options or ""), f"{doctype}.{fieldname} missing option {opt}")

	def test_isotank_booking_fields(self):
		# Shipping line lives on the Container master, not the booking.
		self._assert_field("Isotank Booking", "do_reference", "Data")
		self._assert_field("Isotank Booking", "do_document", "Attach")

	def test_isotank_booking_item_fields(self):
		# Vehicle fields use the depot's paperwork vocabulary (truck_plate / supir).
		self._assert_field("Isotank Booking Item", "truck_plate", "Data")
		self._assert_field("Isotank Booking Item", "driver", "Data")
		self._assert_field("Isotank Booking Item", "driver_phone", "Data")
		# Per-container bongkar / order info.
		self._assert_field("Isotank Booking Item", "ro", "Data")
		self._assert_field("Isotank Booking Item", "tanggal_bongkar", "Date")
		self._assert_field("Isotank Booking Item", "shipper", "Link", ["Customer"])
		self._assert_field("Isotank Booking Item", "ex_vessel", "Data")
		self._assert_field("Isotank Booking Item", "angkutan", "Link", ["Customer"])
		self._assert_field("Isotank Booking Item", "condition", "Select", ["Empty", "Laden"])
		self._assert_field("Isotank Booking Item", "gate_in", "Datetime")
		self._assert_field("Isotank Booking Item", "gate_out", "Datetime")
		self._assert_field("Isotank Booking Item", "eir", "Link", ["Inspection"])
		self._assert_field("Isotank Booking Item", "item_status", "Select", ["Pending", "In Yard", "Completed"])

	def test_order_fields(self):
		# Orders are operational bons now (no billing fields). They reference a
		# booking, a shipper, and carry containers in a child table.
		for dt in ("Order Bongkar", "Order Muat"):
			self._assert_field(dt, "booking", "Link", ["Isotank Booking"])
			self._assert_field(dt, "shipper", "Link", ["Customer"])
			self._assert_field(dt, "ro", "Data")
			self._assert_field(dt, "angkutan", "Data")
			self._assert_field(dt, "containers", "Table", ["Order Container Item"])
		self._assert_field("Order Bongkar", "tanggal_bongkar", "Date")
		self._assert_field("Order Muat", "tanggal_muat", "Date")
		self._assert_field("Order Muat", "destination", "Data")
		# Per-container remarks + cleaning cert live on the child table.
		self._assert_field("Order Container Item", "remarks", "Data")
		self._assert_field("Order Container Item", "cleaning_certificate", "Link", ["Cleaning Certificate"])

	def test_container_seal_and_shipper_fields(self):
		for seal in ("seal_manhole", "seal_airline", "seal_bottom_outlet", "seal_top_discharge", "seal_vapour_valve"):
			self._assert_field("Container", seal, "Data")
		self._assert_field("Container", "shipper", "Link", ["Customer"])

	def test_inspection_survey_and_seal_fields(self):
		self._assert_field("Inspection", "survey_type", "Select", ["Cleanliness Survey", "M&R Pre-Inspection"])
		self._assert_field("Inspection", "priority", "Select", ["High", "Medium", "Low"])
		self._assert_field("Inspection", "deadline", "Date")
		self._assert_field("Inspection", "requested_by", "Data")
		self._assert_field("Inspection", "tank_owner", "Link", ["Customer"])
		for seal in ("seal_manhole", "seal_airline", "seal_bottom_outlet", "seal_top_discharge", "seal_vapour_valve"):
			self._assert_field("Inspection", seal, "Data")

	def test_cleaning_order_approval_fields(self):
		self._assert_field("Cleaning Order", "approval_status", "Select", ["Pending", "Approved", "Rejected"])
		self._assert_field("Cleaning Order", "is_recleaning", "Check")
