"""ESS PWA endpoints for Container Position — where each tank stands.

Thin ``@frappe.whitelist`` wrappers over ``container_depot.container_position``; all logic
lives there so the same code backs the PWA and any Desk / automation caller.

ONE MENU, EVERY FIELD TEAM
--------------------------
``tankPos`` keys on CREATE over ``Container Position``, and every field role holds it
(``install.FIELD_ROLE_MATRIX``). That is the whole design of the feature, not an oversight: a
wrong position costs whoever walks to the wrong stack next — a washer, a mechanic, a surveyor,
the gate — so anyone who finds a tank somewhere may say so. Fencing the correction behind one
crew would only slow it down while everyone else keeps walking to the wrong bay.

Reading is open to the same menu. There is no separate "view positions" right: a screen that
lets you correct a position has to show you the one you are correcting.
"""

from __future__ import annotations

import frappe

from container_depot.container_depot import container_position
from container_depot.ess.guard import require_menu
from container_depot.ess.idempotency import guarded

MENU = "tankPos"


@frappe.whitelist(methods=["GET"])
def tank_search(search=None, start=0, page_length=20, only_unlocated=0):
	"""GET /api/v1/ess/tank-search — find tanks by number, with their last known place.

	``only_unlocated=1`` narrows to the tanks nobody has ever recorded — the list to go and
	clear, and the reason the finder exists at all."""
	require_menu(MENU)
	return container_position.search_containers(
		search=search, start=start, page_length=page_length, only_unlocated=only_unlocated
	)


@frappe.whitelist(methods=["GET"])
def tank_position(container=None):
	"""GET /api/v1/ess/tank-position — one tank's current location, its age, and the readings
	behind it."""
	require_menu(MENU)
	return container_position.get_container_position(container)


@frappe.whitelist(methods=["GET"])
def position_history(container=None, start=0, page_length=20, search=None):
	"""GET /api/v1/ess/position-history — the readings feed, newest first, branch-scoped."""
	require_menu(MENU)
	return container_position.list_position_history(
		container=container, start=start, page_length=page_length, search=search
	)


@frappe.whitelist(methods=["POST"])
def position_record(container=None, location_note=None, notes=None, photos=None, request_id=None):
	"""POST /api/v1/ess/position-record — file one reading of where a tank is standing.

	``request_id`` makes a replay safe. It matters more here than for most writes: this endpoint
	INSERTS, so a lost response on a bad signal would otherwise leave two identical readings
	minutes apart and make the tank look like it had been re-checked when it had not."""
	require_menu(MENU)
	return guarded(request_id, lambda: container_position.record_position(
		container, location_note, notes=notes, photos=photos
	))
