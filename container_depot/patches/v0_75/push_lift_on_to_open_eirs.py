"""Give every OPEN order of a planned tank its ``target_lift_on`` — the draft EIR included.

``Gate Out Plan`` stamps a tank with the date the customer is coming, and mirrors it onto the
orders still holding that tank so the worklists can sort and badge by urgency. The mirror
named Cleaning and M&R itself, so it never reached the EIR — which is both the most common
thing holding a tank that has just arrived and something the plan was ALREADY reporting as a
blocker. A tank could read "Belum: EIR-In" on the plan while the surveyor's own worklist
showed no urgency at all; and where the EIR was the only open work, the plan looked like it
did nothing.

``_push_to_open_orders`` now drives off ``container_open_orders`` (one definition of "belum
selesai" for the whole app) and ``Inspection`` has gained the field. This backfills what the
old mirror skipped: every container currently carrying a stamp re-pushes it to its open work.

Idempotent — it writes the same value the live code would.
"""

from __future__ import annotations

import frappe


def execute():
	frappe.reload_doc("container_depot", "doctype", "inspection")
	from container_depot.container_depot.doctype.gate_out_plan.gate_out_plan import (
		_push_to_open_orders,
	)

	for c in frappe.get_all(
		"Container", filters={"target_lift_on": ["is", "set"]}, fields=["name", "target_lift_on"]
	):
		_push_to_open_orders(c.name, c.target_lift_on)
