"""ESS PWA endpoints for Jadwal — the one calendar over every kind of planned depot work.

Thin ``@frappe.whitelist`` wrappers over ``container_depot.container_depot.schedule``; the
logic, the source table and the per-source permission filter all live there.

ONE GATE, AND WHERE IT IS
-------------------------
``require_menu("schedule")`` only asks that the caller is a logged-in depot user: the entry in
``ess.context._MENU`` carries no doctype, because Jadwal is a GLOBAL screen. What it shows is
where the permission lives — every source re-checks READ on its own doctype, so Team Cleaning
opens the same URL as SPV Lapangan and gets only the wash plan, and a crew with read on
nothing scheduled gets the screen with an empty grid rather than a refusal.
"""

from __future__ import annotations

import frappe

from container_depot.container_depot import schedule
from container_depot.ess.guard import require_menu


@frappe.whitelist(methods=["GET"])
def schedule_calendar(month=None, kinds=None):
	"""GET /api/v1/ess/schedule-calendar — per-day counts for one month (the calendar dots)."""
	require_menu("schedule")
	return schedule.schedule_calendar(month=month, kinds=kinds)


@frappe.whitelist(methods=["GET"])
def schedule_day(date=None, kinds=None):
	"""GET /api/v1/ess/schedule-day — everything planned on one day, one card shape."""
	require_menu("schedule")
	return schedule.schedule_day(date=date, kinds=kinds)
