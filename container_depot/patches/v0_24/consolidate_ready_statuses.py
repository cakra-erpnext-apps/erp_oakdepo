"""Collapse the four redundant "ready" statuses into `Available`.

`Empty_Clean`, `Cleaning_Cert_Issued`, `Ready_For_Service` and `Ready_For_Release`
all meant "the tank is ready" — the actual reason (clean / certified / repaired)
lives on the EIR, Cleaning Certificate and Repair Order, not on the status enum.
They are merged into a single `Available`. `Released_Pending_Pickup` is NOT touched
(it stays the distinct "Release DO issued, queued to leave" marker).

Raw SQL on purpose: it bypasses both the transition guard and the Select
validation, so it is safe even though the four options were just removed from the
Container DocType during the same migrate (patches run after model sync).

Idempotent: a re-run matches no rows once the statuses are gone. Historical
`Container Movement` / `Container Activity` from/to_status text is left as-is
(free-text audit trail).
"""

import frappe

OLD_TO_NEW = {
	"Empty_Clean": "Available",
	"Cleaning_Cert_Issued": "Available",
	"Ready_For_Service": "Available",
	"Ready_For_Release": "Available",
}


def execute():
	for old, new in OLD_TO_NEW.items():
		frappe.db.sql(
			"UPDATE `tabContainer` SET status=%s, inventory_stage=%s WHERE status=%s",
			(new, "Ready", old),
		)
	frappe.db.commit()
