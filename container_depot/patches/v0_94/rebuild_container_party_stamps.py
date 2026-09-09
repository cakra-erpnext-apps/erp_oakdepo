"""Rebuild the Container master's EMKL / Shipper / Ex Vessel from the bons.

These three answer "who last hauled this tank, for which factory, off which vessel" — facts
the yard asks of the TANK, so they live on the master and are read-only there. They used to
be stamped straight through when a bon was submitted and never revisited, which is the exact
failure ``last_orders`` exists to prevent: voiding the bon left the master naming a haul that
never happened, and no later bon could correct it unless it happened to carry the same field.

They are recomputed from source now, like every other pointer in that module. This rebuilds
what the old writer left behind: a tank whose stamp came from a bon that has since been
cancelled is corrected to the last submitted bon that names one, and cleared when none does.

Idempotent — it is the same recompute the doc_events run, so re-running changes nothing.
"""

import frappe

from container_depot.container_depot.last_orders import refresh_container


def execute():
	frappe.reload_doc("container_depot", "doctype", "container")
	for i, name in enumerate(frappe.get_all("Container", pluck="name"), start=1):
		refresh_container(name)
		# A depot's Container table runs to tens of thousands; commit in batches so the patch
		# does not hold one transaction open across the whole fleet.
		if i % 500 == 0:
			frappe.db.commit()
	frappe.db.commit()
