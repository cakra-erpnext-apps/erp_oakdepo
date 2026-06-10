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
	# Pre-arrival: a tank reserved by a Container Booking but not yet physically
	# at the gate. Excluded from live inventory (see ess/inventory.py).
	"Booked": ["Gate_In", "Available"],
	# `Available` is the ready hub. The four redundant ready-cluster statuses
	# collapsed into it — the "why" (clean / certified / repaired) lives on the EIR,
	# Cleaning Certificate and Repair Order, not the status enum. From here a tank
	# re-enters the IN path (Gate_In) or takes the OUT path (Release DO →
	# Released_Pending_Pickup); the document created decides the direction.
	"Available": [
		"Gate_In", "Inspecting", "Pending_Survey", "Needs_Cleaning",
		"Booked", "Released_Pending_Pickup", "Gate_Out",
	],
	"Gate_In": ["Inspecting", "Needs_Cleaning", "Available", "Pending_Survey", "Gate_Out"],
	"Inspecting": ["Gate_In", "Needs_Cleaning", "Available", "Pending_Survey", "Awaiting_MR_Approval"],
	"Needs_Cleaning": ["Pending_Cleaning", "Cleaning_In_Progress"],
	"Pending_Cleaning": ["Cleaning_In_Progress"],
	"Cleaning_In_Progress": ["Cleaning_Completed"],
	"Cleaning_Completed": ["Pending_Survey", "Available"],
	"Pending_Survey": ["Survey_In_Progress"],
	"Survey_In_Progress": ["Available", "Awaiting_MR_Approval", "Awaiting_Recleaning_Approval"],
	"Awaiting_MR_Approval": ["Repair_In_Progress", "Pending_Survey"],
	"Repair_In_Progress": ["Pending_Survey", "Available"],
	"Awaiting_Recleaning_Approval": ["Recleaning_In_Progress", "Pending_Survey"],
	"Recleaning_In_Progress": ["Cleaning_Completed", "Pending_Survey"],
	"Released_Pending_Pickup": ["Gate_Out"],
	"Gate_Out": ["Available", "Gate_In"],
}


# ---------------------------------------------------------------------------
# Inventory stage — a legible grouping of the ~20 raw statuses into the eight
# monitoring buckets ops actually thinks in (Container Inventory dashboard +
# report). Stored on Container.inventory_stage, kept in step in
# Container.before_save via stage_for_status(). Single source of truth.
# ---------------------------------------------------------------------------

# Ordered for display (matches the physical In → process → Out flow).
INVENTORY_STAGES = [
	"Pre-Arrival",
	"Incoming",
	"Cleaning",
	"Survey",
	"Repair (M&R)",
	"Ready",
	"Outgoing",
	"Departed",
]

# Stages that count as physically present in the depo (everything but the
# pre-arrival reservation and a tank that has already gated out).
IN_DEPO_STAGES = ["Incoming", "Cleaning", "Survey", "Repair (M&R)", "Ready", "Outgoing"]

STAGE_BY_STATUS = {
	"Booked": "Pre-Arrival",
	"Gate_In": "Incoming",
	"Inspecting": "Incoming",
	"Needs_Cleaning": "Cleaning",
	"Pending_Cleaning": "Cleaning",
	"Cleaning_In_Progress": "Cleaning",
	"Awaiting_Recleaning_Approval": "Cleaning",
	"Recleaning_In_Progress": "Cleaning",
	"Cleaning_Completed": "Cleaning",
	"Pending_Survey": "Survey",
	"Survey_In_Progress": "Survey",
	"Awaiting_MR_Approval": "Repair (M&R)",
	"Repair_In_Progress": "Repair (M&R)",
	"Available": "Ready",
	"Released_Pending_Pickup": "Outgoing",
	"Gate_Out": "Departed",
}


def stage_for_status(status):
	"""Map a raw ``Container.status`` onto its monitoring stage.

	Returns ``None`` for an empty/unknown status so the caller can leave the
	field blank rather than invent a bucket.
	"""
	if not status:
		return None
	return STAGE_BY_STATUS.get(status)


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
