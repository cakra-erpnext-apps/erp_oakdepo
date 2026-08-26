"""The field teams are told when work is HANDED to them, not when an order is created.

`setup_notification_rules` is add-only by design — an existing event_key belongs to the
admin — so the corrected `install.NOTIFICATION_RULES` reaches fresh sites only. This
carries the same change onto sites already running.

What was wrong with the old routing is not that the bell was dead (v0_76 fixed those); it
is that it rang too early. A Cleaning Order lands in Service Setup with no method picked, an
M&R draft lands unpriced and unapproved, an EIR-Out draft is provisioned the second an Order
Muat is submitted — in every case Admin Ops still stands between the document and any work
the crew may do. A crew rung at creation learns to chase orders that are not released yet,
and stops reading the bell that says the job is finally theirs.

	eir_submitted             Team EIR       — fires when an EIR is FINISHED; news to whoever
	                                           waits on the tank, not to the crew that
	                                           recorded it.
	order_muat_survey         Team EIR       — fires on the Order Muat submit itself.
	cleaning_order_created    Team Cleaning  — Service Setup: no method picked, nothing to work.
	repair_order_created      Team Repair    — unpriced draft, owner has not approved.
	repair_order_decided      Team Repair    — an owner's yes is not yet a dispatch; Admin Ops
	                                           forwards separately, so this rang twice per job.

What each team keeps instead:

	Team Cleaning  cleaning_order_forwarded  (new event, seeded by setup_notification_rules)
	Team Repair    repair_order_forwarded
	Team EIR       nothing — there is no Admin Ops handoff step in front of an EIR-Out, so by
	               the same rule there is no moment to ring. They work the /eir worklist.

Narrow on purpose, exactly like `v0_76.prune_dead_notification_recipients`: only these
(event, role) pairs are dropped, and only if still present. Every other recipient — including
any the admin added — is left alone, and a rule is never emptied (each keeps Admin Ops +
SPV Lapangan), so `validate` cannot refuse the save.
"""

import frappe

HANDOFF_ONLY = {
	"eir_submitted": ["Team EIR"],
	"order_muat_survey": ["Team EIR"],
	"cleaning_order_created": ["Team Cleaning"],
	"repair_order_created": ["Team Repair"],
	"repair_order_decided": ["Team Repair"],
}


def execute():
	if not frappe.db.exists("DocType", "Depot Notification Rule"):
		return  # release not migrated yet; setup_notification_rules seeds it correctly

	from container_depot.container_depot import notify
	from container_depot.install import setup_notification_rules

	# Seed `cleaning_order_forwarded` before pruning, so Team Cleaning is never momentarily
	# on no rule at all. Add-only, and a no-op once after_migrate has run.
	setup_notification_rules()

	changed = 0
	for event_key, roles in HANDOFF_ONLY.items():
		if not frappe.db.exists("Depot Notification Rule", event_key):
			continue
		doc = frappe.get_doc("Depot Notification Rule", event_key)
		keep = [r for r in doc.roles if r.role not in roles]
		if len(keep) == len(doc.roles):
			continue
		if not keep:
			# Should not happen (Admin Ops / SPV are never in HANDOFF_ONLY), but emptying an
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
