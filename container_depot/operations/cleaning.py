"""Core cleaning logic for the PWA Cleaning Order flow.

Mirrors ``operations/eir.py``: deliberately free of ``@frappe.whitelist`` so the
same functions back both the ESS PWA wrappers (``ess/cleaning.py``) and any Desk /
automation caller — the endpoint layer only adds auth + whitelisting.

Flow: EIR (Empty Dirty) -> Cleaning Order (auto-created, Pending) -> the team starts
it (In_Progress) -> fills the cleanliness checklist and submits -> Completed, which
mints the Cleaning Certificate. The cleanliness detail (checklist / gas free / seals /
signature) lives on the Cleaning Order itself — there is no separate statement doc.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, getdate, now_datetime, today

from container_depot.operations.user_branch import assert_in_user_branch, get_user_branches

# Default boiler-plate the OAK cleanliness statement prints unless the team overrides it.
DEFAULT_REMARKS = "TANK ALREADY STEAM 100°C\nTANK ALREADY PASSED LEAK TEST 1 BAR"

# Tank-spec fields read from the Container master for the form header + print.
_CONTAINER_FIELDS = [
	"name", "container_no", "container_type", "manufacture_date", "last_test_date",
	"tare_weight", "max_gross_weight", "capacity", "principal", "last_cargo",
	"depot", "seal_manhole", "seal_airline", "seal_bottom_outlet",
]


def _guard_container_branch(container_name) -> None:
	"""Block cleaning actions on a container outside the user's branch."""
	depot = frappe.db.get_value("Container", container_name, "depot")
	assert_in_user_branch(depot=depot)


def get_cleaning_masters() -> dict:
	"""Checklist taxonomy (grouped by section) + default remarks for the PWA form."""
	checklist = frappe.get_all(
		"Cleaning Checklist Item",
		filters={"is_active": 1},
		fields=["item_code", "section", "item_name", "sequence"],
		order_by="sequence asc",
	)
	return {"checklist": checklist, "default_remarks": DEFAULT_REMARKS}


def get_latest_valid_cleaning_cert(container) -> dict | None:
	"""Latest submitted Cleaning Certificate for a container + its validity.

	Validity mirrors the Order Muat gate (``order_muat._validate_cleaning_cert``): a cert
	is valid when it has no expiry (statement-minted = valid forever) OR ``valid_until >=
	today``. Returns ``{name, valid_until, valid}`` for the newest submitted cert, or
	``None`` when the container has none. Used by the EIR-Out flow to show + verify the
	cleaning certificate before load-out.
	"""
	row = frappe.db.get_value(
		"Cleaning Certificate",
		{"container": container, "docstatus": 1},
		["name", "valid_until"],
		as_dict=True,
		order_by="creation desc",
	)
	if not row:
		return None
	valid = (not row.valid_until) or getdate(row.valid_until) >= getdate(today())
	return {
		"name": row.name,
		"valid_until": str(row.valid_until) if row.valid_until else None,
		"valid": bool(valid),
	}


def _latest_eir(container: str) -> str | None:
	"""The newest submitted EIR for the container (the cleaning's source / anchor)."""
	return frappe.db.get_value(
		"Inspection",
		{"container": container, "docstatus": 1, "inspection_type": ["in", ["EIR-In", "EIR-Out"]]},
		"name",
		order_by="creation desc",
	)


def _default_place_of_issue(user, depot) -> str | None:
	"""Branch default for ``place_of_issue`` — the user's first branch, else the depot."""
	branches = get_user_branches(user)
	if branches:
		return branches[0]
	return depot


def cargo_history(container, limit=4) -> list:
	"""The container's recent cargo history from Container Booking Item — newest to
	oldest, capped at ``limit`` (default 4)."""
	cno = frappe.db.get_value("Container", container, "container_no")
	rows = frappe.get_all(
		"Container Booking Item",
		filters={"cargo": ["is", "set"]},
		or_filters={"container": container, "container_no": cno},
		fields=["cargo", "tanggal_bongkar", "creation"],
		order_by="creation desc",
		limit_page_length=cint(limit),
	)
	return [
		{"cargo": r.cargo, "date": str(r.tanggal_bongkar or r.creation)[:10]}
		for r in rows
	]


def list_open_cleaning_orders(start=0, page_length=20, search=None) -> dict:
	"""Open Cleaning Orders (Pending / In_Progress) the cleaning team still has to
	work — the PWA Cleaning menu's worklist. Depot-scoped to the caller's branch."""
	from container_depot.operations.user_branch import get_user_depots

	filters = {"status": ["in", ["Pending", "In_Progress"]], "docstatus": 0}
	depots = get_user_depots()
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]  # restricted user: only their depots
	or_filters = None
	search = (search or "").strip()
	if search and search.lower() != "undefined":  # guard the literal "undefined" string
		or_filters = {"container_no": ["like", f"%{search}%"], "order_id": ["like", f"%{search}%"]}
	items = frappe.get_all(
		"Cleaning Order",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "order_id", "container", "container_no", "status",
			"cleaning_type", "last_cargo", "depot", "order_created"],
		order_by="order_created asc",
		limit_start=cint(start),
		limit_page_length=cint(page_length),
	)
	# Number of chosen cleaning services per order (NOT the price — hidden from the depot PWA).
	names = [i.name for i in items]
	if names:
		from collections import Counter

		counts = Counter(frappe.get_all("Cleaning Order Service", filters={"parent": ["in", names]}, pluck="parent"))
		for i in items:
			i["service_count"] = counts.get(i.name, 0)
	return {"items": items, "total": frappe.db.count("Cleaning Order", filters)}


def list_cleaning_history(start=0, page_length=10, search=None) -> dict:
	"""Finished Cleaning Orders (Completed / Cancelled) — the PWA Cleaning "Riwayat" feed,
	newest first, paginated + searchable, depot-scoped to the caller's branch. Detail reuses
	``get_cleaning_order_detail``."""
	from container_depot.operations.user_branch import get_user_depots

	filters = {"status": ["in", ["Completed", "Cancelled"]]}
	depots = get_user_depots()
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]
	or_filters = None
	search = (search or "").strip()
	if search and search.lower() != "undefined":
		or_filters = {"container_no": ["like", f"%{search}%"], "order_id": ["like", f"%{search}%"]}
	items = frappe.get_all(
		"Cleaning Order",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "order_id", "container", "container_no", "status", "cleaning_type",
			"last_cargo", "depot", "cleaning_end", "order_created", "cleaning_certificate"],
		order_by="creation desc",
		limit_start=cint(start),
		limit_page_length=cint(page_length),
	)
	names = [i.name for i in items]
	if names:
		from collections import Counter

		counts = Counter(frappe.get_all("Cleaning Order Service", filters={"parent": ["in", names]}, pluck="parent"))
		for i in items:
			i["service_count"] = counts.get(i.name, 0)
	return {"items": items, "total": frappe.db.count("Cleaning Order", filters)}


def start_cleaning(cleaning_order):
	"""Move a Cleaning Order from Pending to In_Progress (the team has started work) and
	mirror it onto the container (-> Cleaning_In_Progress). The order stays a draft — it
	is only submitted (Completed) when the cleanliness checklist is finalized."""
	co = frappe.db.get_value(
		"Cleaning Order", cleaning_order, ["name", "container", "status", "docstatus"], as_dict=True
	)
	if not co:
		frappe.throw(_("Cleaning Order {0} not found.").format(cleaning_order))
	if co.docstatus == 1 or co.status == "Completed":
		frappe.throw(_("Cleaning Order sudah selesai."))
	_guard_container_branch(co.container)

	if co.status != "In_Progress":
		frappe.db.set_value(
			"Cleaning Order", co.name,
			{"status": "In_Progress", "cleaning_start": now_datetime()}, update_modified=True,
		)
	# The order is still a draft, so its controller propagation hasn't run — mirror the
	# In_Progress cleaning hint onto the container here (status stays presence-based).
	cont = frappe.get_doc("Container", co.container)
	cont.cleaning_status = "In_Progress"
	frappe.flags.in_status_automation = True
	try:
		cont.save(ignore_permissions=True)
	finally:
		frappe.flags.in_status_automation = False
	# An open cleaning order keeps the tank In_Depot.
	from container_depot.operations.container_status import recompute_availability

	recompute_availability(co.container)

	from container_depot.operations.container_activity import log_container_activity

	log_container_activity(
		co.container, "Cleaning",
		reference_doctype="Cleaning Order", reference_name=co.name,
		to_status=cont.status, summary="Cleaning started (In Progress)",
	)
	return {"success": True, "name": co.name, "status": "In_Progress", "container_status": cont.status}


def _cleaning_item_options(container) -> list:
	"""Cleaning Service items the container's Owner (Principal) is priced for: members of the
	Depot Service Menu "Cleaning" that have a selling Item Price in the owner's active Price
	List. Drives the PWA "Metode Cleaning" picker. The owner's RATE is deliberately NOT
	exposed to the depot PWA (it's resolved + stored server-side for billing only). Empty
	when there is no principal / no price list."""
	from container_depot import pricing_model
	from container_depot.operations import service_menu

	principal = frappe.db.get_value("Container", container, "principal") if container else None
	price_list = pricing_model.price_list_for_customer(principal) if principal else None
	if not price_list:
		return []
	return [
		{"item_code": i["item_code"], "item_name": i.get("item_name")}
		for i in service_menu.items_in_menu("Cleaning", base_price_list=price_list)
	]


def get_cleaning_order_detail(cleaning_order) -> dict:
	"""Everything the PWA form needs for one Cleaning Order: the order's own cleanliness
	state, the tank spec from the Container master, the saved checklist, recent cargo
	history and the issue defaults."""
	co = frappe.get_doc("Cleaning Order", cleaning_order)
	_guard_container_branch(co.container)
	c = frappe.db.get_value("Container", co.container, _CONTAINER_FIELDS, as_dict=True) or frappe._dict()
	user = frappe.session.user
	return {
		"name": co.name,
		"order_id": co.order_id,
		"status": co.status,
		"docstatus": co.docstatus,
		"container": co.container,
		"container_no": co.container_no or c.container_no,
		"inspection": co.inspection or _latest_eir(co.container),
		"cleaning_type": co.cleaning_type,
		# "Metode Cleaning" = one OR MORE billable Services from the Cleaning menu. The owner's
		# rate/total is NOT sent to the depot PWA (billing-only); ``cleaning_services`` is what's
		# chosen on this order, ``cleaning_items`` the full pickable catalogue for this owner.
		"cleaning_services": [
			{"item_code": r.cleaning_item, "item_name": r.item_name}
			for r in co.cleaning_services
		],
		"cleaning_items": _cleaning_item_options(co.container),
		"gas_free": co.gas_free,
		"o2_percent": co.o2_percent,
		"lel_percent": co.lel_percent,
		"seal_manhole": co.seal_manhole or c.seal_manhole,
		"seal_airline": co.seal_airline or c.seal_airline,
		"seal_bottom_outlet": co.seal_bottom_outlet or c.seal_bottom_outlet,
		"reff_doc": co.reff_doc,
		"remarks": co.remarks or DEFAULT_REMARKS,
		"signed_by": co.signed_by or user,
		"date_of_issue": co.date_of_issue or today(),
		"place_of_issue": co.place_of_issue or _default_place_of_issue(user, c.depot),
		"cleaning_certificate": co.cleaning_certificate,
		# Tank spec (read-only, from the Container master).
		"tank_type": c.container_type,
		"date_of_manufacture": c.manufacture_date,
		"last_test_date": c.last_test_date,
		"tare": c.tare_weight,
		"mgw": c.max_gross_weight,
		"capacity": c.capacity,
		"client": c.principal,
		"previous_cargo": c.last_cargo,
		# Saved checklist + recent cargo history + defaults.
		"saved_checklist": [
			{"item_code": r.checklist_item, "result": r.result, "note": r.note} for r in co.checklist
		],
		"cargo_history": cargo_history(co.container),
		"default_remarks": DEFAULT_REMARKS,
	}


def _coerce_list(value) -> list:
	if isinstance(value, str):
		value = json.loads(value) if value.strip() else []
	return value or []


def _as_bool(value) -> bool:
	if isinstance(value, str):
		return value.strip().lower() in ("1", "true", "yes")
	return bool(value)


def _build_checklist_rows(results) -> list:
	"""Map the surveyor's payload to checklist rows for ALL active items. ``results`` is
	a flat ``[{item_code, result, note}]`` payload; missing items default to "Yes"."""
	items = frappe.get_all(
		"Cleaning Checklist Item",
		filters={"is_active": 1},
		fields=["item_code", "section", "item_name"],
		order_by="sequence asc",
	)
	by_code = {}
	for r in _coerce_list(results):
		code = (r.get("item_code") or "").strip()
		if code:
			by_code[code] = r
	rows = []
	for it in items:
		payload = by_code.get(it.item_code, {})
		result = (payload.get("result") or "").strip() or "Yes"
		if result not in ("Yes", "No"):
			frappe.throw(_("Checklist result must be Yes or No (item {0}).").format(it.item_code))
		rows.append({
			"checklist_item": it.item_code,
			"section": it.section,
			"item_name": it.item_name,
			"result": result,
			"note": (payload.get("note") or "").strip() or None,
		})
	return rows


def save_cleaning_order(
	cleaning_order=None,
	cleaning_type=None,
	cleaning_items=None,
	gas_free=None,
	o2_percent=None,
	lel_percent=None,
	seal_manhole=None,
	seal_airline=None,
	seal_bottom_outlet=None,
	reff_doc=None,
	remarks=None,
	signature=None,
	results=None,
	submit=False,
) -> dict:
	"""Save the cleanliness detail onto a Cleaning Order and, when ``submit`` is true,
	complete it (which mints the Cleaning Certificate). Submitting requires the order to
	have been started (``before_submit`` guards this). Permissions are NOT bypassed."""
	if not cleaning_order:
		frappe.throw(_("cleaning_order is required."))
	co = frappe.get_doc("Cleaning Order", cleaning_order)
	if co.docstatus == 1:
		frappe.throw(_("Cleaning Order sudah selesai."))
	_guard_container_branch(co.container)

	# "Metode Cleaning" is now one OR MORE billable Service items (each priced from the
	# owner's Price List); the controller resolves every row's rate + the total. The legacy
	# free-text cleaning_type is still accepted for back-compat.
	if cleaning_items is not None:
		codes = _coerce_list(cleaning_items)
		seen, rows = set(), []
		for c in codes:
			code = (c.get("item_code") if isinstance(c, dict) else c) or ""
			code = code.strip()
			if code and code not in seen:
				seen.add(code)
				rows.append({"cleaning_item": code})
		co.set("cleaning_services", rows)
	if cleaning_type is not None:
		co.cleaning_type = cleaning_type
	if gas_free is not None:
		co.gas_free = gas_free
	co.o2_percent = o2_percent
	co.lel_percent = lel_percent
	if seal_manhole is not None:
		co.seal_manhole = seal_manhole
	if seal_airline is not None:
		co.seal_airline = seal_airline
	if seal_bottom_outlet is not None:
		co.seal_bottom_outlet = seal_bottom_outlet
	# Optional reference doc (usually pre-filled from the EIR; editable here).
	if reff_doc is not None:
		co.reff_doc = reff_doc
	co.remarks = remarks if remarks is not None else (co.remarks or DEFAULT_REMARKS)
	if signature:
		co.surveyor_signature = signature
	if not co.signed_by:
		co.signed_by = frappe.session.user
	if not co.date_of_issue:
		co.date_of_issue = today()
	if not co.place_of_issue:
		co.place_of_issue = _default_place_of_issue(frappe.session.user, co.depot)
	if results is not None:
		co.set("checklist", _build_checklist_rows(results))

	co.save()  # NOT ignore_permissions — Frappe enforces Cleaning Order write on the caller.
	if _as_bool(submit):
		co.submit()  # before_submit gate (must be started) + on_submit mints the cert

	return {
		"success": True,
		"name": co.name,
		"order_id": co.order_id,
		"status": co.status,
		"docstatus": co.docstatus,
		"cleaning_certificate": co.get("cleaning_certificate"),
	}
