"""Seed Container Activity from existing Container Movement status events.

Container Activity is new, so existing tanks have no history feed. Container
Movement already holds every past status transition (with timestamp + actor),
so map those into baseline ``Status Change`` activities — one per movement,
linked back to the movement row. Fuller backfill from each action doctype
(Inspection / Cleaning / Repair …) is out of scope.

Idempotent: skips a movement that already has a Container Activity referencing
it. Runs post_model_sync (the Container Activity table must exist).
"""

import frappe


def execute():
	if not frappe.db.table_exists("Container Activity"):
		return

	movements = frappe.db.sql(
		"""
		SELECT m.name, m.container, m.movement_timestamp, m.from_status, m.to_status, m.moved_by
		FROM `tabContainer Movement` m
		WHERE m.container IS NOT NULL AND m.container != ''
		  AND EXISTS (SELECT 1 FROM `tabContainer` c WHERE c.name = m.container)
		  AND NOT EXISTS (
		      SELECT 1 FROM `tabContainer Activity` a
		      WHERE a.reference_doctype = 'Container Movement' AND a.reference_name = m.name
		  )
		""",
		as_dict=True,
	)
	if not movements:
		return

	# Denormalize principal/depot per container once.
	containers = {m.container for m in movements}
	meta = {
		c: (p, d)
		for c, p, d in frappe.db.sql(
			"""SELECT name, principal, depot FROM `tabContainer` WHERE name IN %(c)s""",
			{"c": tuple(containers)},
		)
	}

	for m in movements:
		principal, depot = meta.get(m.container, (None, None))
		frappe.get_doc({
			"doctype": "Container Activity",
			"container": m.container,
			"activity_time": m.movement_timestamp,
			"activity_type": "Status Change",
			"reference_doctype": "Container Movement",
			"reference_name": m.name,
			"from_status": m.from_status,
			"to_status": m.to_status,
			"performed_by": m.moved_by,
			"principal": principal,
			"depot": depot,
			"summary": f"{m.from_status or '—'} → {m.to_status or '—'}",
		}).insert(ignore_permissions=True)

	frappe.db.commit()
