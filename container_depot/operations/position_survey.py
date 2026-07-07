"""Core logic for the Container Position Survey (Lift On / Tank Out) workflow.

Deliberately free of ``@frappe.whitelist`` so the exact same functions back both the ESS
PWA wrappers (``ess/position_survey.py``) and any Desk / automation caller — the endpoint
layer only adds auth + whitelisting.

Flow (per outbound container): a Container Booking (Tank Out) submit provisions one
``Container Position Survey`` (status ``Pending Survey``). A Surveyor records the found yard
position (writing a ``Container Movement`` so the yard mapping updates) → ``Surveyed``. An
Operator Kalmar approves ("udah turun") → ``Confirmed`` (submitted).

Hard rule: this module NEVER writes ``Container.status`` — the survey has its own status.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from container_depot.operations.user_branch import assert_in_user_branch, get_user_depots

DOCTYPE = "Container Position Survey"

PENDING = "Pending Survey"
SURVEYED = "Surveyed"
CONFIRMED = "Confirmed"


def _guard_container_branch(container_name) -> None:
	"""Block actions on a container whose depot is outside the caller's branch."""
	depot = frappe.db.get_value("Container", container_name, "depot")
	assert_in_user_branch(depot=depot)


def _coerce_photos(photos) -> list:
	"""Normalise the ``photos`` payload (JSON string or list of urls / {photo}) → url list."""
	if photos is None:
		return []
	if isinstance(photos, str):
		try:
			photos = json.loads(photos)
		except json.JSONDecodeError:
			frappe.throw(_("photos must be a JSON array."))
	if not isinstance(photos, list):
		frappe.throw(_("photos must be a list."))
	out = []
	for p in photos:
		url = (p.get("photo") if isinstance(p, dict) else p) or ""
		url = str(url).strip()
		if url:
			out.append(url)
	return out


# ---------------------------------------------------------------------------
# Provisioning — Container Booking (Tank Out) submit hook
# ---------------------------------------------------------------------------
def provision_position_survey_for_booking(booking_name: str) -> list:
	"""Submit-time hook for an outbound (Tank Out) Container Booking: create one
	``Container Position Survey`` (Pending Survey) per container so a Surveyor is tasked with
	locating it before it is pulled.

	Idempotent per container (skips when an open survey already exists); best-effort per row —
	one failure is logged and never blocks the booking submit. Mirrors
	``eir.provision_eir_out_for_order_muat``.
	"""
	depot = frappe.db.get_value("Container Booking", booking_name, "depot")
	rows = frappe.get_all(
		"Container Booking Item",
		filters={"parent": booking_name, "parenttype": "Container Booking"},
		fields=["container"],
	)
	created = []
	for row in rows:
		container = row.get("container")
		if not container:
			continue
		# Dedup: never open a second survey for a container that still has an open one.
		if frappe.db.exists(DOCTYPE, {"container": container, "docstatus": 0, "status": ["!=", "Cancelled"]}):
			continue
		try:
			doc = frappe.new_doc(DOCTYPE)
			doc.container = container
			doc.depot = depot or frappe.db.get_value("Container", container, "depot")
			doc.booking = booking_name
			doc.status = PENDING
			doc.insert(ignore_permissions=True)  # system automation on booking submit
			created.append(doc.name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"auto position survey for {container} on {booking_name}")
	return created


# ---------------------------------------------------------------------------
# Worklists
# ---------------------------------------------------------------------------
def _list_by_status(status, start=0, page_length=20, search=None) -> dict:
	"""Open surveys in a given status, depot-scoped to the caller's branch, searchable,
	paginated. Copies ``cleaning.list_open_cleaning_orders``."""
	filters = {"status": status, "docstatus": 0}
	depots = get_user_depots()
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]  # restricted user: only their depots
	or_filters = None
	search = (search or "").strip()
	if search and search.lower() not in ("undefined", "null", "none"):
		or_filters = {"container_no": ["like", f"%{search}%"], "name": ["like", f"%{search}%"]}
	items = frappe.get_all(
		DOCTYPE,
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name", "container", "container_no", "status", "depot",
			"booking", "yard_zone", "creation",
		],
		order_by="creation asc",
		limit_start=cint(start),
		limit_page_length=cint(page_length),
	)
	return {"items": items, "total": frappe.db.count(DOCTYPE, filters)}


def list_pending_surveys(start=0, page_length=20, search=None) -> dict:
	"""Surveyor worklist — surveys awaiting a position (Pending Survey)."""
	return _list_by_status(PENDING, start=start, page_length=page_length, search=search)


def list_surveyed(start=0, page_length=20, search=None) -> dict:
	"""Operator Kalmar worklist — surveys awaiting approval (Surveyed)."""
	return _list_by_status(SURVEYED, start=start, page_length=page_length, search=search)


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------
def get_survey_detail(name: str) -> dict:
	"""Full survey header + the container's current yard position + in-scope zones (for the
	surveyor's zone picker) + photos. Branch-scoped."""
	doc = frappe.get_doc(DOCTYPE, name)
	_guard_container_branch(doc.container)

	# In-scope zones + current position (best-effort; recommend_zones drives the yard picker).
	zones, current, recommended = [], None, None
	try:
		from container_depot.operations.yard import recommend_zones

		rec = recommend_zones(doc.container_no or doc.container)
		zones = rec.get("all_zones") or []
		current = rec.get("current")
		# The first recommended candidate, if any, as a hint.
		for z in rec.get("zones") or []:
			if z.get("recommended"):
				recommended = z.get("name")
				break
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"recommend_zones for position survey {name}")

	return {
		"name": doc.name,
		"container": doc.container,
		"container_no": doc.container_no,
		"depot": doc.depot,
		"booking": doc.booking,
		"status": doc.status,
		"docstatus": doc.docstatus,
		"yard_zone": doc.yard_zone,
		"row": doc.row,
		"bay": doc.bay,
		"tier": doc.tier,
		"survey_notes": doc.survey_notes,
		"surveyed_by": doc.surveyed_by,
		"surveyed_on": doc.surveyed_on,
		"approved_by": doc.approved_by,
		"approved_on": doc.approved_on,
		"approval_note": doc.approval_note,
		"photos": [p.photo for p in doc.position_photos],
		"current": current,
		"recommended_zone": recommended,
		"zones": zones,
	}


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
def record_survey_position(name, yard_zone, row=None, bay=None, tier=None, photos=None, notes=None) -> dict:
	"""Surveyor action: record the found yard position + photos, then move to ``Surveyed``.

	The position is written to the ``Container Movement`` ledger (event ``Yard``) — the
	Movement's ``after_insert`` syncs ``Container.yard_zone/row/bay/tier``, so the yard mapping
	reflects reality. We insert the Movement directly (not ``yard.place_container``) so a found
	position that happens to break an SOP limit is still recordable — a survey records reality,
	it does not place a new tank. Permissions are enforced (no bypass).
	"""
	doc = frappe.get_doc(DOCTYPE, name)
	_guard_container_branch(doc.container)
	if doc.status != PENDING:
		frappe.throw(_("Survey {0} sudah bukan Pending Survey.").format(name))
	if not yard_zone or not frappe.db.exists("Yard Zone", yard_zone):
		frappe.throw(_("Yard Zone {0} tidak ditemukan.").format(yard_zone or ""))

	tier = cint(tier) if tier not in (None, "") else None
	row = (str(row).strip() or None) if row not in (None, "") else None
	bay = (str(bay).strip() or None) if bay not in (None, "") else None

	# Ledger write → after_insert syncs the Container's denormalised position.
	movement = frappe.get_doc({
		"doctype": "Container Movement",
		"container": doc.container,
		"event_type": "Yard",
		"to_zone": yard_zone,
		"to_row": row,
		"to_bay": bay,
		"to_tier": tier,
		"moved_by": frappe.session.user,
	})
	movement.insert(ignore_permissions=True)  # the ledger is append-only automation

	doc.yard_zone = yard_zone
	doc.row = row
	doc.bay = bay
	doc.tier = tier
	doc.movement = movement.name
	doc.survey_notes = notes
	doc.surveyed_by = frappe.session.user
	doc.surveyed_on = now_datetime()
	doc.set("position_photos", [{"photo": url} for url in _coerce_photos(photos)])
	doc.status = SURVEYED
	doc.save()  # NOT ignore_permissions — DocPerm (Surveyor) is enforced.

	return {
		"success": True,
		"name": doc.name,
		"status": doc.status,
		"movement": movement.name,
		"yard_zone": yard_zone,
	}


def approve_position(name, note=None) -> dict:
	"""Operator Kalmar action: approve ("udah turun"/Position Fix) → ``Confirmed`` (submit).

	The role is enforced by the ESS wrapper (`_require_position_kalmar`); here we enforce the
	branch and the status transition.
	"""
	doc = frappe.get_doc(DOCTYPE, name)
	_guard_container_branch(doc.container)
	if doc.status != SURVEYED:
		frappe.throw(_("Survey {0} belum disurvei (status harus Surveyed).").format(name))

	doc.approved_by = frappe.session.user
	doc.approved_on = now_datetime()
	doc.approval_note = note
	doc.status = CONFIRMED
	doc.submit()

	return {"success": True, "name": doc.name, "status": doc.status, "docstatus": doc.docstatus}
