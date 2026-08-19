"""ESS PWA read endpoints — Feature F1 (Tank Inventory & Live Status).

All endpoints are GET, authenticated (Guest rejected via the shared
``_require_authenticated_user`` guard), and **permission-aware**: container
reads go through ``frappe.get_list`` / ``frappe.has_permission``, so the
Custom DocPerm matrix seeded by ``install.py`` *and* any ``User Permission``
(e.g. depot scoping on ``Container.depot``) filter the results automatically.
There is no permission logic in the PWA.

Status is **derived server-side** here — the raw ``Container.status`` Select
carries the full lifecycle (normalised in B0: duplicate removed, portal states
added), but the Monitor UI groups tanks by their concrete order state so a field
observer sees the work pipeline. :func:`derive_status` collapses the raw status plus
the tank's Cleaning/M&R order state into five buckets — available / draft / pending /
in_progress / gate_out — classifying by the most-advanced order state it carries.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, cint, getdate, today

from container_depot.api import _require_authenticated_user
from container_depot.ess.guard import require_menu
from container_depot.container_depot import container_activity
from container_depot.container_depot.user_branch import get_user_depots
from container_depot.tasks import PT_REMINDER_DAYS

# Canonical Monitor status buckets — order-state centric so a field observer sees the
# concrete work state per container (keys are stable; labels live in the front-end).
BUCKETS = ("available", "draft", "pending", "in_progress", "gate_out")

# Raw statuses that are NOT physically in the depot yet and must be excluded from
# live inventory counts/lists. `Booked` = a tank reserved by an Container Booking
# whose Container master was created at booking time but has not yet gated in.
EXCLUDED_FROM_INVENTORY = ("Booked",)

# Order states grouped into the Monitor buckets. A container is classified by the
# MOST-ADVANCED order state it carries (in_progress > pending > draft), across Cleaning
# Order + Repair Order (M&R). No open order at all -> `available`.
#   in_progress ("Dikerjakan") = a started job     (start_cleaning / start_repair)
#   pending     ("Pending")    = waiting to be run (queued / awaiting or post approval)
#   draft       ("Draft")      = M&R created, not yet submitted for approval
IN_PROGRESS_CLEANING = ("In_Progress",)
IN_PROGRESS_REPAIR = ("In Progress",)
PENDING_CLEANING = ("Pending",)
PENDING_REPAIR = ("Pending Approval", "Approved")
DRAFT_REPAIR = ("Draft",)

# Container.status is presence-based (Booked / In_Depot / Available / Gate_Out).
# `Gate_Out` is terminal; everything else with no open order maps to `available`.
_GATE_OUT_RAW = {"Gate_Out"}

# Fields surfaced in the tank list (kept lean for the < 2s/1000-tank target).
_LIST_FIELDS = [
	"name",
	"container_no",
	"container_type",
	"principal",
	"depot",
	"yard_zone",
	"status",
	"last_order_bongkar",
]


def _apply_user_depot_scope(filters, depot):
	"""Intersect a Container query's depot filter with the user's allowed depots.

	Container has no Branch field, so the native Branch User Permission does not
	scope it — we filter on ``depot`` explicitly. Returns the (possibly updated)
	filters dict, or None to signal 'no results' (the requested depot is outside
	the user's branch scope)."""
	allowed = get_user_depots()
	if allowed is None:
		if depot:
			filters["depot"] = depot
		return filters
	if depot:
		if depot not in allowed:
			return None
		filters["depot"] = depot
	else:
		filters["depot"] = ["in", allowed]
	return filters


def derive_status(raw_status, in_progress=False, pending=False, draft=False):
	"""Collapse a raw Container.status + its order-state signals into one Monitor bucket.

	Precedence (most-advanced order state wins): a gated-out tank is terminal; then a
	started job (`in_progress`); then a queued/awaiting job (`pending`); then an
	unsubmitted M&R (`draft`); else the tank has no open order -> `available` (includes a
	tank just gated in with nothing raised on it yet).
	"""
	if raw_status in _GATE_OUT_RAW:
		return "gate_out"
	if in_progress:
		return "in_progress"
	if pending:
		return "pending"
	if draft:
		return "draft"
	return "available"


# Order status -> (bucket state) per doctype, so a row can also name WHICH order drives it.
_CLEANING_STATE = {s: "in_progress" for s in IN_PROGRESS_CLEANING}
_CLEANING_STATE.update({s: "pending" for s in PENDING_CLEANING})
_REPAIR_STATE = {s: "in_progress" for s in IN_PROGRESS_REPAIR}
_REPAIR_STATE.update({s: "pending" for s in PENDING_REPAIR})
_REPAIR_STATE.update({s: "draft" for s in DRAFT_REPAIR})
_STATE_RANK = {"draft": 1, "pending": 2, "in_progress": 3}


def _driving_orders(names):
	"""Map container -> the order that drives its Monitor bucket: the most-advanced
	(in_progress > pending > draft) Cleaning/M&R order, as
	``{"state", "kind", "doctype", "name", "status"}``. Restricted to ``names``."""
	if not names:
		return {}
	rows = []
	for r in frappe.get_all(
		"Cleaning Order",
		filters={"container": ["in", names], "status": ["in", list(_CLEANING_STATE)]},
		fields=["name", "container", "status"],
	):
		rows.append((r.container, _CLEANING_STATE[r.status], "Cleaning", "Cleaning Order", r.name, r.status))
	for r in frappe.get_all(
		"Repair Order",
		filters={"container": ["in", names], "status": ["in", list(_REPAIR_STATE)]},
		fields=["name", "container", "status"],
	):
		rows.append((r.container, _REPAIR_STATE[r.status], "M&R", "Repair Order", r.name, r.status))
	out = {}
	for container, state, kind, doctype, name, status in rows:
		cur = out.get(container)
		if cur is None or _STATE_RANK[state] > _STATE_RANK[cur["state"]]:
			out[container] = {"state": state, "kind": kind, "doctype": doctype, "name": name, "status": status}
	return out


def _order_ref(drv):
	"""The frontend link payload for a driving order (or None)."""
	if not drv:
		return None
	return {"kind": drv["kind"], "doctype": drv["doctype"], "name": drv["name"], "status": drv["status"]}


def _pt_due_set(names):
	"""Container names whose next periodic test (``Container.next_pt_due``) falls within the
	reminder horizon — same horizon + source as ``remind_periodic_test_due`` so counts
	reconcile. The Container master is the single source of truth for the next due-date."""
	if not names:
		return set()
	horizon = add_to_date(getdate(today()), days=PT_REMINDER_DAYS)
	rows = frappe.get_all(
		"Container",
		filters={"name": ["in", names], "next_pt_due": ["is", "set"]},
		fields=["name", "next_pt_due"],
	)
	return {r.name for r in rows if r.next_pt_due and getdate(r.next_pt_due) <= horizon}


@frappe.whitelist(methods=["GET"])
def get_inventory_summary(depot=None):
	"""Status-count header + periodic-test-due count, depot-scoped.

	GET /api/v1/ess/inventory-summary
	"""
	require_menu("monitor")

	filters = {"status": ["not in", EXCLUDED_FROM_INVENTORY]}
	scoped = _apply_user_depot_scope(filters, depot)
	if scoped is None:
		return {"success": True, "counts": {b: 0 for b in BUCKETS}, "periodic_test_due": 0, "total": 0}
	filters = scoped

	# Permission-aware: User Permissions on Depot (and DocPerms) filter this.
	containers = frappe.get_list(
		"Container",
		filters=filters,
		fields=["name", "status"],
		limit_page_length=0,
	)
	names = [c.name for c in containers]
	driving = _driving_orders(names)
	pt_due = _pt_due_set(names)

	counts = {b: 0 for b in BUCKETS}
	for c in containers:
		st = (driving.get(c.name) or {}).get("state")
		bucket = derive_status(c.status, st == "in_progress", st == "pending", st == "draft")
		counts[bucket] += 1

	return {
		"success": True,
		"counts": counts,
		"periodic_test_due": len(pt_due),
		"total": len(names),
	}


@frappe.whitelist(methods=["GET"])
def get_tank_list(
	search=None, principal=None, status=None, depot=None,
	today=0, start=0, page_length=50,
):
	"""Searchable / filterable / paginated tank list with derived status.

	A custom endpoint (not /api/resource) is required because the status filter
	and the rows themselves expose the *derived* bucket, which has no column to
	filter on server-side. Container reads remain permission-aware.

	GET /api/v1/ess/tank-list
	"""
	require_menu("monitor")

	start = cint(start)
	page_length = cint(page_length) or 50
	# Tolerate client quirks where an absent filter arrives as "" / "undefined".
	if status in (None, "", "undefined", "null"):
		status = None
	elif status not in BUCKETS:
		frappe.throw(frappe._("Invalid status filter: {0}").format(status), frappe.ValidationError)

	filters = {"status": ["not in", EXCLUDED_FROM_INVENTORY]}
	if principal:
		filters["principal"] = principal
	scoped = _apply_user_depot_scope(filters, depot)
	if scoped is None:
		return {"success": True, "total": 0, "start": start, "page_length": page_length, "items": []}
	filters = scoped
	if search:
		# PRD: search by tank number.
		filters["container_no"] = ["like", f"%{search.strip()}%"]

	rows = frappe.get_list(
		"Container",
		filters=filters,
		fields=_LIST_FIELDS,
		order_by="container_no asc",
		limit_page_length=0,
	)
	names = [r.name for r in rows]
	driving = _driving_orders(names)
	pt_due = _pt_due_set(names)

	today_flag = cint(today)
	today_set = None
	if today_flag and names:
		today_set = set(
			frappe.get_all(
				"Container Activity",
				filters={"container": ["in", names], "activity_time": [">=", frappe.utils.today()]},
				pluck="container",
				distinct=True,
			)
		)

	items = []
	for r in rows:
		drv = driving.get(r.name)
		st = (drv or {}).get("state")
		bucket = derive_status(r.status, st == "in_progress", st == "pending", st == "draft")
		if status and bucket != status:
			continue
		if today_set is not None and r.name not in today_set:
			continue
		items.append(
			{
				"name": r.name,
				"container_no": r.container_no,
				"container_type": r.container_type,
				"principal": r.principal,
				"depot": r.depot,
				"status": bucket,
				"raw_status": r.status,  # exact Container.status (drives the gate-out action eligibility)
				"order_bongkar": r.last_order_bongkar,
				"pt_due": r.name in pt_due,
				# Which order put the tank in this bucket (draft/pending/in_progress) —
				# lets the UI say "Draft M&R" and link straight to the order.
				"order": _order_ref(drv) if bucket in ("draft", "pending", "in_progress") else None,
			}
		)

	total = len(items)
	return {
		"success": True,
		"total": total,
		"start": start,
		"page_length": page_length,
		"items": items[start : start + page_length],
	}


@frappe.whitelist(methods=["GET"])
def list_container_principals():
	"""Distinct principals (Tank Owners) that have at least one in-depot container in the
	caller's branch scope — drives the Monitor Container principal filter.

	GET /api/v1/ess/container-principals
	"""
	require_menu("monitor")
	filters = {"status": ["not in", EXCLUDED_FROM_INVENTORY], "principal": ["is", "set"]}
	scoped = _apply_user_depot_scope(filters, None)
	if scoped is None:
		return {"principals": []}
	names = sorted({n for n in frappe.get_all("Container", filters=scoped, pluck="principal", distinct=True) if n})
	labels = (
		{c.name: c.customer_name for c in frappe.get_all(
			"Customer", filters={"name": ["in", names]}, fields=["name", "customer_name"]
		)} if names else {}
	)
	return {"principals": [{"name": n, "label": labels.get(n) or n} for n in names]}


@frappe.whitelist(methods=["GET"])
def list_user_depots():
	"""Active depots the caller may see (branch-scoped) — drives the Monitor depot filter.

	GET /api/v1/ess/user-depots. Returns [{code, name}]; empty when the user has no depot
	access. An unrestricted user (get_user_depots -> None) gets every active depot.
	"""
	require_menu("monitor")
	allowed = get_user_depots()
	filters = {"is_active": 1}
	if allowed is not None:
		if not allowed:
			return {"depots": []}
		filters["name"] = ["in", allowed]
	rows = frappe.get_all(
		"Depot", filters=filters, fields=["name", "depot_name"], order_by="name asc"
	)
	return {"depots": [{"code": d.name, "name": d.depot_name or d.name} for d in rows]}


@frappe.whitelist(methods=["GET"])
def get_tank_detail(container):
	"""Single-tank detail with derived status + periodic-test-due flag.

	GET /api/v1/ess/tank-detail
	"""
	require_menu("monitor")
	# Enforces both DocPerm read and any User Permission (depot) on this record.
	frappe.has_permission("Container", doc=container, ptype="read", throw=True)

	doc = frappe.get_doc("Container", container)
	drv = _driving_orders([doc.name]).get(doc.name)
	st = (drv or {}).get("state")
	pt_due = _pt_due_set([doc.name])
	bucket = derive_status(doc.status, st == "in_progress", st == "pending", st == "draft")

	return {
		"success": True,
		"name": doc.name,
		"container_no": doc.container_no,
		"container_type": doc.container_type,
		"size": doc.size,
		"principal": doc.principal,
		"depot": doc.depot,
		"yard_zone": doc.yard_zone,
		"current_location": doc.current_location,
		"last_cargo": doc.last_cargo,
		"capacity": doc.capacity,
		"tare_weight": doc.tare_weight,
		"max_gross_weight": doc.max_gross_weight,
		"last_test_date": str(doc.last_test_date) if doc.last_test_date else None,
		"next_pt_due": str(doc.next_pt_due) if doc.next_pt_due else None,
		"serial_no": doc.serial_no,
		"eir_in_date": str(doc.eir_in_date) if doc.eir_in_date else None,
		"eir_out_date": str(doc.eir_out_date) if doc.eir_out_date else None,
		"status": bucket,
		"pt_due": bool(pt_due),
		"order": _order_ref(drv) if bucket in ("draft", "pending", "in_progress") else None,
	}


def _count_active_job_containers(allowed) -> int:
	"""Distinct containers with work still open on them — Gap Analysis §4.8.4.

	The supervisor card people actually asked for. "±800 tanks in the yard" tells a
	supervisor nothing; "31 tanks with a job running" is the number they chase. Open
	means the same thing it means everywhere else in the app — see
	``container_status.container_open_orders``, which this deliberately mirrors: a draft
	EIR-In, or a Cleaning / M&R / Periodic Test order not yet finished. EIR-Out is
	excluded there and excluded here.
	"""
	from container_depot.container_depot.container_status import (
		_DONE_CLEANING,
		_DONE_PERIODIC,
		_DONE_REPAIR,
	)

	scope = {} if allowed is None else {"depot": ["in", allowed or [""]]}
	containers = set(
		frappe.get_all(
			"Inspection",
			filters={**scope, "inspection_type": "EIR-In", "docstatus": 0},
			pluck="container",
		)
	)
	for doctype, done in (
		("Cleaning Order", _DONE_CLEANING),
		("Repair Order", _DONE_REPAIR),
		("Periodic Test Order", _DONE_PERIODIC),
	):
		containers |= set(
			frappe.get_all(
				doctype,
				filters={**scope, "status": ["not in", done], "docstatus": ["<", 2]},
				pluck="container",
			)
		)
	containers.discard(None)
	return len(containers)


@frappe.whitelist(methods=["GET"])
def get_dashboard_summary(depot=None):
	"""Aggregated home-dashboard payload, depot/branch-scoped — one GET so the PWA
	home screen loads every KPI in a single round-trip.

	Scoped to the caller's menu (§6): a section is present only when the caller may open
	the page behind it, so Team Cleaning gets the cleaning queue and not the gate counts.
	The mapping is DERIVED from ``allowed_menu()`` rather than from a second role table —
	one place decides who sees what, and the dashboard cannot drift away from the menu.

	Sections, each gated on its menu key:

	* ``counts`` / ``total`` — container per status bucket (``monitor``)
	* ``periodic_test_due`` — tanks past their next test date (``periodicTest``)
	* ``today`` — Gate In / Out (``gate``), EIR submitted today (``eir``)
	* ``pending`` — per-worklist open counts, one key per menu
	* ``active_jobs`` — tanks with a job running; supervisors only (every menu)

	A caller with no field role gets ``{"success": True, "menu": []}`` and nothing else —
	the PWA is open to them, it is simply empty.

	GET /api/v1/ess/dashboard-summary
	"""
	from container_depot.ess.context import MENU_KEYS, allowed_menu

	_require_authenticated_user()
	menu = set(allowed_menu())
	if not menu:
		return {"success": True, "menu": []}

	from container_depot.container_depot import cleaning, eir, mr, position_survey

	allowed = get_user_depots()  # None = unrestricted; [] = no depot access
	out = {"success": True, "menu": sorted(menu)}

	# 1) Container-per-status buckets (+ periodic-test-due) — reuse the summary. One
	# query serves both cards, so compute it when either menu is present.
	if {"monitor", "periodicTest"} & menu:
		summary = get_inventory_summary(depot)
		if "monitor" in menu:
			out["counts"] = summary["counts"]
			out["total"] = summary["total"]
		if "periodicTest" in menu:
			out["periodic_test_due"] = summary["periodic_test_due"]

	# 2) Today's activity from the Container Activity log (depot-scoped).
	act_filters = {"activity_time": [">=", today()]}
	if allowed is not None:
		act_filters["depot"] = ["in", allowed or [""]]
	today_activity = {}
	if "gate" in menu:
		today_activity["gate_in"] = frappe.db.count(
			"Container Activity", {**act_filters, "activity_type": "Gate In"}
		)
		today_activity["gate_out"] = frappe.db.count(
			"Container Activity", {**act_filters, "activity_type": "Gate Out"}
		)
	if "eir" in menu:
		today_activity["eir"] = frappe.db.count(
			"Container Activity", {**act_filters, "activity_type": "Inspection (EIR)"}
		)
	if today_activity:
		out["today"] = today_activity

	# 3) Pending work — totals from the same worklists the PWA pages use (each is
	# branch-scoped internally; page_length=1 keeps the row fetch minimal — `total`
	# is the full count regardless).
	pending = {}
	if "eir" in menu:
		pending["eir_in"] = eir.list_pending_eirs(page_length=1)["total"]
		pending["eir_out"] = eir.list_pending_eir_out(page_length=1)["total"]
	if "cleaning" in menu:
		pending["cleaning"] = cleaning.list_open_cleaning_orders(page_length=1)["total"]
	if "mr" in menu:
		mr_appr_filters = {"status": "Pending Approval"}
		if allowed is not None:
			mr_appr_filters["depot"] = ["in", allowed or [""]]
		pending["mr_open"] = mr.list_open_mr_orders(page_length=1)["total"]
		pending["mr_approval"] = frappe.db.count("Repair Order", mr_appr_filters)
	if "surveyPos" in menu:
		pending["position_survey"] = position_survey.list_pending_surveys(page_length=1)["total"]
	if "posFix" in menu:
		pending["position_fix"] = position_survey.list_surveyed(page_length=1)["total"]
	if pending:
		out["pending"] = pending

	# 4) Supervisor-only. "Every menu" is what SPV Lapangan means, so deriving it from
	# the menu keeps the role name out of the code — a second supervisor role added from
	# the UI gets this card too, with no deploy.
	if menu == set(MENU_KEYS):
		out["active_jobs"] = _count_active_job_containers(allowed)

	return out


@frappe.whitelist(methods=["GET"])
def activity_history(start=0, page_length=10, search=None):
	"""GET /api/v1/ess/activity-history — Container Activity timeline (Monitor "Riwayat")."""
	require_menu("monitor")
	return container_activity.list_activity_history(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def activity_detail(name=None):
	"""GET /api/v1/ess/activity-detail — one Container Activity record's full detail."""
	require_menu("monitor")
	return container_activity.get_activity_detail(name)
