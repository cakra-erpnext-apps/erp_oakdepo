"""ESS PWA endpoints for the Container Position Survey (Lift On) workflow — thin
``@frappe.whitelist`` wrappers over ``operations.position_survey``.

Per the integration rule: endpoints here only add authentication + whitelisting + GET/POST
gating; all logic lives in ``container_depot.operations.position_survey`` so the same code
backs the PWA and any Desk / automation caller. Mirrors ``ess/cleaning.py``.
"""

from __future__ import annotations

import frappe
from frappe import _

from container_depot.api import _require_authenticated_user
from container_depot.operations import position_survey

# The "Position Fix" approval is restricted to yard operators (Operator Kalmar et al.).
# Reads stay open to any authenticated PWA user.
KALMAR_ROLES = {"Operator Kalmar", "Admin Ops", "Ops Supervisor", "System Manager"}


def _require_position_kalmar() -> None:
	_require_authenticated_user()
	if set(frappe.get_roles(frappe.session.user)).isdisjoint(KALMAR_ROLES):
		frappe.throw(_("Anda tidak berwenang meng-approve posisi container."), frappe.PermissionError)


@frappe.whitelist(methods=["GET"])
def position_pending(start=0, page_length=20, search=None):
	"""GET /api/v1/ess/position-pending — Surveyor worklist (Pending Survey), depot-scoped."""
	_require_authenticated_user()
	return position_survey.list_pending_surveys(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def position_surveyed(start=0, page_length=20, search=None):
	"""GET /api/v1/ess/position-surveyed — Operator Kalmar approval worklist (Surveyed)."""
	_require_authenticated_user()
	return position_survey.list_surveyed(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def position_detail(name=None):
	"""GET /api/v1/ess/position-detail — one survey's header + location note + photos."""
	_require_authenticated_user()
	return position_survey.get_survey_detail(name)


@frappe.whitelist(methods=["POST"])
def position_record(name=None, location_note=None, photos=None, notes=None):
	"""POST /api/v1/ess/position-record — Surveyor records the container's location note +
	photos (→ Surveyed). DocPerm (Surveyor) is enforced (no bypass)."""
	_require_authenticated_user()
	return position_survey.record_survey_position(
		name, location_note=location_note, photos=photos, notes=notes
	)


@frappe.whitelist(methods=["POST"])
def position_approve(name=None, note=None):
	"""POST /api/v1/ess/position-approve — Operator Kalmar approves ("udah turun") →
	Confirmed (submitted). Role-guarded."""
	_require_position_kalmar()
	return position_survey.approve_position(name, note=note)
