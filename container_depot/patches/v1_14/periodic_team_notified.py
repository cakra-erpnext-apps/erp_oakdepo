"""Team Periodic menerima bel "M&R diteruskan ke team" untuk order Periodic Test.

`install.setup_notification_rules` tidak pernah menyentuh rule yang sudah ada, jadi role baru
ini harus ditambahkan ke rule `repair_order_forwarded` di sini. Team Repair tidak ikut menerima
bel Periodic Test (dan sebaliknya) — `notify.notify` menyaringnya lewat `mr_scope`.
"""

import frappe

ROLE = "Team Periodic"
EVENT = "repair_order_forwarded"


def execute():
	from container_depot.install import ensure_roles_exist

	ensure_roles_exist()  # the role must exist before a rule can link to it
	if not frappe.db.exists("Depot Notification Rule", EVENT):
		return
	rule = frappe.get_doc("Depot Notification Rule", EVENT)
	if ROLE in {r.role for r in rule.roles}:
		return
	rule.append("roles", {"role": ROLE})
	rule.save(ignore_permissions=True)
