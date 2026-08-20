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


# The parent booking every Booking Code fixture hangs off. A placeholder tank, reused on
# purpose so the fixtures stay cheap — see the cleanup in make_booking_code.
_PLACEHOLDER_TANK = "TANK0009999"


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
	# One live booking per tank (ContainerBooking._validate_no_open_booking). This helper
	# always parks its parent booking on the same placeholder tank, so the previous one it
	# made has to go first — the number is used by nothing else, so nothing real is hit.
	stale = frappe.get_all(
		"Container Booking Item", filters={"container_no": _PLACEHOLDER_TANK}, pluck="parent"
	)
	if stale:
		frappe.db.delete("Booking Code", {"booking": ("in", stale)})
		frappe.db.delete("Container Booking Item", {"parent": ("in", stale)})
		frappe.db.delete("Container Booking", {"name": ("in", stale)})
	booking = frappe.get_doc({
		"doctype": "Container Booking",
		"direction": "Tank In",
		"customer": customer,
		"contract": contract_name,
		"booking_status": "Confirmed",
		"items": [{"container_no": _PLACEHOLDER_TANK}],
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


def cancel_submitted_booking(booking: str) -> str:
	"""Cancel a SUBMITTED Container Booking the only way the app still allows.

	``before_cancel`` refuses a direct cancel at docstatus 1 (as ``before_update_after_submit``
	refuses every edit): what Submit set in motion is undone by stepping back through
	**Kembali ke Draft** and cancelling the draft. ``void_draft`` unwinds exactly what the old
	direct cancel did — invoice cancelled and kept linked, reservations released, codes voided.

	Refused, correctly, once a bon has been raised or a code has been used at the gate — a
	test that needs that case should assert the refusal rather than call this.
	"""
	from container_depot.container_depot.doctype.container_booking.container_booking import (
		revert_booking_to_draft,
		void_draft,
	)

	revert_booking_to_draft(booking)
	return void_draft(booking)
