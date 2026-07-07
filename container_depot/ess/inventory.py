"""ESS PWA read endpoints — Feature F1 (Tank Inventory & Live Status).

All endpoints are GET, authenticated (Guest rejected via the shared
``_require_authenticated_user`` guard), and **permission-aware**: container
reads go through ``frappe.get_list`` / ``frappe.has_permission``, so the
Custom DocPerm matrix seeded by ``install.py`` *and* any ``User Permission``
(e.g. depot scoping on ``Container.depot``) filter the results automatically.
There is no permission logic in the PWA.

Status is **derived server-side** here — the raw ``Container.status`` Select
carries the full lifecycle (normalised in B0: duplicate removed, portal states
added), but the UI only ever needs five buckets. :func:`derive_status` collapses
the raw status (kept in sync with the latest Container Movement by
``Container.on_update``) plus open Repair / Cleaning / Inspection records into
those five canonical buckets.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, cint, getdate, today

from container_depot.api import _require_authenticated_user
from container_depot.operations import container_activity
from container_depot.operations.user_branch import get_user_depots
from container_depot.tasks import PT_REMINDER_DAYS

# Canonical ESS status buckets (keys are stable; labels live in the front-end).
BUCKETS = ("in_depot", "cleaning", "repair_survey", "ready", "gate_out")

# Raw statuses that are NOT physically in the depot yet and must be excluded from
# live inventory counts/lists. `Booked` = a tank reserved by an Container Booking
# whose Container master was created at booking time but has not yet gated in.
EXCLUDED_FROM_INVENTORY = ("Booked",)

# Open-state filters for the service doctypes that override a tank's bucket.
OPEN_CLEANING = ("Pending", "In_Progress")
OPEN_REPAIR = ("Draft", "Pending Approval", "Approved", "In Progress")
OPEN_INSPECTION = ("Draft", "Submitted")

# Container.status is presence-based now (Booked / In_Depot / Available / Gate_Out).
# The cleaning/repair UI buckets are driven entirely by OPEN ORDERS (open_cleaning /
# open_repair / open_inspection), not by the raw status, so those raw sets are empty.
_GATE_OUT_RAW = {"Gate_Out"}
_READY_RAW = {"Available"}
_CLEANING_RAW: set[str] = set()
_REPAIR_RAW: set[str] = set()

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


def derive_status(raw_status, open_cleaning=False, open_repair=False, open_inspection=False):
	"""Collapse a raw Container.status + open-service signals into one bucket.

	Precedence: a gated-out tank is terminal; then active cleaning (an open
	Cleaning Order or a cleaning raw state); then active survey/repair (an open
	Repair Order / Inspection or a survey/repair raw state); then the consolidated
	`Available` ready pool; else the tank is simply in the depot (e.g. just gated
	in, pre-processing). Open work is checked BEFORE the `Available`->ready mapping
	so a tank that is Available but currently being re-cleaned / re-surveyed still
	surfaces the active job in the PWA instead of reading "ready".
	"""
	if raw_status in _GATE_OUT_RAW:
		return "gate_out"
	if open_cleaning or raw_status in _CLEANING_RAW:
		return "cleaning"
	if open_repair or open_inspection or raw_status in _REPAIR_RAW:
		return "repair_survey"
	if raw_status in _READY_RAW:
		return "ready"
	return "in_depot"


def _open_service_sets(names):
	"""Return (cleaning, repair, inspection) sets of container names with an open
	order of each type, restricted to ``names`` (already permission-filtered)."""
	if not names:
		return set(), set(), set()
	cleaning = set(
		frappe.get_all(
			"Cleaning Order",
			filters={"container": ["in", names], "status": ["in", OPEN_CLEANING]},
			pluck="container",
		)
	)
	repair = set(
		frappe.get_all(
			"Repair Order",
			filters={"container": ["in", names], "status": ["in", OPEN_REPAIR]},
			pluck="container",
		)
	)
	inspection = set(
		frappe.get_all(
			"Inspection",
			filters={
				"container": ["in", names],
				"status": ["in", OPEN_INSPECTION],
				"docstatus": ["<", 2],
			},
			pluck="container",
		)
	)
	return cleaning, repair, inspection


def _pt_due_set(names):
	"""Container names with a due/overdue open Periodic Test, using the same
	horizon as the daily ``remind_periodic_test_due`` job so counts reconcile."""
	if not names:
		return set()
	horizon = add_to_date(getdate(today()), days=PT_REMINDER_DAYS)
	rows = frappe.get_all(
		"Periodic Test",
		filters={
			"container": ["in", names],
			"status": ["not in", ["Completed", "Cancelled"]],
			"docstatus": ["<", 2],
		},
		fields=["container", "due_date"],
	)
	return {r.container for r in rows if r.due_date and getdate(r.due_date) <= horizon}


@frappe.whitelist(methods=["GET"])
def get_inventory_summary(depot=None):
	"""Status-count header + periodic-test-due count, depot-scoped.

	GET /api/v1/ess/inventory-summary
	"""
	_require_authenticated_user()

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
	cleaning, repair, inspection = _open_service_sets(names)
	pt_due = _pt_due_set(names)

	counts = {b: 0 for b in BUCKETS}
	for c in containers:
		bucket = derive_status(
			c.status, c.name in cleaning, c.name in repair, c.name in inspection
		)
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
	_require_authenticated_user()

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
	cleaning, repair, inspection = _open_service_sets(names)
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
		bucket = derive_status(
			r.status, r.name in cleaning, r.name in repair, r.name in inspection
		)
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
	_require_authenticated_user()
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
def get_tank_detail(container):
	"""Single-tank detail with derived status + periodic-test-due flag.

	GET /api/v1/ess/tank-detail
	"""
	_require_authenticated_user()
	# Enforces both DocPerm read and any User Permission (depot) on this record.
	frappe.has_permission("Container", doc=container, ptype="read", throw=True)

	doc = frappe.get_doc("Container", container)
	cleaning, repair, inspection = _open_service_sets([doc.name])
	pt_due = _pt_due_set([doc.name])
	bucket = derive_status(
		doc.status, doc.name in cleaning, doc.name in repair, doc.name in inspection
	)

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
	}


@frappe.whitelist(methods=["GET"])
def get_dashboard_summary(depot=None):
	"""Aggregated home-dashboard payload, depot/branch-scoped — one GET so the PWA
	home screen loads every KPI in a single round-trip.

	Pure aggregation: it reuses the existing, validated read functions
	(:func:`get_inventory_summary`, the EIR / Cleaning / M&R worklist totals) —
	the only extra queries are today's activity counts and the M&R "Pending
	Approval" count. Sections:

	* ``counts`` / ``periodic_test_due`` / ``total`` — container per status bucket
	* ``today`` — Gate In / Gate Out / EIR submitted today (Container Activity)
	* ``pending`` — open EIR-In / EIR-Out / Cleaning / M&R (+ M&R awaiting approval)

	GET /api/v1/ess/dashboard-summary
	"""
	_require_authenticated_user()

	from container_depot.operations import cleaning, eir, mr

	allowed = get_user_depots()  # None = unrestricted; [] = no depot access

	# 1) Container-per-status buckets (+ periodic-test-due) — reuse the summary.
	summary = get_inventory_summary(depot)

	# 2) Today's activity from the Container Activity log (depot-scoped).
	act_filters = {"activity_time": [">=", today()]}
	if allowed is not None:
		act_filters["depot"] = ["in", allowed or [""]]
	today_activity = {
		"gate_in": frappe.db.count("Container Activity", {**act_filters, "activity_type": "Gate In"}),
		"gate_out": frappe.db.count("Container Activity", {**act_filters, "activity_type": "Gate Out"}),
		"eir": frappe.db.count("Container Activity", {**act_filters, "activity_type": "Inspection (EIR)"}),
	}

	# 3) Pending work — totals from the same worklists the PWA pages use (each is
	# branch-scoped internally; page_length=1 keeps the row fetch minimal — `total`
	# is the full count regardless).
	mr_appr_filters = {"status": "Pending Approval"}
	if allowed is not None:
		mr_appr_filters["depot"] = ["in", allowed or [""]]
	pending = {
		"eir_in": eir.list_pending_eirs(page_length=1)["total"],
		"eir_out": eir.list_pending_eir_out(page_length=1)["total"],
		"cleaning": cleaning.list_open_cleaning_orders(page_length=1)["total"],
		"mr_open": mr.list_open_mr_orders(page_length=1)["total"],
		"mr_approval": frappe.db.count("Repair Order", mr_appr_filters),
	}

	return {
		"success": True,
		"counts": summary["counts"],
		"periodic_test_due": summary["periodic_test_due"],
		"total": summary["total"],
		"today": today_activity,
		"pending": pending,
	}


@frappe.whitelist(methods=["GET"])
def activity_history(start=0, page_length=10, search=None):
	"""GET /api/v1/ess/activity-history — Container Activity timeline (Monitor "Riwayat")."""
	_require_authenticated_user()
	return container_activity.list_activity_history(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def activity_detail(name=None):
	"""GET /api/v1/ess/activity-detail — one Container Activity record's full detail."""
	_require_authenticated_user()
	return container_activity.get_activity_detail(name)
