"""Presence-based Container status (replaces the old ordered state machine).

A container is in exactly one of four states — the status no longer encodes *what*
is being done to the tank (that lives on the related orders), only *where* it is:

* ``Booked``    — reserved by a Tank In booking, not yet physically at the gate.
* ``In_Depot``  — physically present with open work: a draft EIR-In, or an open
  Cleaning / Repair (M&R) / Periodic Test order.
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
# Periodic Test Order shares the M&R owner-approval machine — same terminal set.
_DONE_PERIODIC = ("Completed", "Cancelled", "Rejected")


def container_open_orders(container: str) -> list[dict]:
    """Every unfinished order still holding the container, newest first.

    Open = a draft EIR-In (never submitted), a Cleaning Order not yet Completed/
    Cancelled, a Repair (M&R) Order not yet Completed/Cancelled/Rejected, or a
    Periodic Test Order not yet Completed/Cancelled/Rejected. Any of these is work
    that must finish before the tank may leave, so it keeps the tank In_Depot (and
    thus blocks a Tank Out booking + the gate-out). EIR-Out is deliberately excluded
    — it belongs to the outbound flow and must not drag a ready tank back to In_Depot.

    This is the single source of truth for "is the tank ready to leave", and it answers
    with the actual work rather than a yes/no: an operator told *which* order is holding
    the tank can go and finish it, where "not ready" only tells them to go hunting.

    Note what is NOT here: an order that was never raised. A tank that needed no cleaning
    has no cleaning to finish, so nothing holds it — readiness is the ABSENCE of open work,
    never the presence of a completed record.

    Returns ``[{doctype, name, label, status}]`` — empty when the tank is free to go.
    """
    if not container:
        return []
    out = []
    for row in frappe.get_all(
        "Inspection",
        filters={"container": container, "inspection_type": "EIR-In", "docstatus": 0},
        fields=["name", "modified"],
        order_by="modified desc",
    ):
        out.append({"doctype": "Inspection", "name": row.name, "label": "EIR-In", "status": "Draft"})
    for doctype, done, label in (
        ("Cleaning Order", _DONE_CLEANING, "Cleaning"),
        ("Repair Order", _DONE_REPAIR, "M&R"),
        ("Periodic Test Order", _DONE_PERIODIC, "Periodic Test"),
    ):
        for row in frappe.get_all(
            doctype,
            filters={"container": container, "status": ["not in", done], "docstatus": ["<", 2]},
            fields=["name", "status"],
            order_by="modified desc",
        ):
            out.append(
                {"doctype": doctype, "name": row.name, "label": label, "status": row.status}
            )
    return out


def container_has_open_orders(container: str) -> bool:
    """True if the container still has an unfinished processing order."""
    return bool(container_open_orders(container))


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
    """Gate-in: the tank is now physically present.

    Present is not the same as busy. Parking every arrival on ``In_Depot`` and waiting for
    an order to flip it left a tank that needed NO work stranded there forever — nothing
    ever recomputed it, so a clean tank could never leave. So the arrival settles on the
    computed state: In_Depot when something is already open, Available when nothing is.
    An EIR/cleaning raised a moment later flips it back through its own hook.
    """
    if not container:
        return
    _set_status(container, IN_DEPOT if container_has_open_orders(container) else AVAILABLE)


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
