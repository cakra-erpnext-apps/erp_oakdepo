"""Presence-based Container status (replaces the old ordered state machine).

A container is in exactly one of four states — the status no longer encodes *what*
is being done to the tank (that lives on the related orders), only *where* it is:

* ``Booked``    — reserved by a Tank In booking, not yet physically at the gate.
* ``In_Depot``  — physically present with open work: a draft EIR-In, or an open
  Cleaning / Repair (M&R) order.
* ``Available`` — physically present and every related order is finished → ready
  to leave (the only state a Tank Out booking may submit from).
* ``Gate_Out``  — has left the depot.

There is no ordering/sequence: :func:`recompute_availability` simply flips a
*present* container between ``In_Depot`` and ``Available`` whenever an order
opens or closes. Booked / Gate_Out are driven explicitly by the gate + booking.
"""

from __future__ import annotations

import frappe

BOOKED = "Booked"
IN_DEPOT = "In_Depot"
AVAILABLE = "Available"
GATE_OUT = "Gate_Out"

# Statuses that mean the tank is physically in the depot right now.
PRESENT = (IN_DEPOT, AVAILABLE)

# Order states that still count as "open" (i.e. keep the container In_Depot).
_DONE_CLEANING = ("Completed", "Cancelled")
_DONE_REPAIR = ("Completed", "Cancelled", "Rejected")


def container_has_open_orders(container: str) -> bool:
    """True if the container still has an unfinished inbound-processing order.

    Open = a draft EIR-In (never submitted), a Cleaning Order that is not yet
    Completed/Cancelled, or a Repair (M&R) Order that is not yet Completed/
    Cancelled/Rejected. EIR-Out is deliberately excluded — it belongs to the
    outbound flow and must not drag a ready tank back to In_Depot.
    """
    if not container:
        return False
    if frappe.db.exists(
        "Inspection", {"container": container, "inspection_type": "EIR-In", "docstatus": 0}
    ):
        return True
    if frappe.db.exists(
        "Cleaning Order",
        {"container": container, "status": ["not in", _DONE_CLEANING], "docstatus": ["<", 2]},
    ):
        return True
    if frappe.db.exists(
        "Repair Order",
        {"container": container, "status": ["not in", _DONE_REPAIR], "docstatus": ["<", 2]},
    ):
        return True
    return False


def _set_status(container: str, status: str) -> None:
    """Persist ``Container.status`` (idempotent), bypassing the manual-transition
    guard since this is controller automation."""
    cur = frappe.db.get_value("Container", container, "status")
    if cur == status:
        return
    frappe.flags.in_status_automation = True
    try:
        doc = frappe.get_doc("Container", container)
        doc.status = status
        doc.save(ignore_permissions=True)
    finally:
        frappe.flags.in_status_automation = False


def mark_in_depot(container: str) -> None:
    """Gate-in: the tank is now physically present (work still pending)."""
    if container:
        _set_status(container, IN_DEPOT)


def mark_gate_out(container: str) -> None:
    """Gate-out: the tank has left the depot."""
    if container:
        _set_status(container, GATE_OUT)


def recompute_availability(container: str) -> None:
    """Flip a *present* container between In_Depot and Available based on whether
    any related order is still open. Booked / Gate_Out (and unknown) are left as-is
    — only a tank that is physically in the depot is recomputed."""
    if not container:
        return
    cur = frappe.db.get_value("Container", container, "status")
    if cur not in PRESENT:
        return
    target = IN_DEPOT if container_has_open_orders(container) else AVAILABLE
    if cur != target:
        _set_status(container, target)


def is_present(container: str) -> bool:
    """True if the container is currently physically in a depot (In_Depot/Available)."""
    return frappe.db.get_value("Container", container, "status") in PRESENT
