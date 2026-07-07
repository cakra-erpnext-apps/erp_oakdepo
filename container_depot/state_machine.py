"""Container status — presence-based, no ordering.

The raw ``Container.status`` Select is now one of four presence states (see
:mod:`container_depot.operations.container_status`):

    Booked → In_Depot ↔ Available → Gate_Out

There is deliberately **no sequence/transition enforcement** any more — the tank's
process detail (cleaning / repair / survey / EIR) lives on the related orders, not
the status. :func:`assert_transition` is kept as a no-op so existing callers keep
working; :func:`stage_for_status` still maps a status onto a coarse monitoring
bucket for the inventory dashboard/report.
"""

from __future__ import annotations

# Ordered for display (In → present → Out).
INVENTORY_STAGES = ["Pre-Arrival", "In Depot", "Ready", "Departed"]

# Stages that count as physically present in the depo.
IN_DEPO_STAGES = ["In Depot", "Ready"]

STAGE_BY_STATUS = {
	"Booked": "Pre-Arrival",
	"In_Depot": "In Depot",
	"Available": "Ready",
	"Gate_Out": "Departed",
}


def stage_for_status(status):
	"""Map a raw ``Container.status`` onto its monitoring stage (or ``None``)."""
	if not status:
		return None
	return STAGE_BY_STATUS.get(status)


def is_allowed(old, new) -> bool:
	"""No sequence any more — every transition is allowed."""
	return True


def assert_transition(old, new) -> None:
	"""Kept as a no-op: status transitions are unrestricted now."""
	return
