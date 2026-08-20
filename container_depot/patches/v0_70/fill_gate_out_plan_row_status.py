"""Fill the Container status now mirrored on each Gate Out Plan row.

``container_status`` fetches from the Container master, which Frappe refreshes on every
save — but rows written before the field existed hold nothing until their plan happens to
be saved again. An empty status is not harmless here: the "which tanks am I booking?"
picker reads it to pre-tick the tanks that are Available, so on an untouched plan it would
offer nothing and read as "no tank is ready".
"""

import frappe


def execute():
	frappe.reload_doc("container_depot", "doctype", "gate_out_plan_item")
	rows = frappe.get_all(
		"Gate Out Plan Item",
		filters={"parenttype": "Gate Out Plan", "container": ["is", "set"]},
		fields=["name", "container"],
	)
	if not rows:
		return
	status = {
		c.name: c.status
		for c in frappe.get_all(
			"Container",
			filters={"name": ["in", list({r.container for r in rows})]},
			fields=["name", "status"],
		)
	}
	for r in rows:
		frappe.db.set_value(
			"Gate Out Plan Item", r.name, "container_status", status.get(r.container),
			update_modified=False,
		)
