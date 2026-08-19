"""ESS PWA endpoints for the Container Position Survey (Lift On) workflow — thin
``@frappe.whitelist`` wrappers over ``container_depot.position_survey``.

Per the integration rule: endpoints here only add authentication + whitelisting + GET/POST
gating; all logic lives in ``container_depot.container_depot.position_survey`` so the same code
backs the PWA and any Desk / automation caller. Mirrors ``ess/cleaning.py``.
"""

from __future__ import annotations

import frappe
from frappe import _

from container_depot.ess.guard import require_menu
from container_depot.ess.idempotency import guarded
from container_depot.container_depot import position_survey

# The "Position Fix" approval (2026-08-06) is gated by the `posFix` menu, i.e. by submit
# permission on Container Position Survey — Team Kalmar and SPV Lapangan have it, Team
# Survey does not. Recording a survey is the `surveyPos` menu (write permission) and runs
# the other way round. One doctype, two menus, split on ptype; see ess.context._MENU.


@frappe.whitelist(methods=["GET"])
def position_pending(start=0, page_length=20, search=None):
	"""GET /api/v1/ess/position-pending — Surveyor worklist (Pending Survey), depot-scoped."""
	require_menu("surveyPos")
	return position_survey.list_pending_surveys(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def position_surveyed(start=0, page_length=20, search=None):
	"""GET /api/v1/ess/position-surveyed — Operator Kalmar approval worklist (Surveyed)."""
	require_menu("posFix")
	return position_survey.list_surveyed(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def position_history(start=0, page_length=10, search=None):
	"""GET /api/v1/ess/position-history — finished surveys (Confirmed / Cancelled), depot-scoped."""
	require_menu("surveyPos")
	return position_survey.list_survey_history(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def position_detail(name=None):
	"""GET /api/v1/ess/position-detail — one survey's header + location note + photos."""
	require_menu("surveyPos")
	return position_survey.get_survey_detail(name)


@frappe.whitelist(methods=["POST"])
def position_save_draft(name=None, location_note=None, photos=None, notes=None):
	"""POST /api/v1/ess/position-save-draft — surveyor autosave while the form is open.

	No ``request_id``: this is a plain overwrite of three fields on one draft, so a replay
	writes exactly the same values. Guarding it would only fill the idempotency table with a
	row per typing pause."""
	require_menu("surveyPos")
	return position_survey.save_survey_draft(
		name, location_note=location_note, photos=photos, notes=notes
	)


@frappe.whitelist(methods=["POST"])
def position_record(name=None, location_note=None, photos=None, notes=None, request_id=None):
	"""POST /api/v1/ess/position-record — Surveyor records the container's location note +
	photos (→ Surveyed). DocPerm (Surveyor) is enforced (no bypass).

	``request_id`` makes a replay safe — see ``ess/idempotency.py``."""
	require_menu("surveyPos")
	return guarded(request_id, lambda: position_survey.record_survey_position(
		name, location_note=location_note, photos=photos, notes=notes
	))


@frappe.whitelist(methods=["POST"])
def position_approve(name=None, note=None, request_id=None):
	"""POST /api/v1/ess/position-approve — Team Kalmar approves ("udah turun") →
	Confirmed (submitted).

	``request_id`` makes a replay safe: this submits the survey, and a lost response would
	otherwise send a second submit at an already-submitted doc. See ``ess/idempotency.py``."""
	require_menu("posFix")
	return guarded(request_id, lambda: position_survey.approve_position(name, note=note))
