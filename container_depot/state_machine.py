"""Canonical Container status state machine.

The raw ``Container.status`` Select is the single stored lifecycle state. The
customer portal's human-readable labels (e.g. "Waiting for Survey") are a
*presentation* concern and never stored — every stored value is one of the
machine codes in :data:`CONTAINER_TRANSITIONS` below.

Enforcement is deliberately tolerant so it never blocks internal automation or
legacy data:

* A brand-new document (no previous status) is always allowed.
* A no-op save (status unchanged) is always allowed.
* When ``frappe.flags.in_status_automation`` is set, the guard is bypassed —
  controllers that legitimately drive the container (Repair Order, Inspection,
  Cleaning Order, Release DO) wrap their ``container.save()`` in this flag, and
  data-migration patches set it too.
* An *unknown* source status (e.g. a value left over from before this machine
  existed) is allowed through, so a stale row can always transition forward.

Only a known→known transition that is not in the allowed set raises.
"""

from __future__ import annotations

import frappe
from frappe import _

# source status -> set of allowed next statuses.
# Edges cover the customer lifecycle (survey/M&R/re-cleaning/release) plus the
# internal gate-ops moves that existing controllers and tests perform.
CONTAINER_TRANSITIONS = {
	# Pre-arrival: a tank reserved by an Isotank Booking but not yet physically
	# at the gate. Excluded from live inventory (see ess/inventory.py).
	"Booked": ["Gate_In", "Available"],
	"Available": ["Gate_In", "Inspecting", "Pending_Survey", "Needs_Cleaning", "Empty_Clean", "Booked"],
	"Gate_In": ["Inspecting", "Needs_Cleaning", "Empty_Clean", "Pending_Survey", "Available", "Gate_Out"],
	"Inspecting": ["Gate_In", "Needs_Cleaning", "Empty_Clean", "Pending_Survey", "Awaiting_MR_Approval", "Available"],
	"Empty_Clean": ["Pending_Survey", "Ready_For_Release", "Gate_Out"],
	"Needs_Cleaning": ["Pending_Cleaning", "Cleaning_In_Progress"],
	"Pending_Cleaning": ["Cleaning_In_Progress"],
	"Cleaning_In_Progress": ["Cleaning_Completed"],
	"Cleaning_Completed": ["Pending_Survey", "Ready_For_Release"],
	"Pending_Survey": ["Survey_In_Progress"],
	"Survey_In_Progress": [
		"Cleaning_Cert_Issued",
		"Awaiting_MR_Approval",
		"Awaiting_Recleaning_Approval",
		"Ready_For_Release",
	],
	"Awaiting_MR_Approval": ["Repair_In_Progress", "Pending_Survey"],
	"Repair_In_Progress": ["Pending_Survey", "Cleaning_Cert_Issued", "Ready_For_Release", "Ready_For_Service"],
	"Awaiting_Recleaning_Approval": ["Recleaning_In_Progress", "Pending_Survey"],
	"Recleaning_In_Progress": ["Cleaning_Completed", "Pending_Survey"],
	"Cleaning_Cert_Issued": ["Ready_For_Release"],
	"Ready_For_Release": ["Released_Pending_Pickup", "Gate_Out"],
	"Released_Pending_Pickup": ["Gate_Out"],
	"Gate_Out": ["Available", "Gate_In"],
	# Retained synonym for repair/cleaning completion (collapses to `ready`).
	"Ready_For_Service": ["Ready_For_Release", "Gate_Out", "Available", "Pending_Survey"],
}


def is_allowed(old, new) -> bool:
	"""Pure predicate: may a container move from ``old`` to ``new``?"""
	if not old or old == new:
		return True
	if old not in CONTAINER_TRANSITIONS:
		return True
	return new in CONTAINER_TRANSITIONS[old]


def assert_transition(old, new) -> None:
	"""Raise ``frappe.ValidationError`` on an illegal manual status transition.

	Bypassed entirely when ``frappe.flags.in_status_automation`` is set.
	"""
	if getattr(frappe.flags, "in_status_automation", False):
		return
	if is_allowed(old, new):
		return
	frappe.throw(
		_("Illegal container status transition: {0} → {1}.").format(old, new),
		frappe.ValidationError,
	)
