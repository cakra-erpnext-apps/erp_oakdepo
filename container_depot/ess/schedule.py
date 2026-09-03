"""ESS PWA endpoints for Jadwal — the one calendar over every kind of planned depot work.

Thin ``@frappe.whitelist`` wrappers over ``container_depot.container_depot.schedule``; the
logic, the source table and the per-source permission filter all live there.

TWO GATES, AND WHY BOTH
-----------------------
``require_menu("schedule")`` decides whether the calendar opens at all — it is an any-of over
the four scheduled doctypes (``ess.context._MENU``), so an account with read on none of them
is refused outright rather than handed an empty grid.

Inside, every source re-checks READ on its own doctype. That second check is the one that
matters: the menu gate passing means the caller can read SOMETHING, never that they can read
everything. Team Cleaning opens the same URL as SPV Lapangan and gets only the wash plan.
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
