"""Move M&R evidence photos out of the estimate line and into their own table.

``Repair Used Item.photos`` held a JSON array of file URLs on the same row as the item, the
quantity and the price. Two things were wrong with that. The estimate row is what the owner
reads their bill from, and it was already eleven columns wide before a photo column could be
considered; and the two have different lifetimes — the estimate freezes when it leaves Draft,
while the evidence is gathered days later while the repair is happening.

So the photos now live in ``Repair Order.work_photos`` (``Repair Work Photo``), one row per
photo, each pointing back at the line it proves. This patch carries the old ones across.

The old column is left in place but emptied. Frappe never drops a column, and a JSON blob
sitting there full of URLs that nothing reads is how a second, stale source of the same
photos survives a rebuild — the album would then disagree with the row and nobody could say
which was right.

Idempotent: a row already emptied is skipped, and a photo already in the album is not
duplicated.
"""

from __future__ import annotations

import json

import frappe


def execute():
	if not frappe.db.table_exists("Repair Work Photo"):
		return
	# Raw SQL on purpose: `photos` is gone from the doctype JSON by the time this runs, so the
	# ORM no longer knows the column — the table still does.
	try:
		rows = frappe.db.sql(
			"""
			SELECT name, parent, item, photos
			FROM `tabRepair Used Item`
			WHERE photos IS NOT NULL AND photos != '' AND parenttype = 'Repair Order'
			""",
			as_dict=True,
		)
	except Exception:
		return  # column already dropped by a rebuild — nothing to carry
	if not rows:
		return

	# What the album already holds, so a re-run adds nothing twice.
	seen = {
		(p.parent, p.photo)
		for p in frappe.get_all("Repair Work Photo", fields=["parent", "photo"], limit_page_length=0)
	}
	moved = 0
	for r in rows:
		try:
			photos = json.loads(r.photos)
		except Exception:
			photos = []
		for url in photos if isinstance(photos, list) else []:
			if not url or (r.parent, url) in seen:
				continue
			frappe.get_doc({
				"doctype": "Repair Work Photo",
				"parent": r.parent,
				"parenttype": "Repair Order",
				"parentfield": "work_photos",
				"photo": url,
				"item": r.item,
				"used_item": r.name,
			}).insert(ignore_permissions=True)
			seen.add((r.parent, url))
			moved += 1
	frappe.db.sql("UPDATE `tabRepair Used Item` SET photos = NULL WHERE photos IS NOT NULL AND photos != ''")
	frappe.db.commit()
	print(f"Moved {moved} M&R evidence photo(s) into Repair Work Photo")
