"""ESS PWA endpoints for the Tank Out field survey (Survey Order + its tank rows).

Thin ``@frappe.whitelist`` wrappers over ``container_depot.tank_survey``; all logic lives there
so the same code backs the PWA and any Desk / automation caller.

TWO MENUS OVER ONE DOCTYPE, AND WHICH WAY THEY SPLIT
----------------------------------------------------
``posFix`` is the LOWERING queue (write permission — Team Kalmar, Team Survey, SPV Lapangan);
``surveyPos`` is the surveyor's calendar and the closing press (submit permission — Team
Survey, SPV Lapangan). See ``ess.context._MENU`` for why the discriminators are write and
submit, and ``tank_survey``'s module docstring for why a surveyor may lower a tank but a Kalmar
operator may never close a survey.

Where a tank IS never appears in this module. That is ``ess/container_position.py`` — every
list and detail here reads the location live off the Container master, so the two features
share one answer instead of two that drift.
"""

from __future__ import annotations

import frappe

from container_depot.container_depot import tank_survey
from container_depot.ess.guard import require_any_menu, require_menu
from container_depot.ess.idempotency import guarded

# Read endpoints are open to BOTH menus throughout. The two teams work the same tanks on the
# same day and each needs to see what the other has done — a Kalmar operator deciding what to
# drop next reads the survey side, and a surveyor planning a round reads the lowering side.
# Only the closing press and its undo are actually narrowed.
_BOTH = ("surveyPos", "posFix")

# Every READ endpoint admits a third, wider key. `surveyList` is plain READ over Survey Order,
# so it covers both action menus (write and submit both imply read in the seeded matrix) and
# additionally an account that may look but not touch. Splitting reads from writes this way is
# what lets the standalone list exist without handing anyone a press they should not have —
# the action endpoints below stay on `_BOTH` and on `surveyPos` alone.
_READ = ("surveyList", *_BOTH)


# ---------------------------------------------------------------------------
# The calendar — Jadwal Survey
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["GET"])
def survey_calendar(month=None):
	"""GET /api/v1/ess/survey-calendar — per-day tank counts for one month (calendar dots)."""
	require_any_menu(*_READ)
	return tank_survey.survey_calendar(month=month)


@frappe.whitelist(methods=["GET"])
def survey_orders(date=None, start=0, page_length=20):
	"""GET /api/v1/ess/survey-orders — the survey schedules on one day."""
	require_any_menu(*_READ)
	return tank_survey.list_survey_orders(date=date, start=start, page_length=page_length)


@frappe.whitelist(methods=["GET"])
def survey_order_list(status=None, from_date=None, to_date=None, search=None,
					  start=0, page_length=20):
	"""GET /api/v1/ess/survey-order-list — the standalone Jadwal Survey list.

	Gated on ``surveyList`` (READ over Survey Order), which is deliberately wider than the two
	action menus: reading which schedules exist is not the same right as marking a tank down or
	closing a survey, and an account that may see the work but not do it — an Admin Ops
	checking on a day, a supervisor covering another branch — has a legitimate reason to look.
	The list is still depot-scoped, and every action reached from it re-checks its own menu.
	"""
	require_menu("surveyList")
	return tank_survey.list_all_survey_orders(
		status=status, from_date=from_date, to_date=to_date, search=search,
		start=start, page_length=page_length,
	)


@frappe.whitelist(methods=["GET"])
def survey_order_detail(name=None):
	"""GET /api/v1/ess/survey-order-detail — one schedule's header + every tank on it, each
	with its live location from the Container master."""
	require_any_menu(*_READ)
	return tank_survey.get_survey_order_detail(name)


# ---------------------------------------------------------------------------
# Worklists
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["GET"])
def survey_waiting(start=0, page_length=20, search=None):
	"""GET /api/v1/ess/survey-waiting — the LOWERING queue (Waiting Lowering), depot-scoped."""
	require_any_menu(*_READ)
	return tank_survey.list_waiting_lowering(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def survey_ready(start=0, page_length=20, search=None):
	"""GET /api/v1/ess/survey-ready — tanks already on the ground, ready to be surveyed."""
	require_any_menu(*_READ)
	return tank_survey.list_ready_to_survey(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def survey_history(start=0, page_length=10, search=None):
	"""GET /api/v1/ess/survey-history — finished tanks (Survey Done / Cancelled).

	Open to both menus. Riwayat is where a finished step is reopened from, and half of what is
	reopened there is the lowering — gating it on `surveyPos` alone would put the undo behind a
	menu the operator who needs it does not hold."""
	require_any_menu(*_READ)
	return tank_survey.list_survey_history(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def survey_tank_detail(name=None):
	"""GET /api/v1/ess/survey-tank-detail — one tank row: its two steps, its schedule, and its
	live location plus how old that answer is."""
	require_any_menu(*_READ)
	return tank_survey.get_tank_detail(name)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
@frappe.whitelist(methods=["POST"])
def survey_lowered(name=None, location_note=None, note=None, photos=None, request_id=None):
	"""POST /api/v1/ess/survey-lowered — Tandai Lowered (→ Lowered).

	Open to both menus on purpose: normally the Kalmar operator on the reachstacker, but a
	surveyor already standing at a tank that is plainly on the ground should not have to wait
	for somebody else before the day can start.

	``location_note``, when given, is filed as a fresh Container Position reading rather than
	stored on the row — one channel for positions. ``request_id`` makes a replay safe."""
	require_any_menu(*_BOTH)
	return guarded(request_id, lambda: tank_survey.mark_lowered(
		name, location_note=location_note, note=note, photos=photos
	))


@frappe.whitelist(methods=["POST"])
def survey_finish(name=None, notes=None, request_id=None):
	"""POST /api/v1/ess/survey-finish — Selesai Survey (→ Survey Done).

	The surveyor's alone (`surveyPos` = submit permission). This is the press that raises the
	tank's EIR-Out, so a replay must not be able to run it twice — hence ``request_id``."""
	require_menu("surveyPos")
	return guarded(request_id, lambda: tank_survey.finish_survey(name, notes=notes))


@frappe.whitelist(methods=["POST"])
def survey_reopen_lowering(name=None, note=None, request_id=None):
	"""POST /api/v1/ess/survey-reopen-lowering — send a tank all the way back (→ Waiting
	Lowering): it was never really down.

	Either menu may call it: the Kalmar operator correcting themselves from Riwayat, or the
	surveyor who is standing at an empty bay right now."""
	require_any_menu(*_BOTH)
	return guarded(request_id, lambda: tank_survey.reopen_lowering(name, note=note))


@frappe.whitelist(methods=["POST"])
def survey_reopen_survey(name=None, note=None, request_id=None):
	"""POST /api/v1/ess/survey-reopen-survey — send a closed tank back to the surveyor
	(→ Lowered) because it was closed too early. The lowering is left alone."""
	require_menu("surveyPos")
	return guarded(request_id, lambda: tank_survey.reopen_survey(name, note=note))
