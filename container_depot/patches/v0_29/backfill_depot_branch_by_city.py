"""Fill any Depot whose ``branch`` is still blank, matching by city.

Depot Storage recommends placement zones across sibling depots of the SAME
branch. That fallback needs every depot to carry a branch. The v0_19 backfill
only auto-assigned a branch when the site had exactly one Branch; multi-branch
sites (e.g. Medan + Surabaya) left some depots — notably KIM11 — with a null
branch, which blocked the per-branch zone recommendation.

Heuristic: pick the Branch whose name contains the depot's city (case-insensitive).
Idempotent and best-effort — depots without a city or a matching branch are left
untouched for manual assignment.
"""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.has_column("Depot", "branch"):
		return

	branches = frappe.get_all("Branch", pluck="name")
	if not branches:
		return

	rows = frappe.get_all(
		"Depot", filters={"branch": ["in", ["", None]]}, fields=["name", "city"]
	)
	filled = 0
	for d in rows:
		if not d.city:
			continue
		match = next((b for b in branches if d.city.lower() in (b or "").lower()), None)
		if match:
			frappe.db.set_value("Depot", d.name, "branch", match, update_modified=False)
			filled += 1

	frappe.db.commit()
	print(f"[container_depot] backfill_depot_branch_by_city: filled {filled} depot(s).")
