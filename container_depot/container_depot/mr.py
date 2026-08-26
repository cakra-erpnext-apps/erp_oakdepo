"""Core M&R (Maintenance & Repair) logic for the PWA Repair Order flow.

Mirrors ``container_depot/cleaning.py``: deliberately free of ``@frappe.whitelist`` so the
same functions back both the ESS PWA wrappers (``ess/repairs.py``) and any Desk /
automation caller — the endpoint layer only adds auth + whitelisting.

Concept (two sections in the PWA):
  1. **Damages** — a read-only snapshot copied from the source EIR's damage entries (with
     photos) when the Draft M&R is auto-created. Pure information: what the EIR found.
  2. **Used Items** — the services / parts actually used, picked from the **owner's Item
     Price** list (service or part). Only the qty is shown (price is hidden but still
     computed for billing). A part row names the gudang it comes from and is issued out of
     it (Material Issue) the moment the owner approves — the workshop cannot fit a part that
     is still on a shelf.
  3. **Work Photos** — proof of the work, one row per photo, each pointing back at the used
     item it proves. A table of its own because the estimate freezes when it leaves Draft
     while the evidence is gathered days later, mid-repair.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from container_depot.container_depot.container_activity import log_doc_note
from container_depot.container_depot.exceptions import AlreadySettled
from container_depot.container_depot.work_claim import filter_claimed, guard_claim
from container_depot.container_depot.worklist import sort_by_priority
from container_depot.container_depot.eir_followups import MR_OPEN_STATUSES
from container_depot.container_depot.service_menu import filter_items_by_menu, is_real_menu
from container_depot.container_depot.user_branch import assert_in_user_branch, get_user_depots, get_user_warehouses
from container_depot.pricing_model import price_list_for_customer, resolve_price

# The Depot Service Menu the M&R item picker is scoped to. When this menu is
# missing / inactive / empty, the picker falls back to all owner-priced items.
MR_MENU = "Maintenance"

# Owner-approval status machine (single source of truth — shared by the controller,
# the ESS/PWA endpoints, and the Desk workflow buttons). The owner must approve the
# estimate (Pending Approval) before any work starts; they may reject, or ask for a
# revision, and may approve only some lines (partial approval, per Repair Used Item).
MR_TRANSITIONS = {
	# Draft is where Admin Ops builds the estimate — they are the first pair of eyes on an
	# M&R, so there is no staging step in front of them; ``publish_to_owner`` takes the
	# estimate straight from Draft to the customer web. Pending Approval -> Draft is the
	# withdraw ("tarik ulang"), which re-opens editing for a re-send.
	#
	# "Approved" straight from Draft / Revision Requested is the Admin-Ops BYPASS (skip the
	# owner). It is code-guarded to Admin Ops in the ESS layer (bypass_approval); the state
	# machine only declares it a legal edge so validate() doesn't reject it.
	#
	# After the owner has agreed, the tail mirrors Cleaning Order exactly: Admin Ops HANDS
	# the job over (Approved -> Pending, ``forward_to_team``) and only then does it appear on
	# the depot PWA worklist; the team starts it (-> In Progress) and finishes it (-> Pending
	# Review); Desk checks the work and finalises it (-> Completed).
	#
	# Approved -> Completed short-circuits that whole tail, and is deliberate: plenty of M&R
	# is a five-minute job the Desk operator watched happen, or work a subcontractor already
	# did. Routing it through the PWA would mean handing it to a team, having them open it,
	# start it and finish it — four presses to record something that is over. The parts have
	# already left stock at approval either way, so nothing is skipped except the dispatch.
	#
	# "Draft" appears on every in-flight status because a human can always mis-enter or miss
	# an item — ``reopen_to_draft`` (Adm Ops) rewinds a Pending Approval / Approved / Pending
	# / In Progress / Pending Review M&R back to an editable Draft to fix it, then it goes
	# through approval again. Completed is deliberately excluded (parts already issued →
	# Cancel instead).
	"Draft": ["Pending Approval", "Approved", "Cancelled"],
	"Revision Requested": ["Pending Approval", "Approved", "Draft", "Cancelled"],  # editable like Draft
	"Pending Approval": ["Approved", "Rejected", "Revision Requested", "Draft", "Cancelled"],
	"Approved": ["Pending", "Completed", "Draft", "Cancelled"],
	"Pending": ["In Progress", "Draft", "Cancelled"],
	"In Progress": ["Pending Review", "Draft", "Cancelled"],
	"Pending Review": ["Completed", "In Progress", "Draft", "Cancelled"],
	# Completed -> In Progress is the reopen (``reopen_completed``): the team asked for the
	# job to be opened again because the WORK was not right. It is the only way out of
	# Completed and it is gated twice — the controller refuses the edge unless
	# ``flags.oak_reopen`` is set, so no generic status endpoint can walk it, and the function
	# itself refuses an order that has already been billed. Not "Draft": the estimate and the
	# parts were right, the repair was not.
	"Completed": ["In Progress"],
	"Rejected": ["Draft"],
	"Cancelled": [],
}
# Statuses where the depot may still edit the estimate (used items) — the two states that
# sit on Admin Ops' desk, before the owner has been asked and after they sent it back.
MR_EDITABLE_STATUSES = ("Draft", "Revision Requested")

# Statuses the customer web may show. The owner only ever sees an estimate Admin Ops has
# explicitly sent them — never a Draft still being arranged.
MR_CUSTOMER_VISIBLE_STATUSES = (
	"Pending Approval", "Approved", "Rejected", "Pending", "In Progress", "Pending Review", "Completed",
)

# Tank-spec fields read from the Container master for the form header.
_CONTAINER_FIELDS = [
	"name", "container_no", "container_type", "principal", "last_cargo", "depot",
	"capacity", "tare_weight", "max_gross_weight", "manufacture_date", "last_test_date",
]


def _guard_container_branch(container_name) -> None:
	"""Block M&R actions on a container outside the user's branch."""
	depot = frappe.db.get_value("Container", container_name, "depot")
	assert_in_user_branch(depot=depot)


# --- owner / pricing helpers -------------------------------------------------
def _principal(ro) -> str | None:
	return ro.principal or frappe.db.get_value("Container", ro.container, "principal")


def _owner_price_list(principal) -> str | None:
	return price_list_for_customer(principal) if principal else None


# --- inventory / warehouse helpers -------------------------------------------
def _resolve_company() -> str | None:
	return frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")


def _container_branch(depot) -> str | None:
	return frappe.db.get_value("Depot", depot, "branch") if depot else None


def _company_warehouses(company, branch=None) -> list:
	filters = {"is_group": 0, "disabled": 0}
	if company:
		filters["company"] = company
	rows = frappe.get_all("Warehouse", filters=filters, fields=["name", "warehouse_name", "branch"], order_by="warehouse_name asc")
	allowed = get_user_warehouses(branch=branch)  # None = unrestricted
	if allowed is not None:
		allowed = set(allowed)
		rows = [r for r in rows if r.name in allowed]
	return rows


def _default_warehouse(company, depot=None) -> str | None:
	rows = _company_warehouses(company, branch=_container_branch(depot))
	if not rows:
		return None
	for r in rows:
		if "stores" in (r.warehouse_name or "").lower():
			return r.name
	return rows[0].name


def _on_hand(item_code, warehouse=None) -> float:
	if not item_code:
		return 0.0
	if warehouse:
		return flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"))
	total = frappe.db.sql("select coalesce(sum(actual_qty), 0) from `tabBin` where item_code = %s", item_code)
	return flt(total[0][0]) if total else 0.0


def _out_of_stock_items(warehouse) -> set:
	"""Stock items the source warehouse cannot supply (no Bin row, or qty <= 0).

	Service items are never in here — a service has nothing to run out of, so it stays
	offerable forever. Returns an empty set when no warehouse is resolved yet (a brand-new
	M&R): we cannot know the stock then, and hiding every part would be worse than showing
	one that later fails at completion.
	"""
	if not warehouse:
		return set()
	stock_items = set(frappe.get_all("Item", filters={"is_stock_item": 1, "disabled": 0}, pluck="name"))
	if not stock_items:
		return set()
	available = set(
		frappe.get_all(
			"Bin",
			filters={"warehouse": warehouse, "item_code": ["in", list(stock_items)], "actual_qty": [">", 0]},
			pluck="item_code",
		)
	)
	return stock_items - available


def _photos_list(value) -> list:
	"""Parse a Damage Entry ``photos`` JSON string into a list of file URLs."""
	if not value:
		return []
	try:
		out = json.loads(value)
		return [u for u in out if u] if isinstance(out, list) else []
	except (ValueError, TypeError):
		return []


# --- warehouse list (branch-filtered) ----------------------------------------
def list_warehouses(repair_order=None, container=None) -> dict:
	"""Gudang options for a Used-Items row, filtered to the container's branch (and to the
	warehouses the caller's branch allows). Backs the Desk row picker."""
	if repair_order and not container:
		container = frappe.db.get_value("Repair Order", repair_order, "container")
	depot = frappe.db.get_value("Container", container, "depot") if container else None
	branch = _container_branch(depot)
	rows = _company_warehouses(_resolve_company(), branch=branch)
	return {"warehouses": rows, "branch": branch}


# --- item picker (priced by owner; service or part) --------------------------
def mr_item_search(search=None, repair_order=None, start=0, page_length=20, warehouse=None, line_type=None) -> dict:
	"""Item picker for the Used-Items section — services AND parts that have a selling
	Item Price in the owner's price list. Stock items carry their on-hand qty (at the gudang
	the row draws from). When the owner has no price list, falls back to all items.

	``warehouse`` is the gudang picked on the *row*, read off the live form: the stock shown
	belongs to the warehouse the user is actually looking at, not the one last saved. Only
	when the row has none does the container's branch default stand in.
	"""
	pl = None
	warehouse = _clean(warehouse) or None
	if repair_order:
		ro = frappe.db.get_value("Repair Order", repair_order, ["principal", "container"], as_dict=True) or frappe._dict()
		principal = ro.principal or (frappe.db.get_value("Container", ro.container, "principal") if ro.container else None)
		pl = _owner_price_list(principal)
		warehouse = warehouse or _default_warehouse(_resolve_company(), frappe.db.get_value("Container", ro.container, "depot") if ro.container else None)

	priced = (
		frappe.get_all("Item Price", filters={"price_list": pl, "selling": 1}, pluck="item_code", distinct=True)
		if pl
		else None
	)
	filters = {"disabled": 0}
	# The row's Jenis narrows the catalogue before anything else: pick "Jasa" and no part can
	# turn up, pick "Part" and no service can. Blank keeps both (the PWA / API callers).
	#
	# The split is the Item master's own ``is_stock_item``, nothing else. There used to be a
	# third label, "Part (Beli Langsung)", for a physical part the depot buys per job and never
	# stocks; it was dropped because it is invisible to ERPNext (such an item is is_stock_item
	# = 0, exactly like a service) and the operator had to know which of two identical-looking
	# labels to pick. Anything not drawn from a gudang is now simply "Jasa".
	if line_type == "Jasa":
		filters["is_stock_item"] = 0
	elif line_type == "Part":
		filters["is_stock_item"] = 1
	# Scope to the Maintenance menu (group-derived) when it's configured, intersecting
	# with the owner-priced set; otherwise keep the owner-priced filter (or none).
	names = priced
	if is_real_menu(MR_MENU):
		base = priced if priced is not None else frappe.get_all("Item", filters={"disabled": 0}, pluck="name")
		names = filter_items_by_menu(base, MR_MENU)
	# A part that the source warehouse does not hold cannot be used, so it is dropped from
	# the picker; services are untouched. Filtered BEFORE the query so pagination stays
	# honest (a page of 20 never comes back short).
	empty = _out_of_stock_items(warehouse)
	if empty:
		if names is None:
			names = frappe.get_all("Item", filters={"disabled": 0}, pluck="name")
		names = [n for n in names if n not in empty]
	if names is not None:
		filters["name"] = ["in", names or [""]]
	or_filters = None
	search = (search or "").strip()
	if search and search.lower() != "undefined":
		or_filters = {"item_code": ["like", f"%{search}%"], "item_name": ["like", f"%{search}%"]}

	items = frappe.get_all(
		"Item", filters=filters, or_filters=or_filters,
		fields=["name as item_code", "item_name", "stock_uom", "is_stock_item"],
		order_by="item_name asc", limit_start=cint(start), limit_page_length=cint(page_length),
	)
	for it in items:
		it["rate"] = resolve_price(it["item_code"], pl)  # computed, hidden in the PWA
		# Only ever report stock for a known warehouse. Without one, _on_hand would total
		# every warehouse in the company — a number no single M&R can actually issue.
		it["on_hand"] = _on_hand(it["item_code"], warehouse) if (it.get("is_stock_item") and warehouse) else None
	return {"items": items, "price_list": pl, "warehouse": warehouse}


# --- worklist ----------------------------------------------------------------
def list_open_mr_orders(start=0, page_length=20, search=None) -> dict:
	"""Open M&R orders (Draft / Pending Approval / Approved / In Progress) — the PWA M&R
	worklist. Depot-scoped to the caller's branch."""
	filters = {"status": ["in", MR_OPEN_STATUSES]}
	depots = get_user_depots()
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]
	or_filters = None
	search = (search or "").strip()
	if search and search.lower() != "undefined":
		or_filters = {"container_no": ["like", f"%{search}%"], "repair_order_id": ["like", f"%{search}%"]}
	items = frappe.get_all(
		"Repair Order", filters=filters, or_filters=or_filters,
		# started_by: who pressed "Mulai" — what hides a job already in someone's hands from
		# everyone else's worklist (see work_claim).
		fields=["name", "repair_order_id", "container", "container_no", "status",
			"principal", "depot", "total_cost", "target_lift_on", "creation", "started_by"],
		order_by="creation asc", limit_page_length=0,
	)
	items = filter_claimed(items, "started_by")
	total = len(items)
	# Gate-out priority, then the job already in this operator's hands, then the rest —
	# see ``worklist.sort_by_priority`` for why that order.
	items = sort_by_priority(items, lambda r: r.get("status") == "In Progress", start, page_length)
	return {"items": items, "total": total}


# Execution phase — the PWA M&R menu is the field/cleaning division's console: it only shows
# work the owner (or an Admin-Ops bypass) has already approved. Estimate-building and the
# owner decision live in Desk (ERP).
# The PWA worklist. An Approved M&R is NOT here yet: Admin Ops still has to hand it over
# (``forward_to_team`` -> Pending), the same gate Cleaning Order puts in front of its team.
MR_EXECUTION_STATUSES = ["Pending", "In Progress"]


def item_pricing(repair_order, item) -> dict:
	"""Cost inputs (manhour / manhour_rate / item_rate / currency) for one item under the
	Repair Order's owner price list — the Desk grid uses it to default a newly-picked line."""
	from container_depot.pricing_model import item_rate_breakdown

	price_list = frappe.get_doc("Repair Order", repair_order).owner_price_list()
	breakdown = item_rate_breakdown(item, price_list)
	# An item with no Item Price still bills in the owner's currency (the contract currency,
	# e.g. USD) — not the site default — so the grid never falls back to IDR. Mirrors the
	# fallback in RepairOrder.calculate_totals.
	if not breakdown.get("currency") and price_list:
		breakdown["currency"] = frappe.db.get_value("Price List", price_list, "currency")
	return breakdown


def _attach_item_counts(items) -> None:
	"""Stamp ``item_count`` — how many lines the team actually has to work.

	Rejected lines are excluded because they are not work: an order the owner cut down to one
	item would otherwise advertise five on the worklist, and the operator would open it
	expecting a job four times the size. Mirrors the ``service_count`` on a Cleaning Order row.
	"""
	names = [i["name"] for i in items]
	if not names:
		return
	from collections import Counter

	counts = Counter(
		frappe.get_all(
			"Repair Used Item",
			filters={"parent": ["in", names], "decision": ["!=", "Rejected"]},
			pluck="parent",
		)
	)
	for i in items:
		i["item_count"] = counts.get(i["name"], 0)


def list_mr_execution(start=0, page_length=20, search=None) -> dict:
	"""Pending / In Progress M&R orders — the PWA execution worklist (start -> done).

	An Approved order is NOT here: Admin Ops still has to hand it over (``forward_to_team``),
	the same gate Cleaning Order puts in front of its team. Depot-scoped to the caller's
	branch."""
	filters = {"status": ["in", MR_EXECUTION_STATUSES]}
	depots = get_user_depots()
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]
	or_filters = None
	search = (search or "").strip()
	if search and search.lower() != "undefined":
		or_filters = {"container_no": ["like", f"%{search}%"], "repair_order_id": ["like", f"%{search}%"]}
	items = frappe.get_all(
		"Repair Order", filters=filters, or_filters=or_filters,
		# See list_open_mr_orders: started_by is the claim, not a displayed column.
		fields=["name", "repair_order_id", "container", "container_no", "status",
			"principal", "depot", "total_cost", "target_lift_on", "creation", "started_by"],
		order_by="creation asc", limit_page_length=0,
	)
	items = filter_claimed(items, "started_by")
	total = len(items)
	# Gate-out priority, then the job already in this operator's hands, then the rest —
	# see ``worklist.sort_by_priority`` for why that order.
	items = sort_by_priority(items, lambda r: r.get("status") == "In Progress", start, page_length)
	_attach_item_counts(items)
	return {"items": items, "total": total}


def list_review_mr_orders(start=0, page_length=20, search=None) -> dict:
	"""M&R orders awaiting Desk review — the PWA "Diajukan Review" list.

	These were finished in the field: the team pressed "Kirim untuk Review" and the order is
	sitting on Desk waiting for someone to check the work and close it. Depot-scoped exactly
	like the worklist (NOT owner-scoped: an M&R is auto-created from an EIR, so it is rarely
	owned by whoever did the repair). Newest first, searchable by container no / order id.

	It is a separate list rather than a status inside the worklist on purpose: work waiting on
	somebody ELSE must not sit among work waiting on YOU, or the operator re-opens it looking
	for something to do. Mirrors ``cleaning.list_review_cleaning_orders``.
	"""
	filters = {"status": "Pending Review"}
	depots = get_user_depots()
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]
	or_filters = None
	search = (search or "").strip()
	if search and search.lower() != "undefined":
		or_filters = {"container_no": ["like", f"%{search}%"], "repair_order_id": ["like", f"%{search}%"]}
	items = frappe.get_all(
		"Repair Order", filters=filters, or_filters=or_filters,
		fields=["name", "repair_order_id", "container", "container_no", "status",
			"principal", "depot", "total_cost", "target_lift_on", "creation"],
		order_by="modified desc, creation desc",
		limit_start=cint(start), limit_page_length=cint(page_length),
	)
	_attach_item_counts(items)
	return {"items": items, "total": frappe.db.count("Repair Order", filters)}


def list_mr_history(start=0, page_length=10, search=None) -> dict:
	"""Finished M&R orders (Completed / Rejected / Cancelled) — the PWA M&R "Riwayat" feed,
	newest first, paginated + searchable, depot-scoped. Detail reuses ``get_mr_order_detail``."""
	filters = {"status": ["in", ["Completed", "Rejected", "Cancelled"]]}
	depots = get_user_depots()
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]
	or_filters = None
	search = (search or "").strip()
	if search and search.lower() != "undefined":
		or_filters = {"container_no": ["like", f"%{search}%"], "repair_order_id": ["like", f"%{search}%"]}
	items = frappe.get_all(
		"Repair Order", filters=filters, or_filters=or_filters,
		fields=["name", "repair_order_id", "container", "container_no", "status",
			"principal", "depot", "total_cost", "completion_date", "creation"],
		order_by="creation desc", limit_start=cint(start), limit_page_length=cint(page_length),
	)
	return {"items": items, "total": frappe.db.count("Repair Order", filters)}


# --- detail ------------------------------------------------------------------
def get_mr_order_detail(repair_order) -> dict:
	"""Everything the PWA form needs: the copied EIR Damages (Section 1, read-only, with
	resolved code descriptions + photos), the Used Items (Section 2: item, qty, gudang,
	photos) and the tank spec."""
	ro = frappe.get_doc("Repair Order", repair_order)
	_guard_container_branch(ro.container)
	# Only while the job is actually running: a notification tap must not drop a second
	# operator into a form somebody else is filling in. Once it is sent for review or closed
	# the claim is over and the Riwayat detail stays readable to the whole branch.
	if ro.status == "In Progress":
		guard_claim(ro.started_by, _("M&R {0}").format(ro.repair_order_id or ro.name))
	c = frappe.db.get_value("Container", ro.container, _CONTAINER_FIELDS, as_dict=True) or frappe._dict()

	dmg_desc = {d.name: d.description for d in frappe.get_all("Inspection Damage Code", fields=["name", "description"])}
	rep_desc = {r.name: r.description for r in frappe.get_all("Inspection Repair Code", fields=["name", "description"])}
	damages = [{
		"area": d.area, "component": d.component,
		"damage_code": d.damage_code, "damage_desc": dmg_desc.get(d.damage_code),
		"repair_code": d.repair_code, "repair_desc": rep_desc.get(d.repair_code),
		"damage_description": d.damage_description,
		"photos": _photos_list(d.photos) or [p for p in (d.before_photo, d.after_photo) if p],
	} for d in ro.damages]

	used_items = [{
		# The child row id. The PWA stamps it onto every evidence photo it takes, so a photo
		# still points at the right line when one item appears on the order twice.
		"name": r.name,
		"item": r.item, "item_name": r.item_name, "is_stock_item": r.is_stock_item,
		"quantity": r.quantity, "remark": r.remark,
		# The gudang this line is issued from — chosen per row on the Desk form.
		"warehouse": r.warehouse,
		# Owner-approval: prices + per-line decision are exposed (the owner approves by cost).
		"decision": r.decision or "Pending",
		"owner_remark": r.owner_remark,
		# Labour + item breakdown; `amount` is the line's Total Cost. Labour never enters it:
		# `manhour_rate` is the tariff as it stands, `manhour` the hours the invoice bills.
		"manhour": r.manhour, "manhour_rate": r.manhour_rate,
		"item_rate": r.item_rate, "item_amount": r.item_amount,
		"amount": r.amount, "currency": r.currency,
		# Stock at THIS row's gudang. Never a company-wide total: that would promise stock the
		# line cannot actually issue.
		"on_hand": _on_hand(r.item, r.warehouse) if r.item and r.is_stock_item and r.warehouse else None,
	} for r in ro.used_items]

	return {
		"name": ro.name,
		"repair_order_id": ro.repair_order_id,
		"status": ro.status,
		"actions": MR_TRANSITIONS.get(ro.status, []),
		"container": ro.container,
		"container_no": ro.container_no or c.container_no,
		"inspection": ro.inspection,
		"technician": ro.technician,
		"reff_doc": ro.reff_doc,
		"remarks": ro.remarks,
		"stock_entry": ro.stock_entry,
		# Owner-approval surface.
		"total_cost": ro.total_cost,
		"owner_note": ro.owner_note,
		"requested_on": str(ro.requested_on) if ro.requested_on else None,
		"decided_on": str(ro.decided_on) if ro.decided_on else None,
		"revision_no": ro.revision_no,
		# When the work itself happened. The Riwayat entry has to stand on its own as the
		# record of the job, and a repair with no dates reads as one that never happened.
		"start_date": str(ro.start_date) if ro.start_date else None,
		"completion_date": str(ro.completion_date) if ro.completion_date else None,
		# A standing "buka lagi" request, so the PWA shows the reason instead of offering the
		# button a second time.
		"reopen_requested": cint(ro.reopen_requested),
		"reopen_note": ro.reopen_note,
		# Whether reopening is still free. Once billed it is an accounting decision, and a
		# button that always throws is worse than no button.
		"billing_status": ro.billing_status,
		# Tank spec (read-only).
		"tank_type": c.container_type,
		"client": c.principal,
		"capacity": c.capacity,
		"tare": c.tare_weight,
		"mgw": c.max_gross_weight,
		"previous_cargo": c.last_cargo,
		"date_of_manufacture": c.manufacture_date,
		"last_test_date": c.last_test_date,
		"damages": damages,
		"used_items": used_items,
		# Evidence photos, in their own table — keyed to the line they prove.
		"work_photos": [{
			"name": p.name, "photo": p.photo, "item": p.item, "item_name": p.item_name,
			"caption": p.caption, "used_item": p.used_item,
		} for p in (ro.work_photos or [])],
	}


# --- owner approval ----------------------------------------------------------
def publish_to_owner(repair_order):
	"""Admin Ops sends the estimate to the customer web: Draft / Revision Requested ->
	Pending Approval.

	There used to be a "Service Setup" staging step in front of this, on the idea that the
	workshop drafted an estimate and handed it to Admin Ops to arrange. In practice Admin Ops
	is the first pair of eyes on every M&R, so the hand-off was to themselves — Draft IS
	their desk, and this is the first thing that leaves it.

	This is the moment the owner can first see (and decide on) the estimate, so
	``requested_on`` is stamped here — it measures how long the OWNER has had it. Per-line
	decisions are reset so a re-sent revision starts a fresh round, and re-publishing after a
	withdraw restarts the clock, which is what "ajukan ulang" means.
	"""
	ro = frappe.get_doc("Repair Order", repair_order)
	_guard_container_branch(ro.container)
	if ro.status not in MR_EDITABLE_STATUSES:
		frappe.throw(
			_("M&R hanya bisa dikirim ke owner dari Draft / Revision Requested (status: {0}).").format(ro.status)
		)
	if not (ro.used_items and len(ro.used_items) > 0):
		frappe.throw(_("Tambahkan minimal satu item sebelum mengirim ke owner."))
	for r in ro.used_items:
		r.decision = "Pending"
		r.owner_remark = None
	ro.status = "Pending Approval"
	ro.requested_on = now_datetime()
	ro.save()
	from container_depot.container_depot.notify import notify_repair_order_pending_approval
	notify_repair_order_pending_approval(ro.name)
	return {"success": True, "name": ro.name, "status": ro.status}


def withdraw_from_owner(repair_order, note=None):
	"""Admin Ops pulls a published estimate back off the customer web ("tarik ulang"):
	Pending Approval -> Draft.

	Only while the owner has not decided — once they have (Approved / Rejected / Revision
	Requested) the decision stands and this refuses, so a withdrawal can never erase an
	answer the customer already gave. Per-line decisions are reset to Pending because the
	re-published estimate is a fresh round; ``requested_on`` is cleared for the same reason
	(``publish_to_owner`` re-stamps it).
	"""
	ro = frappe.get_doc("Repair Order", repair_order)
	_guard_container_branch(ro.container)
	if ro.status != "Pending Approval":
		frappe.throw(
			_("Hanya M&R yang sedang menunggu keputusan owner yang bisa ditarik (status: {0}).").format(ro.status)
		)
	for r in ro.used_items or []:
		r.decision = "Pending"
		r.owner_remark = None
	ro.status = "Draft"
	ro.requested_on = None
	if note:
		ro.owner_note = _clean(note)
	ro.save()
	return {"success": True, "name": ro.name, "status": ro.status}


def reopen_to_draft(repair_order, note=None):
	"""Rewind an in-flight M&R back to an editable **Draft** so a human can fix a wrong /
	missing input, then run it through approval again.

	Allowed from Pending Approval, Approved, Pending, In Progress, Pending Review and
	Rejected — every stage before the parts are actually issued. NOT from Completed (the stock issue already
	happened; use Cancel + a fresh order) nor Cancelled. Wipes the approval round entirely
	(per-line decisions, requested_on / decided_on / decided_by) so the re-quote starts clean;
	the used items are kept — editing them is the whole point. Adm Ops action (role gate in the
	ESS wrapper); branch-guarded here."""
	ro = frappe.get_doc("Repair Order", repair_order)
	_guard_container_branch(ro.container)
	REOPENABLE = (
		"Pending Approval", "Approved", "Pending", "In Progress", "Pending Review",
		"Rejected", "Revision Requested",
	)
	if ro.status not in REOPENABLE:
		frappe.throw(
			_("M&R {0} tidak bisa dikembalikan ke Draft (part sudah dikeluarkan / order sudah ditutup).").format(ro.status)
		)
	for r in ro.used_items or []:
		r.decision = "Pending"
		r.owner_remark = None
	prev = ro.status
	ro.status = "Draft"
	ro.requested_on = None
	ro.decided_on = None
	ro.decided_by = None
	if note:
		ro.owner_note = _clean(note)
	ro.save()
	# Audit trail on the timeline — best-effort, must not block the reopen.
	msg = _("M&R dikembalikan ke Draft dari {0} oleh {1}").format(prev, frappe.session.user)
	if note:
		msg += ": " + _clean(note)
	log_doc_note("Repair Order", ro.name, msg)
	return {"success": True, "name": ro.name, "status": ro.status}


def bypass_approval(repair_order, note=None):
	"""Admin-Ops BYPASS: approve the estimate directly (Draft / Revision Requested ->
	Approved) without sending it to the owner. Same preconditions as ``publish_to_owner``
	(≥1 used item); every still-Pending line is auto-approved so the total + stock issue are
	consistent with a normal Approved.

	The Admin-Ops role gate lives in the ESS wrapper (``mr_bypass_approval``); this function
	enforces the branch + status preconditions only, mirroring ``record_decision``'s Approved
	branch."""
	ro = frappe.get_doc("Repair Order", repair_order)
	_guard_container_branch(ro.container)
	if ro.status not in MR_EDITABLE_STATUSES:
		frappe.throw(
			_("Bypass hanya dari Draft / Revision Requested (status: {0}).").format(ro.status)
		)
	if not (ro.used_items and len(ro.used_items) > 0):
		frappe.throw(_("Tambahkan minimal satu item sebelum menyetujui."))
	for r in ro.used_items:
		if r.decision not in ("Approved", "Rejected"):
			r.decision = "Approved"
	if not any(r.decision == "Approved" for r in ro.used_items):
		frappe.throw(_("Minimal satu item harus disetujui."))
	ro.status = "Approved"
	ro.owner_note = _clean(note) or _("Disetujui langsung oleh Admin Ops (bypass owner).")
	ro.requested_on = ro.requested_on or now_datetime()
	ro.decided_on = now_datetime()
	ro.decided_by = frappe.session.user
	issue_parts_on_approval(ro)
	ro.save()
	from container_depot.container_depot.notify import notify_repair_order_decided
	notify_repair_order_decided(ro.name)
	return {"success": True, "name": ro.name, "status": ro.status, "total_cost": ro.total_cost}


def _apply_line_decisions(ro, line_decisions) -> None:
	"""Write per-line owner decisions onto the used-item rows. Accepts a JSON string or:
	- a list aligned to ``used_items`` order — each item a decision string or
	  ``{"decision": ..., "owner_remark": ...}``;
	- a dict keyed by item code — value a decision string or ``{decision, owner_remark}``."""
	if line_decisions is None:
		return
	data = json.loads(line_decisions) if isinstance(line_decisions, str) else line_decisions
	if not data:
		return

	def _set(row, value):
		if isinstance(value, dict):
			d = value.get("decision")
			if "owner_remark" in value:
				row.owner_remark = _clean(value.get("owner_remark"))
		else:
			d = value
		if d in ("Approved", "Rejected", "Pending"):
			row.decision = d

	if isinstance(data, dict):
		for r in ro.used_items:
			if r.item in data:
				_set(r, data[r.item])
	elif isinstance(data, list):
		for r, value in zip(ro.used_items, data):
			_set(r, value)


def record_decision(repair_order, decision, line_decisions=None, note=None):
	"""Record the owner's decision on a Pending-Approval M&R (Fase B: depot records it).

	``decision`` ∈ {Approved, Rejected, Revision Requested}. ``line_decisions`` optionally
	sets each line's Approved/Rejected before an Approved is validated (partial approval).
	On Approved, any still-Pending line defaults to Approved; ≥1 Approved line is required.
	Only Approved lines drive the total and the stock issue on completion."""
	ro = frappe.get_doc("Repair Order", repair_order)
	_guard_container_branch(ro.container)
	if ro.status != "Pending Approval":
		frappe.throw(_("Keputusan hanya bisa direkam saat Pending Approval (status: {0}).").format(ro.status))
	if decision not in ("Approved", "Rejected", "Revision Requested"):
		frappe.throw(_("Keputusan tidak valid: {0}.").format(decision))

	_apply_line_decisions(ro, line_decisions)
	note = _clean(note)

	if decision == "Revision Requested":
		ro.status = "Revision Requested"
		ro.owner_note = note
		ro.revision_no = cint(ro.revision_no) + 1
	elif decision == "Rejected":
		for r in ro.used_items:
			r.decision = "Rejected"
		ro.status = "Rejected"
		ro.owner_note = note
		ro.decided_on = now_datetime()
		ro.decided_by = frappe.session.user
	else:  # Approved (possibly partial)
		approved = 0
		for r in ro.used_items:
			if r.decision not in ("Approved", "Rejected"):
				r.decision = "Approved"
			if r.decision == "Approved":
				approved += 1
		if approved == 0:
			frappe.throw(_("Minimal satu item harus disetujui untuk meng-approve M&R."))
		ro.status = "Approved"
		ro.owner_note = note
		ro.decided_on = now_datetime()
		ro.decided_by = frappe.session.user
		issue_parts_on_approval(ro)

	ro.save()
	from container_depot.container_depot.notify import notify_repair_order_decided
	notify_repair_order_decided(ro.name)
	return {"success": True, "name": ro.name, "status": ro.status, "total_cost": ro.total_cost}


def issue_parts_on_approval(ro) -> None:
	"""Take the approved parts out of the warehouse the moment the estimate is agreed.

	The workshop cannot repair anything with parts that are still on a shelf, so the stock
	moves when the money is agreed, not when the work is reported done. Both roads to
	"Approved" come through here — the owner's own yes (``record_decision``) and the Admin-Ops
	bypass (``bypass_approval``) — because from the warehouse's point of view they are the
	same event: someone with authority said these parts are being used.

	Only Approved lines are issued; a line the owner struck out is never repaired, so it never
	leaves stock. Nothing is issued twice: an order that already carries a Stock Entry is
	skipped, and rewinding one (``RepairOrder._return_parts_if_rewound``) cancels that entry
	and puts the parts back before it can be issued again.

	Mutates ``ro`` in place; the caller saves. ``stock_entry`` is set BEFORE that save on
	purpose — ``_validate_stock_available`` reads it to know the on-hand figure has already
	moved and must not be re-checked against the estimate.
	"""
	if ro.get("stock_entry"):
		return
	assert_stock_available(ro)
	stock_entry = _issue_parts_stock(ro)
	if stock_entry:
		ro.stock_entry = stock_entry


def return_parts_stock(ro) -> None:
	"""Put the issued parts back: cancel the Material Issue this M&R raised.

	Called when an order that has already taken its parts is rewound to Draft or cancelled.
	Cancelling the Stock Entry (rather than raising a Material Receipt) is what keeps the
	ledger honest — the issue and its reversal stay one linked pair instead of two unrelated
	movements that happen to net to zero.

	Mutates ``ro`` in place; the caller saves.
	"""
	name = ro.get("stock_entry")
	if not name or not frappe.db.exists("Stock Entry", name):
		ro.stock_entry = None
		return
	se = frappe.get_doc("Stock Entry", name)
	if se.docstatus == 1:
		se.flags.ignore_permissions = True
		se.cancel()
	ro.stock_entry = None


def _assert_not_billed(ro) -> None:
	"""Refuse to reopen an M&R that has already reached an invoice.

	Un-finishing a closed order changes what the owner is charged for. While it is still
	``Unbilled`` that costs nothing; once it has been swept onto a Sales Invoice, undoing it
	is an accounting decision (credit note, amend) and not something a PWA button may take.
	"""
	if (ro.get("billing_status") or "Unbilled") != "Unbilled" or ro.get("sales_invoice"):
		frappe.throw(
			_("M&R ini sudah masuk invoice — pembukaan kembali harus lewat proses billing.")
		)


def request_revision(repair_order, reason=None) -> dict:
	"""The team asks Admin Ops to open a CLOSED M&R again ("Ajukan Revisi" in the PWA).

	Mirrors ``cleaning.request_revision``: a closed order cannot be edited from the PWA, so
	this raises a REQUEST rather than touching the work — an audit note on the timeline, a
	flag the Desk shows with its reason, and a notification to Admin Ops. Reopening stays a
	human decision on the Desk side (:func:`reopen_completed`).

	Only from Completed. A job still in flight does not need asking: the team can pull it back
	themselves (``withdraw_review``), and offering both would make the cheap, permissionless
	route look like the expensive one.
	"""
	from container_depot.container_depot import notify as _notify
	from container_depot.container_depot.container_activity import log_doc_note

	if not repair_order:
		frappe.throw(_("repair_order is required."))
	ro = frappe.get_doc("Repair Order", repair_order)
	_guard_container_branch(ro.container)
	if ro.status != "Completed":
		frappe.throw(
			_("Hanya M&R yang sudah selesai yang bisa diajukan revisi (status: {0}).").format(ro.status)
		)
	_assert_not_billed(ro)

	reason = _clean(reason)
	user = frappe.session.user
	note = _("Permintaan buka kembali M&R oleh {0}").format(user)
	if reason:
		note += ": " + reason
	# Best-effort audit trail — the notification is what carries the request, so a
	# comment-permission hiccup must not fail it.
	log_doc_note("Repair Order", ro.name, note)
	frappe.db.set_value(
		"Repair Order", ro.name,
		{"reopen_requested": 1, "reopen_note": note},
		update_modified=False,
	)
	from container_depot.container_depot.notify import notify_repair_revision_requested

	sent = notify_repair_revision_requested(ro.name, reason=reason)
	return {"success": True, "notified": sent, "repair_order": ro.name, "status": ro.status}


def reopen_completed(repair_order, note=None) -> dict:
	"""Admin Ops opens a closed M&R again: Completed -> In Progress.

	The other half of :func:`request_revision`, and offered without one too — Admin Ops may
	spot the mistake themselves. **In Progress**, not Draft: what was wrong is the repair, not
	the estimate. The owner's approval, the prices and the parts already issued all stand, so
	rewinding past them would make the team re-quote work that was correctly quoted.

	``flags.oak_reopen`` is what the controller checks: the Completed -> In Progress edge is
	legal in the state machine (validate has to allow this save) but refused on every other
	path, so a generic status endpoint cannot un-finish a closed order.
	"""
	ro = frappe.get_doc("Repair Order", repair_order)
	_guard_container_branch(ro.container)
	if ro.status != "Completed":
		frappe.throw(_("Hanya M&R yang sudah selesai yang bisa dibuka kembali (status: {0}).").format(ro.status))
	_assert_not_billed(ro)

	from container_depot.container_depot.container_activity import log_doc_note

	msg = _("M&R dibuka kembali ke In Progress oleh {0}").format(frappe.session.user)
	note = _clean(note)
	if note:
		msg += ": " + note
	ro.status = "In Progress"
	# The order is open again, so the completion never happened. Left standing it would print
	# on the record as a job that finished before it was worked.
	ro.completion_date = None
	ro.reopen_requested = 0
	ro.reopen_note = None
	ro.flags.oak_reopen = True
	ro.save()
	log_doc_note("Repair Order", ro.name, msg)
	return {"success": True, "name": ro.name, "status": ro.status}


# --- lifecycle ---------------------------------------------------------------
def forward_to_team(repair_order):
	"""Admin Ops hands an approved M&R to the workshop: Approved -> Pending.

	The gate exists so approval and dispatch stay separate decisions. An owner's yes says the
	money is agreed; it does not say the depot is ready to start — the tank may still be
	waiting on cleaning, on a part, or on a slot. Until this is pressed the order is invisible
	to the PWA worklist (``MR_EXECUTION_STATUSES``), exactly the way Cleaning Order holds a
	job in Service Setup until "Teruskan ke Team".
	"""
	ro = frappe.get_doc("Repair Order", repair_order)
	_guard_container_branch(ro.container)
	if ro.status != "Approved":
		frappe.throw(
			_("Hanya M&R yang sudah disetujui owner yang bisa diteruskan ke team (status: {0}).").format(ro.status)
		)
	ro.status = "Pending"
	ro.save()
	from container_depot.container_depot.notify import notify_repair_forwarded_to_team
	notify_repair_forwarded_to_team(ro.name)
	return {"success": True, "name": ro.name, "status": ro.status}


def start_repair(repair_order):
	"""The team picks the job up off its worklist: Pending -> In Progress. The controller
	mirrors this onto the container (-> Repair_In_Progress).

	Only a job Admin Ops has actually handed over may start — approval alone is not the
	starting gun (see :func:`forward_to_team`)."""
	ro = frappe.get_doc("Repair Order", repair_order)
	_guard_container_branch(ro.container)
	# First press wins — see work_claim. Checked BEFORE the status gate: a job a colleague
	# already started is "In Progress", and "teruskan ke team dulu" would be a confusing way
	# to say "Budi is holding it".
	guard_claim(ro.started_by, _("M&R {0}").format(ro.repair_order_id or ro.name))
	if ro.status != "Pending":
		frappe.throw(
			_("M&R harus diteruskan ke team dulu sebelum dikerjakan (status: {0}).").format(ro.status)
		)
	ro.status = "In Progress"
	if not ro.start_date:
		ro.start_date = now_datetime()
	# Who is doing the work is whoever pressed "Mulai" here — not whoever built the estimate
	# in Desk. Same rule as Cleaning Order.assigned_to and Inspection.work_started_by, and it
	# is what keeps the job in this operator's hands until it leaves for review.
	if not ro.started_by:
		ro.started_by = frappe.session.user
	ro.save()
	return {"success": True, "name": ro.name, "status": ro.status}


def withdraw_review(repair_order):
	"""The team pulls a finished job back to fix something: Pending Review -> In Progress.

	Their own correction, before Desk finalises it — no Admin Ops needed, and nothing has
	left the warehouse yet. Mirrors ``cleaning.withdraw_review``."""
	ro = frappe.get_doc("Repair Order", repair_order)
	_guard_container_branch(ro.container)
	if ro.status != "Pending Review":
		frappe.throw(
			_("Hanya M&R yang menunggu review yang bisa ditarik kembali (status: {0}).").format(ro.status)
		)
	ro.status = "In Progress"
	ro.save()
	return {"success": True, "name": ro.name, "status": ro.status}


MR_FINALIZABLE_STATUSES = ("Pending Review", "Approved")


def finalize_repair(repair_order):
	"""Desk closes the job: Pending Review -> Completed, or Approved -> Completed.

	Nothing moves in the warehouse here — the parts left it back at approval
	(:func:`issue_parts_on_approval`), which is when the workshop actually needed them in
	hand. This is the sign-off on the WORK: a human agreed the repair is right, so the order
	closes and becomes billable.

	Two ways in, one meaning. From **Pending Review** it closes a job the team reported done
	in the PWA — the ordinary path. From **Approved** it closes a job that never needed
	dispatching: the repair is already over (a five-minute fix, or a subcontractor's work),
	and sending it round the PWA would only make the operator press Mulai and Selesai on
	something finished. Nothing is skipped by taking the short road; the money was agreed and
	the parts were issued at approval either way.

	``start_date`` is stamped when it is missing so a directly-closed order still says when
	the work happened, rather than showing a completion with no beginning.
	"""
	ro = frappe.get_doc("Repair Order", repair_order)
	_guard_container_branch(ro.container)
	if ro.status not in MR_FINALIZABLE_STATUSES:
		frappe.throw(
			_("M&R hanya bisa diselesaikan dari Disetujui atau Menunggu Review (status: {0}).").format(ro.status)
		)
	direct = ro.status == "Approved"
	ro.status = "Completed"
	# A standing request asked for exactly this round of work; it has been actioned and the
	# order is closed again, so the badge comes off rather than following it into history.
	ro.reopen_requested = 0
	ro.reopen_note = None
	if not ro.completion_date:
		ro.completion_date = now_datetime()
	if not ro.start_date:
		ro.start_date = ro.completion_date
	ro.save()
	if direct:
		# Worth a timeline note: an order that reaches Completed without ever appearing on
		# the team's worklist looks, in the history, like a step went missing.
		log_doc_note(
			"Repair Order", ro.name,
			_("M&R diselesaikan langsung dari Disetujui (tanpa diteruskan ke team) oleh {0}").format(
				frappe.session.user
			),
		)
	return {
		"success": True,
		"name": ro.name,
		"status": ro.status,
		"total_cost": ro.total_cost,
		"stock_entry": ro.get("stock_entry"),
	}


# The team's half of the flow, in the order it is walked. ``submit_direct`` steps along it
# one status at a time because ``_validate_status_transition`` checks every save against the
# STORED status — a single jump from Pending to Completed would be refused.
MR_TEAM_TAIL = ("Pending", "In Progress", "Pending Review")


def submit_direct(repair_order, note=None):
	"""Desk "Submit": close an M&R in one press, from wherever it currently stands.

	This is the convenience a submittable Cleaning Order gets for free — whoever is looking at
	the order signs it off there and then, instead of walking work that is already over
	through the owner, the dispatch and the review. Repair Order carries no docstatus, so
	"Submit" is this function.

	Nothing is skipped, only pressed for you: every stage it passes through is that stage's own
	function, so the still-Pending lines are approved, the parts leave the warehouse exactly
	once (:func:`issue_parts_on_approval`), the notifications fire and the timeline records both
	the bypass and the completion.

	Guarded to the bypass roles in the ESS wrapper (``mr_submit_direct``): it approves on the
	owner's behalf, which is the one thing an ordinary M&R press may not do."""
	ro = frappe.get_doc("Repair Order", repair_order)
	_guard_container_branch(ro.container)
	if ro.status == "Completed":
		frappe.throw(_("M&R ini sudah selesai."), exc=AlreadySettled)
	if ro.status in ("Cancelled", "Rejected"):
		frappe.throw(_("M&R sudah {0} — tidak bisa di-submit.").format(ro.status), exc=AlreadySettled)

	note = _clean(note) or _("Diselesaikan langsung dari Desk (submit).")

	if ro.status in MR_EDITABLE_STATUSES and ro.used_items:
		bypass_approval(repair_order, note=note)
	elif ro.status in MR_EDITABLE_STATUSES:
		# An order with no estimate at all is CLOSED as it stands, not refused — the same
		# answer a Cleaning Order with no service line gives its Submit. There is nothing to
		# charge and no part to take out of the warehouse, so the approval is stamped here
		# rather than through ``bypass_approval`` (which insists on ≥1 item, because an
		# estimate sent for approval with nothing on it is a different mistake).
		ro.status = "Approved"
		ro.owner_note = note
		ro.requested_on = ro.requested_on or now_datetime()
		ro.decided_on = now_datetime()
		ro.decided_by = frappe.session.user
		ro.save()
	elif ro.status == "Pending Approval":
		record_decision(repair_order, "Approved", note=note)
	elif ro.status in MR_TEAM_TAIL:
		# Already handed to the team: walk forward to Pending Review, one legal edge per save.
		for nxt in MR_TEAM_TAIL[MR_TEAM_TAIL.index(ro.status) + 1 :]:
			step = frappe.get_doc("Repair Order", repair_order)
			step.status = nxt
			if nxt == "In Progress" and not step.start_date:
				step.start_date = now_datetime()
			step.save()

	log_doc_note(
		"Repair Order", repair_order,
		_("Submit langsung dari Desk oleh {0}: {1}").format(frappe.session.user, note),
	)
	return finalize_repair(repair_order)


def _coerce_list(value) -> list:
	if isinstance(value, str):
		value = json.loads(value) if value.strip() else []
	return value or []


def _as_bool(value) -> bool:
	if isinstance(value, str):
		return value.strip().lower() in ("1", "true", "yes")
	return bool(value)


def _clean(value):
	return ((value or "").strip() or None) if isinstance(value, str) else (value or None)


def _apply_used_items(ro, used_items) -> None:
	rows = []
	for u in _coerce_list(used_items):
		item = _clean(u.get("item"))
		if not item:
			continue  # a used-item line is meaningless without an Item
		rows.append({
			"item": item,
			"quantity": flt(u.get("quantity")) or 1,
			# The gudang this line issues from; blank falls back to the container's branch
			# default in ``row_warehouse``, and the controller stamps it back onto the row.
			"warehouse": _clean(u.get("warehouse")),
			"remark": _clean(u.get("remark")),
		})
	ro.set("used_items", rows)


def _apply_work_photos(ro, work_photos) -> None:
	"""Replace the evidence album with what the caller sent.

	Whole-table replace, not a merge: the PWA holds the full list on screen and a removal is
	as meaningful an edit as an addition — merging would make deleting a wrong photo
	impossible from the one screen it is visible on. Rows without a ``photo`` are dropped
	rather than refused, so an upload that never landed cannot block the save that carries the
	rest.

	The item/line pairing is NOT resolved here — ``RepairOrder._bind_work_photos`` does it on
	validate, so a photo attached from the Desk grid gets the same treatment as one shot in
	the PWA.
	"""
	ro.set("work_photos", [])
	for row in _coerce_list(work_photos):
		if not isinstance(row, dict):
			continue
		photo = _clean(row.get("photo"))
		if not photo:
			continue
		ro.append("work_photos", {
			"photo": photo,
			"item": row.get("item"),
			"caption": _clean(row.get("caption")),
			"used_item": _clean(row.get("used_item")),
		})


def _assert_warehouses_in_user_branch(ro) -> None:
	"""No row may issue from a gudang outside the caller's branch.

	The branch check used to sit on the order's single Source Warehouse; now that every row
	picks its own, it has to be made per row or the scoping is simply gone.
	"""
	for wh in {r.warehouse for r in ro.used_items or [] if r.get("warehouse")}:
		assert_in_user_branch(branch=frappe.db.get_value("Warehouse", wh, "branch"))


def row_warehouse(ro, row) -> str | None:
	"""The warehouse one Used-Items row issues from: its own, else the branch default.

	Each row names its own gudang, so a single M&R can pull the gasket from Stores and the
	rail from the workshop. The fallback matters only inside ``validate`` — it runs before
	``before_save`` stamps the resolved gudang onto the row, and without it the stock guard
	would skip a row that is about to get a warehouse anyway.
	"""
	return row.get("warehouse") or default_warehouse(ro)


def _requested_stock_qty(ro) -> dict:
	"""Stockable quantity this M&R will issue, summed **per (item, warehouse)**.

	Mirrors :func:`_issue_parts_stock` line for line — an owner-rejected line is never
	issued, so it is never counted against stock either. Summing per pair (not per row) is
	the point: two rows of one seal kit from the same gudang are a single demand of two,
	while the same part taken from two gudang are two independent demands.
	"""
	want = {}
	for r in ro.used_items or []:
		if (r.get("decision") or "Pending") == "Rejected":
			continue
		if not r.item or flt(r.quantity) <= 0:
			continue
		if not frappe.db.get_value("Item", r.item, "is_stock_item"):
			continue
		key = (r.item, row_warehouse(ro, r))
		want[key] = want.get(key, 0.0) + flt(r.quantity)
	return want


def default_warehouse(ro) -> str | None:
	"""The gudang a Part row starts from when the user has not picked one: the branch default
	for the container's depot.

	Only a seed and a fallback — the row owns the choice, and the controller stamps whatever
	this resolves to back onto the row, so the grid always shows the gudang actually used.
	Shared by the item picker, the stock guard and the Stok column so all three agree."""
	return _default_warehouse(
		_resolve_company(),
		frappe.db.get_value("Container", ro.container, "depot") if ro.get("container") else None,
	)


def on_hand_map(items, warehouse) -> dict:
	"""``{item_code: qty}`` at ``warehouse`` for the stockable members of ``items``.

	Services are simply absent from the result — they have no stock to report, and an
	explicit 0 would read as "habis" in the grid.
	"""
	items = [i for i in (items or []) if i]
	if not (items and warehouse):
		return {}
	stockable = frappe.get_all(
		"Item", filters={"name": ["in", items], "is_stock_item": 1}, pluck="name"
	)
	return {code: _on_hand(code, warehouse) for code in stockable}


def assert_stock_available(ro):
	"""Refuse an M&R whose gudang cannot cover its parts — stock must exist before the part
	can be put on the order.

	Checked per (item, gudang), because each row names its own warehouse. Every shortfall
	goes into ONE message, naming the gudang, so a mis-entered estimate is fixed in a single
	pass instead of one error per save. Rows with no gudang resolved yet are skipped: the
	stock is unknowable then, and ``_issue_parts_stock`` refuses to run without one anyway.

	Note this is about the message, not about data safety — ``allow_negative_stock`` is off
	and a failed Material Issue already rolls the whole completion back. What it buys is
	catching the shortfall while the estimate is being typed, naming the part and the
	numbers, instead of a raw Stock Entry error after the user presses Selesai.
	"""
	short = []
	for (item_code, warehouse), qty in _requested_stock_qty(ro).items():
		if not warehouse:
			continue  # no gudang resolved yet — stock is unknowable, see the docstring
		have = _on_hand(item_code, warehouse)
		if flt(qty) > flt(have):
			label = frappe.db.get_value("Item", item_code, "item_name") or item_code
			short.append(
				_("{0} di {1} — diminta {2}, tersedia {3}").format(label, warehouse, flt(qty), flt(have))
			)
	if short:
		frappe.throw(
			_("Stok tidak cukup:<br>{0}").format("<br>".join(short)), title=_("Stok Tidak Cukup")
		)


def _issue_parts_stock(ro) -> str | None:
	"""Issue the M&R's stockable Used Items as a Material Issue — **each line out of its own
	gudang**. Returns the Stock Entry name, or ``None`` when nothing is stockable. Raises
	(rolling back the request) if stock is insufficient."""
	lines = []
	for r in ro.used_items:
		if (r.get("decision") or "Pending") == "Rejected":
			continue  # owner rejected this line — not repaired, not issued
		if not r.item or flt(r.quantity) <= 0:
			continue
		item = frappe.db.get_value("Item", r.item, ["is_stock_item", "stock_uom"], as_dict=True)
		if not item or not item.is_stock_item:
			continue
		wh = row_warehouse(ro, r)
		if not wh:
			frappe.throw(
				_("Baris {0} ({1}) belum punya Gudang. Pilih gudangnya dulu.").format(r.idx, r.item)
			)
		lines.append((r.item, flt(r.quantity), item.stock_uom, wh))
	if not lines:
		return None

	company = _resolve_company()
	if not company:
		frappe.throw(_("Tidak ada Company default untuk mengeluarkan part dari stok."))

	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Material Issue"
	se.company = company
	# Header from_warehouse only when every line agrees; otherwise the per-row s_warehouse
	# below carries it, which is what lets one M&R draw from several gudang.
	warehouses = {wh for *_, wh in lines}
	if len(warehouses) == 1:
		se.from_warehouse = next(iter(warehouses))
	se.remarks = f"M&R {ro.repair_order_id or ro.name} • {ro.container_no or ro.container}"
	for item_code, qty, uom, wh in lines:
		se.append("items", {
			"item_code": item_code, "qty": qty, "s_warehouse": wh,
			"uom": uom, "stock_uom": uom, "conversion_factor": 1,
		})
	se.insert(ignore_permissions=True)
	se.submit()
	return se.name


# Where evidence photos may be added or dropped. Wider than MR_EDITABLE_STATUSES on purpose:
# the photos are proof of WORK, and the work happens long after the estimate is frozen — the
# team shoots them mid-repair, which is In Progress. Narrower than "always": once the order is
# closed the album is part of what the owner was shown, and Pending Review is somebody else's
# turn (withdraw first, which is one press).
MR_PHOTO_STATUSES = MR_EDITABLE_STATUSES + ("Approved", "Pending", "In Progress")


def save_mr_order(
	repair_order=None,
	used_items=None,
	work_photos=None,
	technician=None,
	reff_doc=None,
	remarks=None,
	submit=False,
) -> dict:
	"""Save the M&R's Used Items (each with its own gudang) and its evidence photos and, when
	``submit`` is true, hand the finished job to Desk for review (In Progress -> **Pending
	Review**).

	The two tables answer to different rules and that is the point of them being two tables:
	``used_items`` is the estimate the owner agreed to and freezes when it leaves Draft, while
	``work_photos`` is proof of the work and is gathered while the repair is happening.

	``submit`` does NOT complete the order — that is :func:`finalize_repair`, run by Desk once
	a human has checked the work. No stock moves here either: the parts were taken out at
	approval (:func:`issue_parts_on_approval`), because the workshop needed them in hand to do
	the job at all. Mirrors ``cleaning.save_cleaning_order``.

	Used items may only be edited while Draft / Revision Requested; the copied ``damages`` are
	read-only. Rates follow the owner's Item Price (controller-computed)."""
	if not repair_order:
		frappe.throw(_("repair_order is required."))
	ro = frappe.get_doc("Repair Order", repair_order)
	if ro.status in ("Completed", "Cancelled", "Rejected"):
		frappe.throw(_("M&R sudah {0}.").format(ro.status), exc=AlreadySettled)
	_guard_container_branch(ro.container)
	# The operator who started it owns the form until it leaves for review — an autosave that
	# only reaches the server later (offline queue) is checked here too.
	if ro.status == "In Progress":
		guard_claim(ro.started_by, _("M&R {0}").format(ro.repair_order_id or ro.name))

	submitting = _as_bool(submit)
	if submitting and ro.status != "In Progress":
		frappe.throw(_("M&R harus In Progress untuk diselesaikan (status: {0}).").format(ro.status))
	if ro.status == "Pending Review" and not submitting:
		frappe.throw(
			_("M&R sedang menunggu review Desk — tarik kembali dulu kalau mau diubah."), exc=AlreadySettled
		)
	if used_items is not None and ro.status not in MR_EDITABLE_STATUSES:
		frappe.throw(_("Item hanya bisa diubah saat Draft / Revision Requested."))
	if work_photos is not None and ro.status not in MR_PHOTO_STATUSES:
		frappe.throw(
			_("Foto bukti tidak bisa diubah saat status {0}.").format(ro.status)
		)

	if used_items is not None:
		_apply_used_items(ro, used_items)
		_assert_warehouses_in_user_branch(ro)
	if work_photos is not None:
		_apply_work_photos(ro, work_photos)
	if technician is not None:
		ro.technician = _clean(technician)
	# Optional reference doc (usually pre-filled from the EIR; editable here).
	if reff_doc is not None:
		ro.reff_doc = reff_doc
	if remarks is not None:
		ro.remarks = remarks

	if submitting:
		# No stock check and no stock movement: the parts were issued at approval, so on-hand
		# is ALREADY lower by exactly this order's amount and re-checking it against the
		# estimate would fail on every order that ever took a part.
		ro.status = "Pending Review"

	ro.save()  # before_save -> calculate_totals() (prices from Item Price) + container sync
	if submitting:
		from container_depot.container_depot.notify import notify_repair_pending_review

		notify_repair_pending_review(ro.name)
	return {
		"success": True,
		"name": ro.name,
		"repair_order_id": ro.repair_order_id,
		"status": ro.status,
		"total_cost": ro.total_cost,
		"stock_entry": ro.get("stock_entry"),
	}
