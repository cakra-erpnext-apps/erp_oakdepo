"""Core logic for the Container Position Survey (Lift On / Tank Out) workflow.

Deliberately free of ``@frappe.whitelist`` so the exact same functions back both the ESS
PWA wrappers (``ess/position_survey.py``) and any Desk / automation caller — the endpoint
layer only adds auth + whitelisting.

Flow (per outbound container): a Container Booking (Tank Out) submit provisions one
``Container Position Survey`` (status ``Pending Survey``). A Surveyor presses Mulai
(→ ``In Survey``, which claims the job) and writes a free-text note of where the container
physically sits (+ photos) → ``Surveyed``. An Operator Kalmar presses Mulai (→ ``In Fix``)
and approves ("udah turun") → ``Confirmed`` (submitted).

NO REVIEW STEP, AND WHY THE REOPEN IS NOT OPTIONAL
--------------------------------------------------
Cleaning and M&R park a finished job in ``Pending Review`` so Admin Ops can check it before
the Desk Submit, and the PWA can only *request* a reopen (``cleaning.request_revision``).
This workflow has no such step: the survey carries no money, touches no invoice, and is not
in ``container_status.container_open_orders``, so a wrong position note holds up nothing but
the next person to walk out to the tank. Making Admin Ops the gate would put an office queue
in front of a two-minute correction.

The price of dropping the review is that the operator must be able to undo their own step,
so :func:`reopen_survey` and :func:`reopen_fix` push a finished half back to its in-progress
state — clearing exactly the stamps of the step being redone and nothing else. They are the
one place in this app where a field role un-submits a document, and that is deliberate: with
no reviewer standing behind them, the alternative is a wrong record nobody can fix.

Hard rule: this module NEVER writes ``Container.status`` — the survey has its own status.
No yard zones / mapping: the location is a human note only.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from container_depot.container_depot.exceptions import AlreadySettled
from container_depot.container_depot.notify import (
	notify_position_confirmed,
	notify_position_survey_pending,
	notify_position_surveyed,
)
from container_depot.container_depot.user_branch import assert_in_user_branch, get_user_depots
from container_depot.container_depot.work_claim import filter_claimed, guard_claim
from container_depot.container_depot.worklist import sort_by_priority

DOCTYPE = "Container Position Survey"

PENDING = "Pending Survey"
IN_SURVEY = "In Survey"
SURVEYED = "Surveyed"
IN_FIX = "In Fix"
CONFIRMED = "Confirmed"

# The two worklists, each as (statuses it shows, the column that claims it). Written once
# here because four places need to agree on them: the list, the claim filter, the start
# action and the reopen target.
SURVEY_OPEN = (PENDING, IN_SURVEY)
FIX_OPEN = (SURVEYED, IN_FIX)


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
	# Per row, not off the booking header: an outbound booking may collect from two depots
	# of one branch, and then the header carries no depot at all. Each survey is tasked at
	# the yard its own tank is standing in.
	booking_depot = frappe.db.get_value("Container Booking", booking_name, "depot")
	rows = frappe.get_all(
		"Container Booking Item",
		filters={"parent": booking_name, "parenttype": "Container Booking"},
		fields=["container", "depot"],
	)
	created = []
	for row in rows:
		container = row.get("container")
		if not container:
			continue
		# Dedup: never open a second survey for a container that still has an open one.
		if frappe.db.exists(DOCTYPE, {"container": container, "docstatus": 0, "status": ["!=", "Cancelled"]}):
			continue
		# ... nor a second one for a booking that has been through submit before. A finished
		# survey is SUBMITTED (``approve_position`` calls doc.submit()), so the open-survey
		# test above cannot see it — and a booking CAN be submitted twice, since
		# ``revert_booking_to_draft`` only refuses once a bon exists or a code is Used, both
		# of which happen after the survey. Same rule as ``eir._already_provisioned``.
		if frappe.db.exists(DOCTYPE, {
			"container": container, "booking": booking_name, "docstatus": ["!=", 2],
		}):
			continue
		try:
			doc = frappe.new_doc(DOCTYPE)
			doc.container = container
			doc.depot = (
				row.get("depot")
				or frappe.db.get_value("Container", container, "depot")
				or booking_depot
			)
			doc.booking = booking_name
			doc.status = PENDING
			doc.insert(ignore_permissions=True)  # system automation on booking submit
			created.append(doc.name)
			notify_position_survey_pending(doc)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"auto position survey for {container} on {booking_name}")
	return created


# ---------------------------------------------------------------------------
# Worklists
# ---------------------------------------------------------------------------
def _list_by_status(statuses, in_progress, claim_field, start=0, page_length=20, search=None) -> dict:
	"""Open surveys in the given statuses, depot-scoped to the caller's branch, searchable,
	paginated. Copies ``cleaning.list_open_cleaning_orders``.

	``in_progress`` is the status this half ends on once Mulai is pressed (In Survey for the
	surveyor's list, In Fix for the Kalmar's) — it decides tier 2 of the sort, and is passed
	rather than derived so the order can never drift from the screen's own Dikerjakan tab.

	``claim_field`` is the column that says who pressed Mulai on this half of the workflow:
	once someone has, the row leaves everybody else's worklist (see ``work_claim``). Filtered
	in Python and BEFORE ``total`` is taken, so the count on the tab matches what is under it.
	"""
	filters = {"status": ["in", list(statuses)], "docstatus": 0}
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
			"name", "container", "container_no", "status", "depot", "booking",
			"location_note", "reopen_note", "creation", "target_lift_on",
			"survey_started_by", "fix_started_by",
		],
		# Whole list, then filter, then sort, then slice: the priority order is decided in
		# Python (see ``worklist.sort_by_priority``), so SQL cannot page it.
		order_by="creation asc",
		limit_page_length=0,
	)
	items = filter_claimed(items, claim_field)
	total = len(items)
	# Gate-out priority, then the job already in this operator's hands, then the rest —
	# see ``worklist.sort_by_priority`` for why that order.
	items = sort_by_priority(items, lambda r: r.get("status") == in_progress, start, page_length)
	return {"items": items, "total": total}


def list_pending_surveys(start=0, page_length=20, search=None) -> dict:
	"""Surveyor worklist — surveys still to be located (Pending Survey + the ones this
	surveyor has already started)."""
	return _list_by_status(
		SURVEY_OPEN, IN_SURVEY, "survey_started_by",
		start=start, page_length=page_length, search=search,
	)


def list_surveyed(start=0, page_length=20, search=None) -> dict:
	"""Operator Kalmar worklist — located surveys awaiting approval (Surveyed + the ones this
	operator has already started)."""
	return _list_by_status(
		FIX_OPEN, IN_FIX, "fix_started_by",
		start=start, page_length=page_length, search=search,
	)


def list_survey_history(start=0, page_length=10, search=None) -> dict:
	"""Finished surveys (Confirmed / Cancelled) — the PWA position-survey "Riwayat" feed,
	newest first, paginated + searchable, depot-scoped to the caller's branch. Detail reuses
	``get_survey_detail``. Mirrors ``cleaning.list_cleaning_history``."""
	filters = {"status": ["in", [CONFIRMED, "Cancelled"]]}
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
			"name", "container", "container_no", "status", "depot", "booking",
			"location_note", "surveyed_by", "surveyed_on", "approved_by", "approved_on",
			"reopen_note", "target_lift_on", "creation",
		],
		order_by="creation desc",
		limit_start=cint(start),
		limit_page_length=cint(page_length),
	)
	return {"items": items, "total": frappe.db.count(DOCTYPE, filters)}


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------
def get_survey_detail(name: str) -> dict:
	"""Full survey header + the surveyor's location note + photos. Branch-scoped."""
	doc = frappe.get_doc(DOCTYPE, name)
	_guard_container_branch(doc.container)

	return {
		"name": doc.name,
		"container": doc.container,
		"container_no": doc.container_no,
		"depot": doc.depot,
		"booking": doc.booking,
		"status": doc.status,
		"docstatus": doc.docstatus,
		"location_note": doc.location_note,
		"survey_notes": doc.survey_notes,
		"surveyed_by": doc.surveyed_by,
		"surveyed_on": doc.surveyed_on,
		"survey_started_by": doc.survey_started_by,
		"survey_started_on": doc.survey_started_on,
		"approved_by": doc.approved_by,
		"approved_on": doc.approved_on,
		"approval_note": doc.approval_note,
		"fix_started_by": doc.fix_started_by,
		"fix_started_on": doc.fix_started_on,
		# Why it came back, for the operator who now has to redo it.
		"reopen_note": doc.reopen_note,
		# The customer's lift-on date, from the Gate Out Plan via the container.
		"target_lift_on": doc.target_lift_on,
		"photos": [p.photo for p in doc.position_photos],
	}


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
def _open_for(name, statuses, claim_field):
	"""Load a survey, check the branch and the claim, and refuse a wrong status.

	Every action below starts exactly this way, and the order matters: branch first (may this
	user touch this depot at all), then status (is this step even live), then the claim (is it
	someone else's job). Getting "sudah dikerjakan rekan lain" for a survey that is actually
	finished would send the operator looking for a colleague who is not holding anything.
	"""
	doc = frappe.get_doc(DOCTYPE, name)
	_guard_container_branch(doc.container)
	if doc.status not in statuses:
		frappe.throw(_("Survey {0} statusnya {1}, bukan {2}.").format(
			name, doc.status, " / ".join(statuses)
		))
	guard_claim(doc.get(claim_field), _("Survey posisi {0}").format(doc.container_no or name))
	return doc


def start_survey(name) -> dict:
	"""Surveyor presses Mulai: Pending Survey -> In Survey, and the job is theirs.

	First press wins (``work_claim``) — the tank disappears from every other surveyor's
	worklist, so two people do not walk out to the same stack. Pressing it again on a job
	already yours is a no-op rather than an error: a retried request from a bad signal spot
	must not read as a failure.
	"""
	doc = _open_for(name, SURVEY_OPEN, "survey_started_by")
	if doc.status == PENDING:
		doc.status = IN_SURVEY
		doc.survey_started_by = frappe.session.user
		doc.survey_started_on = now_datetime()
		doc.save()  # NOT ignore_permissions — the caller holds write on the survey.
	return {"success": True, "name": doc.name, "status": doc.status}


def start_fix(name) -> dict:
	"""Operator Kalmar presses Mulai: Surveyed -> In Fix, and the job is theirs.

	The twin of :func:`start_survey` on the other half of the workflow, claimed on its own
	column: the same survey can be held by a surveyor earlier and a Kalmar operator later
	without either claim standing in the other's way.
	"""
	doc = _open_for(name, FIX_OPEN, "fix_started_by")
	if doc.status == SURVEYED:
		doc.status = IN_FIX
		doc.fix_started_by = frappe.session.user
		doc.fix_started_on = now_datetime()
		doc.save()
	return {"success": True, "name": doc.name, "status": doc.status}


def save_survey_draft(name, location_note=None, photos=None, notes=None) -> dict:
	"""Surveyor autosave: park the note + photos on the survey while the form is still open.

	Deliberately looser than :func:`record_survey_position`. An autosave fires mid-typing, so
	a half-filled (or empty) ``location_note`` is written as-is instead of being thrown at —
	the whole point is that whatever the surveyor has so far survives the app being closed.

	What it must NOT do is advance the status or stamp ``surveyed_by`` / ``surveyed_on``: the
	survey only counts as done when the surveyor taps Simpan, and the Kalmar worklist reads
	``Surveyed`` to decide what is ready for Position Fix.
	"""
	doc = _open_for(name, SURVEY_OPEN, "survey_started_by")

	doc.location_note = str(location_note).strip() if location_note is not None else ""
	doc.survey_notes = notes
	doc.set("position_photos", [{"photo": url} for url in _coerce_photos(photos)])
	doc.save()  # NOT ignore_permissions — same DocPerm check as the real save.

	return {"success": True, "name": doc.name, "status": doc.status}


def record_survey_position(name, location_note, photos=None, notes=None) -> dict:
	"""Surveyor action: record where the container physically sits (free-text note + photos),
	then move to ``Surveyed``.

	No yard zone / Container Movement — the location is a human note only (the depot no longer
	maps tanks to zones). Permissions are enforced (no bypass).
	"""
	doc = _open_for(name, SURVEY_OPEN, "survey_started_by")
	location_note = (str(location_note).strip() if location_note is not None else "")
	if not location_note:
		frappe.throw(_("Isi dulu letak container-nya."))

	doc.location_note = location_note
	doc.survey_notes = notes
	doc.surveyed_by = frappe.session.user
	doc.surveyed_on = now_datetime()
	# Whoever finishes the survey owns it, Mulai or no Mulai: a handset that came back from a
	# dead spot straight into Simpan must not leave the job unclaimed behind it.
	if not doc.survey_started_by:
		doc.survey_started_by = frappe.session.user
		doc.survey_started_on = now_datetime()
	doc.set("position_photos", [{"photo": url} for url in _coerce_photos(photos)])
	doc.status = SURVEYED
	# The redo asked for is done; the reason it was sent back stops being news.
	doc.reopen_note = None
	doc.save()  # NOT ignore_permissions — DocPerm (Surveyor) is enforced.
	notify_position_surveyed(doc)

	return {
		"success": True,
		"name": doc.name,
		"status": doc.status,
		"location_note": location_note,
	}


def _reopen(name, target, sources, clear, note, subject, notifier) -> dict:
	"""Push a finished survey back to an in-progress state, clearing the step being redone.

	Written once for both halves because the risky part is identical: a Confirmed survey is
	SUBMITTED, and a backwards docstatus flip can never go through ``doc.save()``. It goes
	through ``frappe.db.set_value``, which also means no Version row is written — hence the
	timeline note, which is the only trace the Desk would otherwise have of the reopen.

	``clear`` names the stamps of the step being redone. Nothing else is touched: reopening
	the approval must not throw away the surveyor's note and photos, or the Kalmar operator
	would be sending someone back out to the yard to retype work that was never wrong.
	"""
	from container_depot.container_depot.container_activity import log_doc_note

	doc = frappe.get_doc(DOCTYPE, name)
	_guard_container_branch(doc.container)
	if doc.status == target:
		# Already back in the worklist. A retried request, not a mistake.
		return {"success": True, "name": doc.name, "status": doc.status, "docstatus": doc.docstatus}
	if doc.status not in sources:
		# Reopening only ever undoes a step that was actually taken. Without this, "buka lagi
		# approval" on a survey nobody has located yet would drop it straight into the Kalmar
		# worklist with no position note to approve.
		frappe.throw(_("Survey {0} statusnya {1} — belum ada yang bisa dibuka lagi.").format(
			name, doc.status
		))

	note = (note or "").strip()
	who = frappe.session.user
	line = _("{0} dibuka lagi oleh {1}").format(subject, who)
	if note:
		line += ": " + note

	frappe.db.set_value(DOCTYPE, doc.name, dict(
		{"docstatus": 0, "status": target, "reopen_note": line}, **clear
	))
	log_doc_note(DOCTYPE, doc.name, line)
	# Reloaded first: the flip went through db.set_value, so the in-memory doc still carries
	# the stamps that were just cleared — and the bell would quote them.
	doc.reload()
	notifier(doc, reopened=True)
	return {"success": True, "name": doc.name, "status": target, "docstatus": 0}


def reopen_survey(name, note=None) -> dict:
	"""Send a survey back to the surveyor (-> ``In Survey``): the position note is wrong.

	Reachable from both menus, and on purpose. The surveyor finds their own mistake in
	Riwayat; the Kalmar operator finds it standing at the wrong stack, which is the case that
	actually happens. Whoever presses it, the tank lands back in the SURVEY worklist, because
	that is where the work now is.

	Both halves' stamps are cleared: the approval that followed a wrong position was approving
	the wrong thing, so it does not survive the note it was given for.
	"""
	return _reopen(
		name, IN_SURVEY, (SURVEYED, IN_FIX, CONFIRMED),
		{
			"surveyed_by": None, "surveyed_on": None,
			"approved_by": None, "approved_on": None, "approval_note": None,
			"fix_started_by": None, "fix_started_on": None,
		},
		note, _("Survey posisi"), notify_position_survey_pending,
	)


def reopen_fix(name, note=None) -> dict:
	"""Send a confirmed survey back to the Kalmar operator (-> ``In Fix``): the position was
	right, the "udah turun" was not.

	Only the approval is cleared. The surveyor's note, photos and stamps stay exactly as they
	were — nobody has to walk out to the tank again for a confirmation somebody pressed early.
	"""
	return _reopen(
		name, IN_FIX, (CONFIRMED,),
		{"approved_by": None, "approved_on": None, "approval_note": None},
		note, _("Approval posisi"), notify_position_surveyed,
	)


def approve_position(name, note=None) -> dict:
	"""Operator Kalmar action: approve ("udah turun"/Position Fix) → ``Confirmed`` (submit).

	The role is enforced by the ESS wrapper (`_require_position_kalmar`); here we enforce the
	branch and the status transition.
	"""
	# Already approved — usually a queued approval that left the handset after somebody else
	# had confirmed the same tank. Said plainly, and marked so the queue can tell "this is
	# done" from "this is not ready yet". Checked before _open_for so the operator is told
	# the tank is settled rather than that its status is wrong.
	if frappe.db.get_value(DOCTYPE, name, "status") == CONFIRMED:
		frappe.throw(_("Survey {0} sudah dikonfirmasi.").format(name), exc=AlreadySettled)
	doc = _open_for(name, FIX_OPEN, "fix_started_by")

	doc.approved_by = frappe.session.user
	doc.approved_on = now_datetime()
	doc.approval_note = note
	# Same rule as the surveyor's Simpan: finishing claims what starting would have.
	if not doc.fix_started_by:
		doc.fix_started_by = frappe.session.user
		doc.fix_started_on = now_datetime()
	doc.status = CONFIRMED
	doc.reopen_note = None
	doc.submit()
	notify_position_confirmed(doc)

	return {"success": True, "name": doc.name, "status": doc.status, "docstatus": doc.docstatus}
