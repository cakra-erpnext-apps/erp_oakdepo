"""Core M&R (Maintenance & Repair) logic for the PWA Repair Order flow.

Mirrors ``operations/cleaning.py``: deliberately free of ``@frappe.whitelist`` so the
same functions back both the ESS PWA wrappers (``ess/repairs.py``) and any Desk /
automation caller — the endpoint layer only adds auth + whitelisting.

Concept (two sections in the PWA):
  1. **Damages** — a read-only snapshot copied from the source EIR's damage entries (with
     photos) when the Draft M&R is auto-created. Pure information: what the EIR found.
  2. **Used Items** — the services / parts actually used, picked from the **owner's Item
     Price** list (service or part). Only the qty is shown (price is hidden but still
     computed for billing); each used item carries multiple evidence photos. Stock parts
     among them are issued from the source warehouse (Material Issue) on completion.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from container_depot.operations.eir_followups import MR_OPEN_STATUSES
from container_depot.operations.service_menu import filter_items_by_menu, is_real_menu
from container_depot.operations.user_branch import assert_in_user_branch, get_user_depots, get_user_warehouses
from container_depot.pricing_model import price_list_for_customer, resolve_price

# The Depot Service Menu the M&R item picker is scoped to. When this menu is
# missing / inactive / empty, the picker falls back to all owner-priced items.
MR_MENU = "Maintenance"

# Owner-approval status machine (single source of truth — shared by the controller,
# the ESS/PWA endpoints, and the Desk workflow buttons). The owner must approve the
# estimate (Pending Approval) before any work starts; they may reject, or ask for a
# revision, and may approve only some lines (partial approval, per Repair Used Item).
MR_TRANSITIONS = {
	# "Approved" straight from Draft / Revision / Service Setup is the Admin-Ops BYPASS
	# (skip the owner). It is code-guarded to Admin Ops in the ESS layer (bypass_approval);
	# the state machine only declares it a legal edge so validate() doesn't reject it.
	#
	# ``Service Setup`` is the Admin-Ops staging step: the workshop hands the estimate over
	# there, Admin Ops arranges it, and only ``publish_to_owner`` moves it to Pending
	# Approval — the first status the customer web can see. Pending Approval -> Service
	# Setup is the withdraw ("tarik ulang"), which re-opens editing for a re-submit.
	# "Draft" appears on every in-flight status because a human can always mis-enter or miss
	# an item — ``reopen_to_draft`` (Adm Ops) rewinds a Service Setup / Pending Approval /
	# Approved / In Progress M&R back to an editable Draft to fix it, then it goes through
	# approval again. Completed is deliberately excluded (parts already issued → Cancel instead).
	"Draft": ["Service Setup", "Approved", "Cancelled"],
	"Revision Requested": ["Service Setup", "Approved", "Draft", "Cancelled"],  # editable like Draft
	"Service Setup": ["Pending Approval", "Draft", "Approved", "Cancelled"],
	"Pending Approval": ["Approved", "Rejected", "Revision Requested", "Service Setup", "Draft", "Cancelled"],
	"Approved": ["In Progress", "Draft", "Cancelled"],
	"In Progress": ["Completed", "Draft", "Cancelled"],
	"Completed": [],
	"Rejected": ["Draft"],
	"Cancelled": [],
}
# Statuses where the depot may still edit the estimate (used items). Service Setup is
# included: arranging the estimate before the customer sees it is the whole point of it.
MR_EDITABLE_STATUSES = ("Draft", "Revision Requested", "Service Setup")

# Statuses the customer web may show. The owner only ever sees an estimate Admin Ops has
# explicitly published — never a Draft or a Service Setup still being arranged.
MR_CUSTOMER_VISIBLE_STATUSES = ("Pending Approval", "Approved", "Rejected", "In Progress", "Completed")

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
	"""Parse a Used Item ``photos`` JSON string into a list of file URLs."""
	if not value:
		return []
	try:
		out = json.loads(value)
		return [u for u in out if u] if isinstance(out, list) else []
	except (ValueError, TypeError):
		return []


# --- warehouse list (branch-filtered) ----------------------------------------
def list_warehouses(repair_order=None, container=None) -> dict:
	"""Source-warehouse options for the M&R, filtered to the container's branch."""
	if repair_order and not container:
		container = frappe.db.get_value("Repair Order", repair_order, "container")
	depot = frappe.db.get_value("Container", container, "depot") if container else None
	branch = _container_branch(depot)
	rows = _company_warehouses(_resolve_company(), branch=branch)
	return {"warehouses": rows, "branch": branch}


# --- item picker (priced by owner; service or part) --------------------------
def mr_item_search(search=None, repair_order=None, start=0, page_length=20, warehouse=None) -> dict:
	"""Item picker for the Used-Items section — services AND parts that have a selling
	Item Price in the owner's price list. Stock items carry their on-hand qty (at the
	M&R's source warehouse). When the owner has no price list, falls back to all items.

	``warehouse`` overrides the M&R's stored source warehouse. The caller passes the one
	currently picked on the *unsaved* form, so the stock shown belongs to the warehouse the
	user is actually looking at — reading it back from the database would show the previous
	warehouse's stock until the form is saved.
	"""
	pl = None
	warehouse = _clean(warehouse) or None
	if repair_order:
		ro = frappe.db.get_value("Repair Order", repair_order, ["principal", "container", "warehouse"], as_dict=True) or frappe._dict()
		principal = ro.principal or (frappe.db.get_value("Container", ro.container, "principal") if ro.container else None)
		pl = _owner_price_list(principal)
		warehouse = warehouse or ro.warehouse or _default_warehouse(_resolve_company(), frappe.db.get_value("Container", ro.container, "depot") if ro.container else None)

	priced = (
		frappe.get_all("Item Price", filters={"price_list": pl, "selling": 1}, pluck="item_code", distinct=True)
		if pl
		else None
	)
	filters = {"disabled": 0}
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
		fields=["name", "repair_order_id", "container", "container_no", "status",
			"principal", "depot", "total_cost", "creation"],
		order_by="creation asc", limit_start=cint(start), limit_page_length=cint(page_length),
	)
	return {"items": items, "total": frappe.db.count("Repair Order", filters)}


# Execution phase — the PWA M&R menu is the field/cleaning division's console: it only shows
# work the owner (or an Admin-Ops bypass) has already approved. Estimate-building and the
# owner decision live in Desk (ERP).
MR_EXECUTION_STATUSES = ["Approved", "In Progress"]


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


def list_mr_execution(start=0, page_length=20, search=None) -> dict:
	"""Approved / In Progress M&R orders — the PWA execution worklist (start -> done).
	Depot-scoped to the caller's branch."""
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
		fields=["name", "repair_order_id", "container", "container_no", "status",
			"principal", "depot", "total_cost", "creation"],
		order_by="creation asc", limit_start=cint(start), limit_page_length=cint(page_length),
	)
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
	resolved code descriptions + photos) and the Used Items (Section 2: item, qty, photos),
	the tank spec and the branch-filtered source-warehouse options."""
	ro = frappe.get_doc("Repair Order", repair_order)
	_guard_container_branch(ro.container)
	c = frappe.db.get_value("Container", ro.container, _CONTAINER_FIELDS, as_dict=True) or frappe._dict()
	company = _resolve_company()
	warehouse = ro.warehouse or _default_warehouse(company, c.depot)

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
		"item": r.item, "item_name": r.item_name, "is_stock_item": r.is_stock_item,
		"quantity": r.quantity, "remark": r.remark,
		# Owner-approval: prices + per-line decision are exposed (the owner approves by cost).
		"decision": r.decision or "Pending",
		"owner_remark": r.owner_remark,
		# Labour + item breakdown; `amount` is the line's Total Cost.
		"manhour": r.manhour, "manhour_rate": r.manhour_rate, "manhour_amount": r.manhour_amount,
		"item_rate": r.item_rate, "item_amount": r.item_amount,
		"amount": r.amount, "currency": r.currency,
		"photos": _photos_list(r.photos),
		"on_hand": _on_hand(r.item, warehouse) if r.item and r.is_stock_item else None,
	} for r in ro.used_items]

	wh = list_warehouses(container=ro.container)
	return {
		"name": ro.name,
		"repair_order_id": ro.repair_order_id,
		"status": ro.status,
		"actions": MR_TRANSITIONS.get(ro.status, []),
		"container": ro.container,
		"container_no": ro.container_no or c.container_no,
		"inspection": ro.inspection,
		"technician": ro.technician,
		"warehouse": warehouse,
		"warehouses": wh["warehouses"],
		"branch": wh["branch"],
		"reff_doc": ro.reff_doc,
		"remarks": ro.remarks,
		"stock_entry": ro.stock_entry,
		# Owner-approval surface.
		"total_cost": ro.total_cost,
		"owner_note": ro.owner_note,
		"requested_on": str(ro.requested_on) if ro.requested_on else None,
		"decided_on": str(ro.decided_on) if ro.decided_on else None,
		"revision_no": ro.revision_no,
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
	}


# --- owner approval ----------------------------------------------------------
def submit_for_approval(repair_order):
	"""Hand the estimate to Admin Ops: Draft / Revision Requested -> Service Setup.

	This does NOT reach the customer. Admin Ops arranges the estimate in Service Setup and
	then :func:`publish_to_owner` puts it on the customer web. Requires at least one used
	item; per-line decisions are reset to Pending so a re-submitted revision starts a fresh
	decision round.
	"""
	ro = frappe.get_doc("Repair Order", repair_order)
	_guard_container_branch(ro.container)
	if ro.status not in ("Draft", "Revision Requested"):
		frappe.throw(
			_("M&R hanya bisa diajukan dari Draft / Revision Requested (status: {0}).").format(ro.status)
		)
	if not (ro.used_items and len(ro.used_items) > 0):
		frappe.throw(_("Tambahkan minimal satu item sebelum mengajukan."))
	for r in ro.used_items:
		r.decision = "Pending"
		r.owner_remark = None
	ro.status = "Service Setup"
	ro.save()
	from container_depot.operations.notify import notify_repair_order_service_setup
	notify_repair_order_service_setup(ro.name)
	return {"success": True, "name": ro.name, "status": ro.status}


def publish_to_owner(repair_order):
	"""Admin Ops publishes the arranged estimate to the customer web: Service Setup ->
	Pending Approval.

	This is the moment the owner can first see (and decide on) the estimate, so
	``requested_on`` is stamped here rather than at ``submit_for_approval`` — it measures
	how long the OWNER has had it, not how long it sat with Admin Ops. Re-publishing after
	a withdraw restarts that clock, which is what "ajukan ulang" means.
	"""
	ro = frappe.get_doc("Repair Order", repair_order)
	_guard_container_branch(ro.container)
	if ro.status != "Service Setup":
		frappe.throw(
			_("Hanya M&R berstatus Service Setup yang bisa ditampilkan ke customer (status: {0}).").format(ro.status)
		)
	if not (ro.used_items and len(ro.used_items) > 0):
		frappe.throw(_("Tambahkan minimal satu item sebelum menampilkan ke customer."))
	ro.status = "Pending Approval"
	ro.requested_on = now_datetime()
	ro.save()
	from container_depot.operations.notify import notify_repair_order_pending_approval
	notify_repair_order_pending_approval(ro.name)
	return {"success": True, "name": ro.name, "status": ro.status}


def withdraw_from_owner(repair_order, note=None):
	"""Admin Ops pulls a published estimate back off the customer web ("tarik ulang"):
	Pending Approval -> Service Setup.

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
	ro.status = "Service Setup"
	ro.requested_on = None
	if note:
		ro.owner_note = _clean(note)
	ro.save()
	return {"success": True, "name": ro.name, "status": ro.status}


def reopen_to_draft(repair_order, note=None):
	"""Rewind an in-flight M&R back to an editable **Draft** so a human can fix a wrong /
	missing input, then run it through approval again.

	Allowed from Service Setup, Pending Approval, Approved, In Progress and Rejected — every
	stage before the parts are actually issued. NOT from Completed (the stock issue already
	happened; use Cancel + a fresh order) nor Cancelled. Wipes the approval round entirely
	(per-line decisions, requested_on / decided_on / decided_by) so the re-quote starts clean;
	the used items are kept — editing them is the whole point. Adm Ops action (role gate in the
	ESS wrapper); branch-guarded here."""
	ro = frappe.get_doc("Repair Order", repair_order)
	_guard_container_branch(ro.container)
	REOPENABLE = ("Service Setup", "Pending Approval", "Approved", "In Progress", "Rejected", "Revision Requested")
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
	try:
		msg = _("M&R dikembalikan ke Draft dari {0} oleh {1}").format(prev, frappe.session.user)
		if note:
			msg += ": " + _clean(note)
		ro.add_comment("Comment", msg)
	except Exception:
		frappe.log_error(title="M&R reopen_to_draft comment", message=frappe.get_traceback())
	return {"success": True, "name": ro.name, "status": ro.status}


def bypass_approval(repair_order, note=None):
	"""Admin-Ops BYPASS: approve the estimate directly (Draft / Revision Requested ->
	Approved) without sending it to the owner. Same preconditions as ``submit_for_approval``
	(≥1 used item); every still-Pending line is auto-approved so the total + stock issue are
	consistent with a normal Approved.

	The Admin-Ops role gate lives in the ESS wrapper (``mr_bypass_approval``); this function
	enforces the branch + status preconditions only, mirroring ``record_decision``'s Approved
	branch."""
	ro = frappe.get_doc("Repair Order", repair_order)
	_guard_container_branch(ro.container)
	if ro.status not in MR_EDITABLE_STATUSES:
		frappe.throw(_("Bypass hanya dari Draft / Revision Requested (status: {0}).").format(ro.status))
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
	ro.save()
	from container_depot.operations.notify import notify_repair_order_decided
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

	ro.save()
	from container_depot.operations.notify import notify_repair_order_decided
	notify_repair_order_decided(ro.name)
	return {"success": True, "name": ro.name, "status": ro.status, "total_cost": ro.total_cost}


# --- lifecycle ---------------------------------------------------------------
def start_repair(repair_order):
	"""Move an Approved M&R into work (In Progress). The controller mirrors this onto the
	container (-> Repair_In_Progress). Approval is mandatory, so only Approved may start."""
	ro = frappe.get_doc("Repair Order", repair_order)
	_guard_container_branch(ro.container)
	if ro.status != "Approved":
		frappe.throw(_("M&R harus Approved oleh owner sebelum dimulai (status: {0}).").format(ro.status))
	ro.status = "In Progress"
	if not ro.start_date:
		ro.start_date = now_datetime()
	ro.save()
	return {"success": True, "name": ro.name, "status": ro.status}


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
		photos = u.get("photos")
		photos = _coerce_list(photos) if photos is not None else []
		rows.append({
			"item": item,
			"quantity": flt(u.get("quantity")) or 1,
			"remark": _clean(u.get("remark")),
			"photos": json.dumps([p for p in photos if p]) if photos else None,
		})
	ro.set("used_items", rows)


def _requested_stock_qty(ro) -> dict:
	"""Stockable quantity this M&R will actually issue, summed **per item**.

	Mirrors :func:`_issue_parts_stock` line for line — an owner-rejected line is never
	issued, so it is never counted against stock either. Summing per item (not per row) is
	the point: two rows of one seal kit are a single demand of two.
	"""
	want = {}
	for r in ro.used_items or []:
		if (r.get("decision") or "Pending") == "Rejected":
			continue
		if not r.item or flt(r.quantity) <= 0:
			continue
		if not frappe.db.get_value("Item", r.item, "is_stock_item"):
			continue
		want[r.item] = want.get(r.item, 0.0) + flt(r.quantity)
	return want


def source_warehouse(ro) -> str | None:
	"""The warehouse an M&R issues its parts from: the one picked on the order, else the
	branch default. Single source of truth for the item picker, the stock guard and the
	grid's Stok column, so all three always talk about the same warehouse."""
	if ro.get("warehouse"):
		return ro.warehouse
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
	"""Refuse an M&R whose source warehouse cannot cover its parts — stock must exist
	before the part can be put on the order.

	Every shortfall goes into ONE message so a mis-entered estimate is fixed in a single
	pass instead of one error per save. No-op when no source warehouse resolves yet: the
	stock is unknowable then, and ``_issue_parts_stock`` refuses to run without one anyway.

	Note this is about the message, not about data safety — ``allow_negative_stock`` is off
	and a failed Material Issue already rolls the whole completion back. What it buys is
	catching the shortfall while the estimate is being typed, naming the part and the
	numbers, instead of a raw Stock Entry error after the user presses Selesai.
	"""
	want = _requested_stock_qty(ro)
	if not want:
		return
	warehouse = source_warehouse(ro)
	if not warehouse:
		return
	short = []
	for item_code, qty in want.items():
		have = _on_hand(item_code, warehouse)
		if flt(qty) > flt(have):
			label = frappe.db.get_value("Item", item_code, "item_name") or item_code
			short.append(_("{0} — diminta {1}, tersedia {2}").format(label, flt(qty), flt(have)))
	if short:
		frappe.throw(
			_("Stok tidak cukup di {0}:<br>{1}").format(warehouse, "<br>".join(short)),
			title=_("Stok Tidak Cukup"),
		)


def _issue_parts_stock(ro) -> str | None:
	"""Issue the M&R's stockable Used Items out of the source warehouse as a Material
	Issue. Returns the Stock Entry name, or ``None`` when nothing is stockable. Raises
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
		lines.append((r.item, flt(r.quantity), item.stock_uom))
	if not lines:
		return None

	company = _resolve_company()
	if not company:
		frappe.throw(_("Tidak ada Company default untuk mengeluarkan part dari stok."))
	warehouse = ro.warehouse or _default_warehouse(company, frappe.db.get_value("Container", ro.container, "depot"))
	if not warehouse:
		frappe.throw(_("Tidak ada warehouse sumber untuk mengeluarkan part. Pilih 'Gudang Sumber Part' dulu."))

	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Material Issue"
	se.company = company
	se.from_warehouse = warehouse
	se.remarks = f"M&R {ro.repair_order_id or ro.name} • {ro.container_no or ro.container}"
	for item_code, qty, uom in lines:
		se.append("items", {
			"item_code": item_code, "qty": qty, "s_warehouse": warehouse,
			"uom": uom, "stock_uom": uom, "conversion_factor": 1,
		})
	se.insert(ignore_permissions=True)
	se.submit()
	return se.name


def save_mr_order(
	repair_order=None,
	used_items=None,
	technician=None,
	warehouse=None,
	reff_doc=None,
	remarks=None,
	submit=False,
) -> dict:
	"""Save the M&R's Used Items (+ source warehouse / remarks) and, when ``submit`` is
	true, complete it — which issues the stockable **approved** parts and returns the tank
	to the ready pool. Used items may only be edited while Draft / Revision Requested;
	completion is only allowed from In Progress (approval is mandatory). The copied
	``damages`` are read-only. Rates follow the owner's Item Price (controller-computed)."""
	if not repair_order:
		frappe.throw(_("repair_order is required."))
	ro = frappe.get_doc("Repair Order", repair_order)
	if ro.status in ("Completed", "Cancelled", "Rejected"):
		frappe.throw(_("M&R sudah {0}.").format(ro.status))
	_guard_container_branch(ro.container)

	submitting = _as_bool(submit)
	if submitting and ro.status != "In Progress":
		frappe.throw(_("M&R harus In Progress untuk diselesaikan (status: {0}).").format(ro.status))
	if used_items is not None and ro.status not in MR_EDITABLE_STATUSES:
		frappe.throw(_("Item hanya bisa diubah saat Draft / Revision Requested."))

	if warehouse is not None:
		warehouse = _clean(warehouse)
		if warehouse:
			assert_in_user_branch(branch=frappe.db.get_value("Warehouse", warehouse, "branch"))
		ro.warehouse = warehouse
	if used_items is not None:
		_apply_used_items(ro, used_items)
	if technician is not None:
		ro.technician = _clean(technician)
	# Optional reference doc (usually pre-filled from the EIR; editable here).
	if reff_doc is not None:
		ro.reff_doc = reff_doc
	if remarks is not None:
		ro.remarks = remarks

	if submitting:
		# Re-checked here (not just on save): stock can drop between the estimate and the
		# completion when another M&R issues the same part first.
		assert_stock_available(ro)
		stock_entry = _issue_parts_stock(ro)
		if stock_entry:
			ro.stock_entry = stock_entry
		ro.status = "Completed"
		if not ro.completion_date:
			ro.completion_date = now_datetime()

	ro.save()  # before_save -> calculate_totals() (prices from Item Price) + container sync
	return {
		"success": True,
		"name": ro.name,
		"repair_order_id": ro.repair_order_id,
		"status": ro.status,
		"total_cost": ro.total_cost,
		"stock_entry": ro.get("stock_entry"),
	}
