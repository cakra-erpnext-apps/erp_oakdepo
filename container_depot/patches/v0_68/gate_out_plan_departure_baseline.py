"""Gate Out Plan rows used to read "Keluar" straight off ``Container.status == Gate_Out``.

That status also covers a tank that was NEVER in the yard — the doctype's own default, and
what an imported / bulk-injected master carries until it gates in. A plan listing such a
tank was born 100% collected: no booking button, and the auto-close only fires on a real
gate-out that never comes, so the plan can never be worked or closed.

Rows now carry a baseline (``was_out``) saying where the tank stood when it was listed, and
only report the change. This backfills that baseline for rows written before the rule.

Only plans that could not have sent a tank out are touched: still open (not Fulfilled) and
with no Container Booking raised from them. A plan that produced a booking really did
collect its tanks, so its history is left exactly as it stands.
"""

import frappe

from container_depot.container_depot.doctype.gate_out_plan.gate_out_plan import (
	refresh_plan_fulfilment,
)


def execute():
	frappe.reload_doc("container_depot", "doctype", "gate_out_plan_item")

	booked = {
		b.gate_out_plan
		for b in frappe.get_all(
			"Container Booking", filters={"gate_out_plan": ["is", "set"]}, fields=["gate_out_plan"]
		)
	}
	plans = [
		p
		for p in frappe.get_all("Gate Out Plan", filters={"status": ["!=", "Fulfilled"]}, pluck="name")
		if p not in booked
	]
	if not plans:
		return

	rows = frappe.get_all(
		"Gate Out Plan Item",
		filters={"parent": ["in", plans], "parenttype": "Gate Out Plan", "container": ["is", "set"]},
		fields=["name", "parent", "container"],
	)
	if not rows:
		return

	away = set(
		frappe.get_all(
			"Container",
			filters={"name": ["in", [r.container for r in rows]], "status": "Gate_Out"},
			pluck="name",
		)
	)
	touched = set()
	for r in rows:
		if r.container not in away:
			continue
		frappe.db.set_value(
			"Gate Out Plan Item", r.name, {"was_out": 1, "gated_out": 0}, update_modified=False
		)
		touched.add(r.parent)

	# Rewrite each affected plan's % Keluar from the corrected rows.
	for plan in touched:
		refresh_plan_fulfilment(plan)
