"""Follow-up work derivable from a submitted EIR — detection + creation logic ONLY.

The wiring (when/where to fire these) is intentionally left to the caller: nothing here
is hooked into ``Inspection.on_submit`` or any menu. Call these from wherever you decide.

Rules (per ops):
- **Cleaning Order**  ← an EIR whose ``tank_status`` is ``Empty Dirty``.
- **Repair Order (M&R)** ← an EIR with at least one Inspection Damage Entry that is not
  an explicitly-clean card: any row carrying a real damage code, a real repair code, a
  remark, or NO codes at all (a part written onto the checklist with nothing ticked yet).
  Only a row coded Acceptable (``v``) + No Action (``X``) with no remark is skipped — that
  is the PWA storing an opened-and-fine card, not a finding.
"""

from __future__ import annotations

import frappe

from container_depot.container_depot.eir import ACCEPTABLE_DAMAGE_CODE, NO_ACTION_REPAIR_CODE

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
	"""Inspection Damage Entry rows of ``inspection`` worth an M&R.

	Four things count as an indication of damage:

	* a damage code other than Acceptable,
	* a repair code other than No Action,
	* **a note the surveyor typed** — even on a card coded Acceptable / No Action. Somebody
	  standing at the tank wrote something down about that part; that is the indication, and
	  letting the code alone veto it meant the M&R team never heard about it.
	* **a row with no codes at all** — a part written onto the Checklist Kerusakan without
	  anything being ticked. Nobody adds a line to that table to say a part is fine; the line
	  itself is the report, and the codes are what the M&R team fills in. Requiring a code
	  first meant a hand-entered checklist submitted silently and no M&R ever appeared.

	An OPENED-but-clean card is the one case that stays out: it carries the codes explicitly
	(Acceptable + No Action), which is the PWA saying "checked, nothing wrong" rather than a
	blank line waiting to be worked.

	Note this is deliberately wider than ``eir.is_real_finding`` (which decides what reads as
	a "kerusakan" on screen and which photos are evidence): a noted-but-acceptable part still
	shows as checked-and-fine, it just also reaches the M&R queue.
	"""
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
		noted = bool((r.damage_description or "").strip())
		uncoded = not r.damage_type and not r.repair_code
		if real_damage or real_repair or noted or uncoded:
			out.append(r)
	return out


def eir_needs_mr(inspection) -> bool:
	"""True when the EIR carries at least one indication of damage (→ M&R is due) — a real
	damage code, a real repair code, a note the surveyor typed, or a checklist row with no
	codes filled in yet."""
	return bool(eir_real_damage_rows(inspection))


# --- creation (idempotent; NOT auto-called) ----------------------------------
def create_cleaning_order_from_eir(inspection, ignore_permissions=True):
	"""Create a Pending Cleaning Order for an Empty-Dirty EIR's container. Idempotent:
	returns the existing open order (Pending / In_Progress) if one already exists.
	Returns the Cleaning Order name, or ``None`` when no cleaning is due."""
	insp = frappe.db.get_value(
		"Inspection", inspection, ["container", "tank_status", "depot", "reff_doc"], as_dict=True
	)
	if not insp or not insp.container or insp.tank_status != EMPTY_DIRTY:
		return None
	existing = frappe.db.exists(
		"Cleaning Order",
		{"container": insp.container, "status": ["in", ["Service Setup", "Pending", "In_Progress"]]},
	)
	if existing:
		# Backfill the reference doc from the EIR if the open order doesn't have one yet.
		if insp.reff_doc and not frappe.db.get_value("Cleaning Order", existing, "reff_doc"):
			frappe.db.set_value("Cleaning Order", existing, "reff_doc", insp.reff_doc, update_modified=False)
		return existing
	co = frappe.new_doc("Cleaning Order")
	co.container = insp.container
	co.inspection = inspection  # EIR -> Cleaning Order
	co.reff_doc = insp.reff_doc  # reference doc flows through from the EIR
	# Land in Admin Ops' queue first (Service Setup); Admin Ops picks the cleaning method(s)
	# and forwards it to the depot operator (-> Pending) from the Desk Cleaning Order.
	co.status = "Service Setup"
	# Carry the depot (for branch-scoped notifications) — from the EIR, else the container.
	depot = insp.depot or frappe.db.get_value("Container", insp.container, "depot")
	if depot and co.meta.has_field("depot"):
		co.depot = depot
	co.insert(ignore_permissions=ignore_permissions)
	return co.name


# An M&R is "open" (still in play) until it is finished or dropped. "Revision Requested"
# bounces back to the depot for edits, so it stays on the worklist too.
MR_OPEN_STATUSES = [
	"Draft", "Pending Approval", "Approved", "Revision Requested",
	"Pending", "In Progress", "Pending Review",
]


def open_repair_order(container) -> str | None:
	"""The container's open (not Completed/Cancelled) Repair Order, if any."""
	return frappe.db.get_value(
		"Repair Order", {"container": container, "status": ["in", MR_OPEN_STATUSES]}, "name"
	)


def seed_damages_from_eir(ro, inspection) -> None:
	"""Copy ALL of an EIR's damage entries (with their photos) into the M&R's read-only
	``damages`` table — a self-contained snapshot of what the EIR found. The team then
	records the services/parts used in a separate section.

	EIR photos are keyed by checklist item, not by damage row: the evidence for a finding
	lives in ``damage_photos`` and the general walk-around shots in ``item_photos``. Both are
	gathered here — a photo taken before the defect code was entered sits in the second table
	until the next save moves it — plus any before/after photo on the row itself."""
	import json

	photos_by_item: dict = {}
	for table in ("Inspection Damage Photo", "Inspection Item Photo"):
		for p in frappe.get_all(
			table,
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
		"Inspection", inspection, ["container", "depot", "reff_doc"], as_dict=True
	)
	if not insp or not insp.container:
		return None
	existing = open_repair_order(insp.container)
	if existing:
		# Make sure the open M&R points back at an EIR (the draft may pre-date this one).
		if not frappe.db.get_value("Repair Order", existing, "inspection"):
			frappe.db.set_value("Repair Order", existing, "inspection", inspection, update_modified=False)
			# db_set skips the controller, so the booking link that before_save would have
			# derived has to be written here too — otherwise adopting an existing M&R
			# leaves it attributed to no visit while a freshly created one is attributed.
			from container_depot.container_depot.booking_link import booking_of_inspection

			booking = booking_of_inspection(inspection)
			if booking and not frappe.db.get_value("Repair Order", existing, "container_booking"):
				frappe.db.set_value(
					"Repair Order", existing, "container_booking", booking, update_modified=False
				)
		# Backfill the reference doc from the EIR if the open order doesn't have one yet.
		if insp.reff_doc and not frappe.db.get_value("Repair Order", existing, "reff_doc"):
			frappe.db.set_value("Repair Order", existing, "reff_doc", insp.reff_doc, update_modified=False)
		return existing
	ro = frappe.new_doc("Repair Order")
	ro.container = insp.container
	ro.inspection = inspection  # EIR -> M&R -> (parts issued on completion)
	ro.reff_doc = insp.reff_doc  # reference doc flows through from the EIR
	ro.status = "Draft"
	ro.billing_status = "Unbilled"
	depot = insp.depot or frappe.db.get_value("Container", insp.container, "depot")
	if depot:
		ro.depot = depot
	seed_damages_from_eir(ro, inspection)
	ro.insert(ignore_permissions=ignore_permissions)
	return ro.name
