"""Yard placement logic — Depot Storage feature (SOP: Operator Kalmar menyusun
isotank sesuai status).

Single source of truth for the PWA + Desk + automation, mirroring the
``operations.eir`` pattern: the ``ess.yard`` endpoints are thin auth wrappers over
the functions here.

What lives here:
- :data:`STATUS_TO_CATEGORY` — maps a raw ``Container.status`` to the functional
  Yard Zone *category* the tank belongs in per the OAK workflow SOP.
- :func:`recommend_zones` — given a container, return the candidate zones (in its
  depot, in the target category) ranked emptiest-first.
- :func:`zone_occupancy` — count vs capacity per Yard Zone for the storage view.
- :func:`place_container` — record a placement as an audited Container Movement
  (``event_type="Yard"``), enforcing the SOP stacking limits.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.query_builder.functions import Count
from frappe.utils import cint

# Raw Container.status -> Yard Zone category (SOP workflow). ``None`` = the tank is
# not physically placeable in the depot (pre-arrival / already gated out), so it
# yields no recommendation. ``Gate_In`` defaults to the dirty-queue but is refined
# by the latest inspection's tank condition (see :func:`_target_category`).
STATUS_TO_CATEGORY = {
	"Booked": None,
	"Gate_In": "Empty Dirty Queue",
	"Inspecting": "Survey",
	"Needs_Cleaning": "Empty Dirty Queue",
	"Pending_Cleaning": "Empty Dirty Queue",
	"Cleaning_In_Progress": "Cleaning Bay",
	"Awaiting_Recleaning_Approval": "Cleaning Bay",
	"Recleaning_In_Progress": "Cleaning Bay",
	"Cleaning_Completed": "Ready",
	"Pending_Survey": "Survey",
	"Survey_In_Progress": "Survey",
	"Awaiting_MR_Approval": "Workshop",
	"Repair_In_Progress": "Workshop",
	"Available": "Ready",
	"Released_Pending_Pickup": "Ready",
	"Gate_Out": None,
}

# Statuses that no longer occupy a yard slot — excluded from occupancy counts.
_NOT_OCCUPYING = ("Gate_Out",)


def _resolve_container(container_no):
	"""Return the Container doc for a container number (lenient, case-insensitive)."""
	if not container_no or not isinstance(container_no, str):
		frappe.throw(_("container_no is required."), frappe.ValidationError)
	candidate = container_no.strip().upper()
	name = frappe.db.get_value("Container", {"container_no": candidate}, "name") or (
		candidate if frappe.db.exists("Container", candidate) else None
	)
	if not name:
		frappe.throw(_("Container {0} not found.").format(candidate), frappe.DoesNotExistError)
	return frappe.get_doc("Container", name)


def _current_position(container):
	"""The tank's current placement (zone + row/tier/bay), or ``None`` if not yet placed.

	Lets the recommendation panel show where the tank sits right now before suggesting
	where it should go next."""
	zone = container.get("yard_zone")
	if not zone:
		return None
	row, tier, bay = container.get("row"), container.get("tier"), container.get("bay")
	if not (row or tier or bay):
		slot = None
	else:
		slot = " · ".join(
			p for p in (
				f"Baris {row}" if row else None,
				f"Tumpukan {tier}" if tier else None,
				f"Bay {bay}" if bay else None,
			) if p
		)
	return {
		"zone_code": zone,
		"zone_name": frappe.db.get_value("Yard Zone", zone, "zone_name") or zone,
		"row": row,
		"tier": tier,
		"bay": bay,
		"slot": slot,
	}


def _latest_tank_condition(container_name):
	"""Most recent submitted Inspection tank condition (Empty Clean/Dirty/Laden), or None."""
	rows = frappe.get_all(
		"Inspection",
		filters={"container": container_name, "docstatus": 1},
		fields=["tank_status"],
		order_by="creation desc",
		limit=1,
	)
	return rows[0].tank_status if rows else None


def _latest_eir(container_name):
	"""Most recent SUBMITTED EIR (EIR-In / EIR-Out) for a container, with its damage rows.

	Returns ``None`` when the container has no submitted EIR yet. The summary drives both
	the placement target category (:func:`_target_category`) and the recommendation panel's
	"last inspection" card, so the operator sees what the EIR found before placing the tank.
	"""
	rows = frappe.get_all(
		"Inspection",
		filters={
			"container": container_name,
			"docstatus": 1,
			"inspection_type": ["in", ["EIR-In", "EIR-Out"]],
		},
		fields=[
			"name", "inspection_id", "inspection_type", "eir_date",
			"tank_status", "cargo", "remarks", "owner", "inspector",
		],
		order_by="creation desc",
		limit=1,
	)
	if not rows:
		return None
	eir = rows[0]
	damages = frappe.get_all(
		"Inspection Damage Entry",
		filters={"parent": eir.name, "parenttype": "Inspection"},
		fields=[
			"checklist_item", "damage_description", "damage_type", "repair_code",
			"severity", "area", "component", "part_face",
		],
		order_by="idx asc",
		limit_page_length=0,
	)
	# Photos are stored per checklist item (Inspection Item Photo), not on the damage
	# row — group them so each damage can show the photos taken for its item.
	photos_by_item = {}
	for p in frappe.get_all(
		"Inspection Item Photo",
		filters={"parent": eir.name, "parenttype": "Inspection"},
		fields=["checklist_item", "photo"],
		order_by="idx asc",
		limit_page_length=0,
	):
		if p.photo:
			photos_by_item.setdefault(p.checklist_item, []).append(p.photo)
	# Resolve the damage / repair code masters to their human descriptions — these are
	# the real captured data (severity is not collected in the PWA, it defaults to Minor).
	dmg_codes = list({d.damage_type for d in damages if d.damage_type})
	rep_codes = list({d.repair_code for d in damages if d.repair_code})
	dmg_desc = (
		{r.name: r.description for r in frappe.get_all(
			"Inspection Damage Code", filters={"name": ["in", dmg_codes]}, fields=["name", "description"]
		)} if dmg_codes else {}
	)
	rep_desc = (
		{r.name: r.description for r in frappe.get_all(
			"Inspection Repair Code", filters={"name": ["in", rep_codes]}, fields=["name", "description"]
		)} if rep_codes else {}
	)
	for d in damages:
		d["damage_label"] = dmg_desc.get(d.damage_type)
		d["repair_label"] = rep_desc.get(d.repair_code)
		d["photos"] = photos_by_item.get(d.checklist_item, [])

	creator = eir.owner
	return {
		"name": eir.name,
		"inspection_id": eir.inspection_id or eir.name,
		"inspection_type": eir.inspection_type,
		"eir_date": str(eir.eir_date)[:10] if eir.eir_date else None,
		"tank_status": eir.tank_status,
		"cargo": eir.cargo,
		"remarks": eir.remarks,
		"created_by": creator,
		"created_by_name": (frappe.db.get_value("User", creator, "full_name") or creator) if creator else None,
		"damages": damages,
		"damage_count": len(damages),
	}


def _target_category(container, eir=None):
	"""The Yard Zone category a container should go to, driven by its latest EIR.

	Priority (per ops SOP), based on the most recent submitted EIR:
	1. any damage logged  -> ``Workshop`` (needs repair before anything else)
	2. tank ``Empty Dirty`` -> ``Empty Dirty Queue`` (queue for cleaning)
	3. tank ``Empty Clean`` -> ``Survey`` (inspecting)

	Laden tanks and containers without a submitted EIR fall back to the raw
	``Container.status`` mapping (with the Gate_In condition split preserved).
	"""
	if eir is None:
		eir = _latest_eir(container.name)
	if eir:
		if eir.get("damage_count"):
			return "Workshop"
		if eir.get("tank_status") == "Empty Dirty":
			return "Empty Dirty Queue"
		if eir.get("tank_status") == "Empty Clean":
			return "Survey"

	category = STATUS_TO_CATEGORY.get(container.status)
	if container.status == "Gate_In":
		condition = (eir or {}).get("tank_status") or _latest_tank_condition(container.name)
		if condition == "Empty Clean":
			return "Empty Clean"
		if condition == "Empty Dirty":
			return "Empty Dirty Queue"
	return category


def _occupancy_map(zone_names=None):
	"""Return {zone_name: occupied_count} for the given zones (or all), excluding
	tanks that have left the yard."""
	if zone_names is not None and not zone_names:
		return {}
	container = frappe.qb.DocType("Container")
	query = (
		frappe.qb.from_(container)
		.select(container.yard_zone, Count(container.name).as_("cnt"))
		.where(container.status.notin(list(_NOT_OCCUPYING)))
		.groupby(container.yard_zone)
	)
	if zone_names is not None:
		query = query.where(container.yard_zone.isin(list(zone_names)))
	else:
		query = query.where(container.yard_zone.isnotnull()).where(container.yard_zone != "")
	rows = query.run(as_dict=True)
	return {r.yard_zone: cint(r.cnt) for r in rows if r.yard_zone}


def _zone_view(zone, occupied):
	"""Shape one Yard Zone master row + its live count into a view dict."""
	capacity = cint(zone.capacity)
	free = max(capacity - occupied, 0) if capacity else None
	utilization = round((occupied / capacity) * 100, 1) if capacity else None
	return {
		"zone_code": zone.name,
		"zone_name": zone.zone_name,
		"depot": zone.depot,
		"block": zone.block or "",
		"category": zone.category,
		"occupied": occupied,
		"capacity": capacity,
		"free": free,
		"utilization": utilization,
		"is_full": bool(capacity) and occupied >= capacity,
		"max_rows": cint(zone.max_rows),
		"max_rows_full": cint(zone.max_rows_full),
		"max_tiers": cint(zone.max_tiers),
	}


def zone_occupancy(depot=None, depots=None):
	"""Occupancy vs capacity for active Yard Zones, optionally restricted to one
	depot (``depot``) or a set of depots (``depots``). ``depots=[]`` yields no rows
	(an explicitly empty branch scope).

	Powers the Depot Storage overview. Returns a flat list sorted by depot, block,
	then zone code; the PWA groups it for display.
	"""
	filters = {"is_active": 1}
	if depot:
		filters["depot"] = depot
	elif depots is not None:
		if not depots:
			return []
		filters["depot"] = ["in", depots]
	zones = frappe.get_all(
		"Yard Zone",
		filters=filters,
		fields=[
			"name", "zone_name", "depot", "block", "category",
			"capacity", "max_rows", "max_rows_full", "max_tiers",
		],
		order_by="depot asc, block asc, name asc",
	)
	occupancy = _occupancy_map([z.name for z in zones])
	return [_zone_view(z, occupancy.get(z.name, 0)) for z in zones]


def depot_rollup(zone_views):
	"""Aggregate zone occupancy into per-depot summaries for the accordion headers.

	Returns {depot_code: {occupied, capacity, full_count, zone_count, utilization}}.
	"""
	by_depot = {}
	for z in zone_views:
		d = by_depot.setdefault(
			z["depot"], {"occupied": 0, "capacity": 0, "full_count": 0, "zone_count": 0}
		)
		d["occupied"] += z["occupied"]
		d["capacity"] += z["capacity"] or 0
		d["full_count"] += 1 if z["is_full"] else 0
		d["zone_count"] += 1
	out = {}
	for code, d in by_depot.items():
		util = round((d["occupied"] / d["capacity"]) * 100, 1) if d["capacity"] else None
		out[code] = {**d, "utilization": util}
	return out


def zone_tank_list(zone, search=None, start=0, page_length=50):
	"""Containers physically in ``zone`` — the exact set :func:`zone_occupancy` counts.

	Membership is by ``yard_zone`` + "still occupies a slot" (status not in
	``_NOT_OCCUPYING``), so this list can never disagree with the zone card's ``X/Y``.
	Unlike the generic inventory list it does NOT apply the per-container branch-depot
	scope (the zone itself is what's branch-checked, by the caller) and reads with
	``frappe.get_all`` (same permission-free read as the occupancy count) — a tank
	whose own ``depot`` is blank or stale therefore still shows. Optional container_no
	search + pagination; each row carries the derived UI status bucket.
	"""
	from container_depot.ess.inventory import (
		_LIST_FIELDS,
		_open_service_sets,
		_pt_due_set,
		derive_status,
	)

	start = cint(start)
	page_length = cint(page_length) or 50
	# Guard against junk search values: a GET caller (or frappe-ui serialising an
	# `undefined`) can send the literal strings "undefined"/"null", which must not
	# become a `LIKE "%undefined%"` that hides every tank in the zone.
	term = str(search).strip() if search is not None else ""
	if term.lower() in ("undefined", "null", "none"):
		term = ""
	filters = {"yard_zone": zone, "status": ["not in", list(_NOT_OCCUPYING)]}
	if term:
		filters["container_no"] = ["like", f"%{term}%"]
	rows = frappe.get_all(
		"Container", filters=filters, fields=_LIST_FIELDS, order_by="container_no asc"
	)
	names = [r.name for r in rows]
	cleaning, repair, inspection = _open_service_sets(names)
	pt_due = _pt_due_set(names)
	items = [
		{
			"name": r.name,
			"container_no": r.container_no,
			"container_type": r.container_type,
			"principal": r.principal,
			"depot": r.depot,
			"yard_zone": r.yard_zone,
			"status": derive_status(
				r.status, r.name in cleaning, r.name in repair, r.name in inspection
			),
			"pt_due": r.name in pt_due,
		}
		for r in rows
	]
	return {
		"success": True,
		"total": len(items),
		"start": start,
		"page_length": page_length,
		"items": items[start : start + page_length],
	}


def _scope_depots(container):
	"""Ordered candidate depots for placing this container (per-branch policy).

	The container's own depot comes first, then every other active depot in the
	same branch — so a tank in a depot that has no zones of its own (or no zone of
	the target category) can still be placed in a sibling depot of the same branch.
	"""
	own = container.depot
	if not own:
		return [], None
	branch = frappe.db.get_value("Depot", own, "branch")
	depots = [own]
	if branch:
		for d in frappe.get_all(
			"Depot", filters={"branch": branch, "is_active": 1}, pluck="name", order_by="name asc"
		):
			if d not in depots:
				depots.append(d)
	return depots, branch


def recommend_zones(container_no):
	"""Rank candidate zones for a container and list every in-scope zone.

	Scope = the container's own depot first, then sibling depots in the same branch
	(:func:`_scope_depots`). ``zones`` are the target-category candidates ranked
	same-depot-first then emptiest-first, with the first non-full one flagged
	``recommended``. ``all_zones`` is every active zone in scope (all categories) so
	the operator can always place a tank manually, even when ``zones`` is empty.
	"""
	container = _resolve_container(container_no)
	eir = _latest_eir(container.name)
	category = _target_category(container, eir)
	depots, branch = _scope_depots(container)
	result = {
		"container_no": container.container_no,
		"status": container.status,
		"depot": container.depot,
		"branch": branch,
		"condition": (eir or {}).get("tank_status") or _latest_tank_condition(container.name),
		"target_category": category,
		"eir": eir,
		"current": _current_position(container),
		"zones": [],
		"all_zones": [],
	}
	if not depots:
		return result

	zones = frappe.get_all(
		"Yard Zone",
		filters={"is_active": 1, "depot": ["in", depots]},
		fields=[
			"name", "zone_name", "depot", "block", "category",
			"capacity", "max_rows", "max_rows_full", "max_tiers",
		],
		order_by="name asc",
	)
	occupancy = _occupancy_map([z.name for z in zones])
	own = container.depot

	def view(z):
		v = _zone_view(z, occupancy.get(z.name, 0))
		v["same_depot"] = z.depot == own
		return v

	all_views = [view(z) for z in zones]
	# Manual list: own-depot zones first, then grouped by category for the picker.
	all_views.sort(key=lambda v: (not v["same_depot"], v["category"], v["zone_name"]))
	result["all_zones"] = all_views

	if category:
		# Recommended candidates: own depot first, then emptiest (unknown headroom last).
		cands = [v for v in all_views if v["category"] == category]
		cands.sort(key=lambda v: (not v["same_depot"], v["utilization"] is None, v["utilization"] or 0))
		for v in cands:
			if not v["is_full"]:
				v["recommended"] = True
				break
		result["zones"] = cands
	return result


def place_container(container_no, zone, row=None, tier=None, bay=None, moved_by=None):
	"""Record a tank placement as an audited Container Movement (Yard event).

	Enforces the SOP stacking limits (vertical tier, horizontal row with the
	depot-full tolerance) and the zone capacity, then inserts the Movement. The
	Movement's ``after_insert`` syncs zone/row/bay/tier back onto the Container, so
	this single write keeps the occupancy view accurate.

	Returns the new placement. Callers are responsible for authorisation.
	"""
	container = _resolve_container(container_no)
	if not zone or not frappe.db.exists("Yard Zone", zone):
		frappe.throw(_("Yard Zone {0} not found.").format(zone or ""), frappe.ValidationError)

	z = frappe.get_doc("Yard Zone", zone)
	tier = cint(tier) if tier not in (None, "") else None
	if tier is not None:
		if tier < 1:
			frappe.throw(_("Tier must be at least 1."), frappe.ValidationError)
		if z.max_tiers and tier > z.max_tiers:
			frappe.throw(
				_("Tier {0} exceeds the SOP stacking limit of {1} for zone {2}.").format(
					tier, z.max_tiers, z.zone_name
				),
				frappe.ValidationError,
			)

	# Row is free-text (may be a label); only range-check when it's numeric.
	row = (str(row).strip() or None) if row not in (None, "") else None
	if row is not None and row.isdigit():
		row_limit = cint(z.max_rows_full) or cint(z.max_rows)
		if row_limit and int(row) > row_limit:
			frappe.throw(
				_("Row {0} exceeds the SOP limit of {1} rows for zone {2}.").format(
					row, row_limit, z.zone_name
				),
				frappe.ValidationError,
			)

	# Capacity guard — count peers already in the zone (excluding this container).
	if z.capacity:
		occupied = frappe.db.count(
			"Container",
			{
				"yard_zone": zone,
				"status": ["not in", _NOT_OCCUPYING],
				"name": ["!=", container.name],
			},
		)
		if occupied >= z.capacity:
			frappe.throw(
				_("Zone {0} is full ({1}/{1}).").format(z.zone_name, z.capacity),
				frappe.ValidationError,
			)

	movement = frappe.get_doc({
		"doctype": "Container Movement",
		"container": container.name,
		"event_type": "Yard",
		"to_zone": zone,
		"to_row": row,
		"to_bay": (str(bay).strip() or None) if bay not in (None, "") else None,
		"to_tier": tier,
		"moved_by": moved_by or frappe.session.user,
	})
	movement.insert(ignore_permissions=True)

	return {
		"success": True,
		"container_no": container.container_no,
		"movement": movement.name,
		"yard_zone": zone,
		"zone_name": z.zone_name,
		"row": row,
		"bay": movement.to_bay,
		"tier": tier,
	}
