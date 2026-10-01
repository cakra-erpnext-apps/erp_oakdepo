"""Team Survey ikut mengerjakan Periodic Test (permintaan mandor 2026-10-01).

Izin Repair Order / Charge Template untuk Team Survey masuk sendiri lewat
`install.setup_permissions` (baris yang belum ada selalu ditambahkan). Rule notifikasi
tidak: `setup_notification_rules` tidak pernah menyentuh rule yang sudah ada, jadi role ini
ditambahkan ke `repair_order_forwarded` di sini. `notify.notify` menyaringnya lewat
`mr_scope`, jadi Team Survey hanya menerima bel untuk order Periodic Test.
"""

import frappe

ROLE = "Team Survey"
EVENT = "repair_order_forwarded"


def execute():
	if not frappe.db.exists("Depot Notification Rule", EVENT):
		return
	rule = frappe.get_doc("Depot Notification Rule", EVENT)
	if ROLE in {r.role for r in rule.roles}:
		return
	rule.append("roles", {"role": ROLE})
	rule.save(ignore_permissions=True)
