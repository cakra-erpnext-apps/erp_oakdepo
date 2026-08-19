"""Drop the "Siap Keluar" (ACC Gate Out) step.

A tank is out the moment its EIR-Out is reviewed and submitted clean — that approval is now
the only thing that declares a departure (``Inspection.on_submit`` -> ``gate.mark_gate_out``).
The reminder queue that used to sit between the two, and the operator-pressed ACC that closed
it, are gone: the PWA menu (``readyOut``), its Desk twin (the "Container Siap Keluar" query
report) and the now-never-fired ``ready_to_load`` notification rule all go with them.

Only leftovers on the site are removed here — the code, the menu entry and the workspace
links are already gone from disk.
"""

import frappe


def execute():
	if frappe.db.exists("Report", "Container Siap Keluar"):
		# force: the report's folder is already gone, so the standard-report guard has
		# nothing left to protect.
		frappe.delete_doc("Report", "Container Siap Keluar", force=True, ignore_missing=True)

	# The rule is seeded add-only (install.setup_notification_rules), so dropping the seed
	# entry alone would leave this row routing an event nothing fires any more.
	if frappe.db.exists("Depot Notification Rule", "ready_to_load"):
		frappe.delete_doc("Depot Notification Rule", "ready_to_load", force=True, ignore_missing=True)

	frappe.db.commit()
