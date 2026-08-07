"""Shared test fixtures for the Booking Code → Order flow.

Kept dependency-light (no import of other test modules) so it can be imported
from any test file without risking an import cycle. Callers pass an already
resolved Customer name (e.g. via ``ensure_test_customer``).
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, add_to_date, now_datetime, today

from container_depot.container_depot.doctype.booking_code.booking_code import generate_code


def make_contract(customer: str) -> str:
	"""Return an Active Depot Contract for ``customer``, creating one if needed."""
	existing = frappe.db.get_value(
		"Depot Contract", {"customer": customer, "status": "Active"}, "name"
	)
	if existing:
		return existing
	return frappe.get_doc({
		"doctype": "Depot Contract",
		"customer": customer,
		"currency": "IDR",
		"status": "Active",
		"payment_type": "Cash",
		"valid_from": today(),
		"valid_to": add_days(today(), 365),
		"tariff_lines": [{"item": "Lift Off", "rate": 250000}],
	}).insert(ignore_permissions=True).name


def make_booking_code(
	*,
	customer: str,
	container_no: str,
	direction: str = "Tank In",
	container: str | None = None,
	state: str = "Active",
	offset_hours: int = 24,
):
	"""Create a fresh Container Booking + Booking Code per call.

	Inlining the booking (rather than caching it across tests) avoids stale
	names after FrappeTestCase rolls back per-test transactions. The parent
	booking is always Tank In to dodge Tank-Out gating — the Booking Code
	carries its own ``direction`` and that is what the gate/SST checks.
	"""
	contract_name = make_contract(customer)
	booking = frappe.get_doc({
		"doctype": "Container Booking",
		"direction": "Tank In",
		"customer": customer,
		"contract": contract_name,
		"booking_status": "Confirmed",
		"items": [{"container_no": "TANK0009999"}],
	}).insert(ignore_permissions=True)
	return frappe.get_doc({
		"doctype": "Booking Code",
		"code": generate_code(),
		"booking": booking.name,
		"direction": direction,
		"container_no": container_no,
		"container": container,
		"state": state,
		"issued_at": now_datetime(),
		"expires_at": add_to_date(now_datetime(), hours=offset_hours),
	}).insert(ignore_permissions=True)
