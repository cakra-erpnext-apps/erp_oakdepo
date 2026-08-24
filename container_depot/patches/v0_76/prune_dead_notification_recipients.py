"""Remove recipients who were routed an event they can never open.

`setup_notification_rules` is add-only by design — an existing event_key belongs to the
admin — so the corrected `install.NOTIFICATION_RULES` reaches fresh sites only. These three
rows were wrong at seed time, not tuned by anyone, and each one produced the same failure:
the bell rings, the operator taps, and the PWA answers "Anda tidak punya akses ke menu ini"
because the menu behind the route is gated on a permission that role does not hold.

	eir_submitted      Team Cleaning, Team Repair  — Inspection is read-only for them; `/eir`
	                                                 needs write. The EIR that concerns them
	                                                 already fires cleaning_order_created /
	                                                 repair_order_created.
	order_muat_survey  Team Survey                 — this is the EIR-Out, not the position
	                                                 survey; they hold no Inspection perm.

Narrow on purpose: only these exact (event, role) pairs are dropped, and only if still
present. Every other recipient — including any the admin added — is left alone, and a rule
is never emptied (each keeps Admin Ops + SPV Lapangan), so `validate` cannot refuse the save.

Team Kalmar is deliberately NOT pruned from the gate events: they genuinely work gate-out, so
the fix there runs the other way — `v0_76.kalmar_gate_access` grants them the menu.
"""

import frappe

DEAD_RECIPIENTS = {
	"eir_submitted": ["Team Cleaning", "Team Repair"],
	"order_muat_survey": ["Team Survey"],
}


def execute():
	if not frappe.db.exists("DocType", "Depot Notification Rule"):
		return  # release not migrated yet; setup_notification_rules seeds it correctly

	from container_depot.container_depot import notify

	changed = 0
	for event_key, roles in DEAD_RECIPIENTS.items():
		if not frappe.db.exists("Depot Notification Rule", event_key):
			continue
		doc = frappe.get_doc("Depot Notification Rule", event_key)
		keep = [r for r in doc.roles if r.role not in roles]
		if len(keep) == len(doc.roles):
			continue
		if not keep:
			# Should not happen (Admin Ops / SPV are never in DEAD_RECIPIENTS), but emptying an
			# enabled rule silently stops the event instead of fixing it. Leave it to a human.
			print(f"skip {event_key}: pruning would leave nobody")
			continue
		dropped = [r.role for r in doc.roles if r.role in roles]
		doc.roles = []
		for row in keep:
			doc.append("roles", {"role": row.role})
		doc.save(ignore_permissions=True)
		changed += 1
		print(f"{event_key}: dropped {', '.join(dropped)}")

	if changed:
		notify.clear_rule_cache()
		frappe.db.commit()
