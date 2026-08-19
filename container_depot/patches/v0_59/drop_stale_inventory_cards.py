"""Delete the two Number Cards that count a Container stage which no longer exists.

``Tanks In Cleaning`` (``inventory_stage = Cleaning``) and ``Tanks In Survey or
Repair`` (``Survey`` / ``Repair (M&R)``) were seeded when ``inventory_stage`` still
carried the work detail. The stage Select is presence-based now (Pre-Arrival / In
Depot / Ready / Departed — see :mod:`container_depot.state_machine`), so both cards
have been reading a hard zero ever since: worse than no card, because a zero looks
like an answer. Their replacements count the orders themselves (``Cleaning Order
Aktif`` / ``M&R Aktif``, seeded by ``install.setup_inventory_dashboard``).

Deleting the record — not just unlinking it from the workspace — is deliberate: a
Number Card left behind stays offerable in the "Add Card" picker, which is exactly
how a dead card gets put back on a dashboard.

Idempotent + best-effort: a missing card is a no-op, and a delete that fails (a card
someone pinned to their own workspace) is logged, never fatal.
"""

from __future__ import annotations

import frappe

_CARDS = ["Tanks In Cleaning", "Tanks In Survey or Repair"]


def execute():
	dropped = []
	for card in _CARDS:
		if not frappe.db.exists("Number Card", card):
			continue
		try:
			# Detach from every workspace first — a Workspace Number Card child row
			# holds a link that would otherwise block the delete.
			frappe.db.delete("Workspace Number Card", {"number_card_name": card})
			frappe.delete_doc("Number Card", card, force=True, ignore_permissions=True)
			dropped.append(card)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"drop number card {card}")

	frappe.db.commit()
	if dropped:
		print(f"[container_depot] v0_59: dropped stale number cards: {', '.join(dropped)}")
