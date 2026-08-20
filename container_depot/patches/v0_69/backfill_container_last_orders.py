"""Fill the Container master's "last order of each kind" cache for tanks that already exist.

The pointers are maintained from here on by doc_events (see ``last_orders.py``), but every
Container written before those hooks existed has them empty — including
``last_order_bongkar``, which was declared on the doctype long ago and never written by
anything, so it sat half-filled from old seed data.

Rebuilt from source, one tank at a time, so the result is identical to what the hooks would
have produced had they always been there.
"""

import frappe

from container_depot.container_depot.last_orders import refresh_container


def execute():
	frappe.reload_doc("container_depot", "doctype", "container")
	containers = frappe.get_all("Container", pluck="name")
	for i, name in enumerate(containers, start=1):
		refresh_container(name)
		# A depot's Container table runs to tens of thousands; commit in batches so the patch
		# does not hold one transaction open across the whole fleet.
		if i % 500 == 0:
			frappe.db.commit()
	frappe.db.commit()
