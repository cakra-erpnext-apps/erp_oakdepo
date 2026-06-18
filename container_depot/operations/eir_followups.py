"""Follow-up work derivable from a submitted EIR — detection + creation logic ONLY.

The wiring (when/where to fire these) is intentionally left to the caller: nothing here
is hooked into ``Inspection.on_submit`` or any menu. Call these from wherever you decide.

Rules (per ops):
- **Cleaning Order**  ← an EIR whose ``tank_status`` is ``Empty Dirty``.
- **Repair Order (M&R)** ← an EIR with at least one *real* Inspection Damage Entry — a
  row whose damage is other than Acceptable (``v``) or whose repair is other than No
  Action (``X``). (With the new checklist default these rows aren't even stored unless
  they are findings, but the filter is applied defensively for older / Desk-entered data.)
"""

from __future__ import annotations

import frappe

from container_depot.operations.eir import ACCEPTABLE_DAMAGE_CODE, NO_ACTION_REPAIR_CODE

EMPTY_DIRTY = "Empty Dirty"

# Container Movement-style copy guard for child rows.
_ROW_EXCLUDE = {
	"name", "parent", "parentfield", "parenttype", "idx",
	"owner", "creation", "modified", "modified_by", "docstatus", "doctype",
}


# --- detection ---------------------------------------------------------------
def eir_needs_cleaning(inspection) -> bool:
	"""True when the EIR's tank condition is Empty Dirty (→ a Cleaning Order is due)."""
	return frappe.db.get_value("Inspection", inspection, "tank_status") == EMPTY_DIRTY


def eir_real_damage_rows(inspection) -> list:
	"""Inspection Damage Entry rows of ``inspection`` that are real findings — damage
	other than Acceptable, or repair other than No Action."""
	rows = frappe.get_all(
		"Inspection Damage Entry",
		filters={"parent": inspection, "parenttype": "Inspection"},
		fields=[
			"name", "checklist_item", "damage_type", "repair_code",
			"damage_description", "severity", "area", "component",
			"before_photo", "after_photo",
		],
		order_by="idx asc",
	)
	out = []
	for r in rows:
		real_damage = r.damage_type and r.damage_type != ACCEPTABLE_DAMAGE_CODE
		real_repair = r.repair_code and r.repair_code != NO_ACTION_REPAIR_CODE
		if real_damage or real_repair:
			out.append(r)
	return out


def eir_needs_mr(inspection) -> bool:
	"""True when the EIR has at least one real damage/repair finding (→ M&R is due)."""
	return bool(eir_real_damage_rows(inspection))


# --- creation (idempotent; NOT auto-called) ----------------------------------
def create_cleaning_order_from_eir(inspection, ignore_permissions=True):
	"""Create a Pending Cleaning Order for an Empty-Dirty EIR's container. Idempotent:
	returns the existing open order (Pending / In_Progress) if one already exists.
	Returns the Cleaning Order name, or ``None`` when no cleaning is due."""
	insp = frappe.db.get_value(
		"Inspection", inspection, ["container", "tank_status", "depot"], as_dict=True
	)
	if not insp or not insp.container or insp.tank_status != EMPTY_DIRTY:
		return None
	existing = frappe.db.exists(
		"Cleaning Order", {"container": insp.container, "status": ["in", ["Pending", "In_Progress"]]}
	)
	if existing:
		return existing
	co = frappe.new_doc("Cleaning Order")
	co.container = insp.container
	co.inspection = inspection  # EIR -> Cleaning Order -> Certificate
	co.status = "Pending"
	# Carry the depot (for branch-scoped notifications) — from the EIR, else the container.
	depot = insp.depot or frappe.db.get_value("Container", insp.container, "depot")
	if depot and co.meta.has_field("depot"):
		co.depot = depot
	co.insert(ignore_permissions=ignore_permissions)
	return co.name


# An M&R is "open" (still in play) until it is finished or dropped.
MR_OPEN_STATUSES = ["Draft", "Pending Approval", "Approved", "In Progress"]


def open_repair_order(container) -> str | None:
	"""The container's open (not Completed/Cancelled) Repair Order, if any."""
	return frappe.db.get_value(
		"Repair Order", {"container": container, "status": ["in", MR_OPEN_STATUSES]}, "name"
	)


def seed_damages_from_eir(ro, inspection) -> None:
	"""Copy ALL of an EIR's damage entries (with their photos) into the M&R's read-only
	``damages`` table — a self-contained snapshot of what the EIR found. The team then
	records the services/parts used in a separate section.

	The PWA stores EIR photos in ``item_photos`` keyed by checklist item (not on the
	damage row), so for each finding we gather every photo of its checklist item, plus
	any before/after photo on the row, into a ``photos`` JSON list."""
	import json

	photos_by_item: dict = {}
	for p in frappe.get_all(
		"Inspection Item Photo",
		filters={"parent": inspection, "parenttype": "Inspection"},
		fields=["checklist_item", "photo"],
	):
		if p.photo:
			photos_by_item.setdefault(p.checklist_item, []).append(p.photo)

	rows = frappe.get_all(
		"Inspection Damage Entry",
		filters={"parent": inspection, "parenttype": "Inspection"},
		fields=[
			"checklist_item", "area", "component", "damage_type", "repair_code",
			"damage_description", "severity", "part_face", "location",
			"before_photo", "after_photo",
		],
		order_by="idx asc",
	)
	for r in rows:
		photos = list(photos_by_item.get(r.get("checklist_item"), []))
		for direct in (r.get("before_photo"), r.get("after_photo")):
			if direct and direct not in photos:
				photos.append(direct)
		ro.append("damages", {
			"checklist_item": r.get("checklist_item"),
			"area": r.get("area"),
			"component": r.get("component"),
			"damage_code": r.get("damage_type"),
			"repair_code": r.get("repair_code"),
			"damage_description": r.get("damage_description"),
			"severity": r.get("severity"),
			"part_face": r.get("part_face"),
			"location": r.get("location"),
			"before_photo": r.get("before_photo"),
			"after_photo": r.get("after_photo"),
			"photos": json.dumps(photos) if photos else None,
		})


def create_repair_order_from_eir(inspection, ignore_permissions=True):
	"""Create a **Draft** M&R (Repair Order) for an EIR with real damage findings — the
	team then edits it (picks inventory parts to replace/repair) before completing it.

	Idempotent **per container**: returns the container's existing open M&R if one is
	already in play (so an EIR-In draft and a later Detailed Survey don't double up).
	Seeds one estimation line per real damage finding (component + description) as a
	starting worklist. Returns the Repair Order name, or ``None`` when nothing is due."""
	rows = eir_real_damage_rows(inspection)
	if not rows:
		return None
	insp = frappe.db.get_value(
		"Inspection", inspection, ["container", "depot"], as_dict=True
	)
	if not insp or not insp.container:
		return None
	existing = open_repair_order(insp.container)
	if existing:
		# Make sure the open M&R points back at an EIR (the draft may pre-date this one).
		if not frappe.db.get_value("Repair Order", existing, "inspection"):
			frappe.db.set_value("Repair Order", existing, "inspection", inspection, update_modified=False)
		return existing
	ro = frappe.new_doc("Repair Order")
	ro.container = insp.container
	ro.inspection = inspection  # EIR -> M&R -> (parts issued on completion)
	ro.status = "Draft"
	ro.billing_status = "Unbilled"
	depot = insp.depot or frappe.db.get_value("Container", insp.container, "depot")
	if depot:
		ro.depot = depot
	seed_damages_from_eir(ro, inspection)
	ro.insert(ignore_permissions=ignore_permissions)
	return ro.name
