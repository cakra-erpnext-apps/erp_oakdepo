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
	return [r for r in rows if damage_row_needs_mr(r)]


def damage_row_needs_mr(row) -> bool:
	"""One Inspection Damage Entry read as an indication of damage — the four tests spelled
	out in :func:`eir_real_damage_rows`, on a single row.

	Split out so the rule has ONE home: ``Inspection.sync_followup_flags`` asks it about rows
	that are still in memory (unsaved), and ``inspection.js`` mirrors it in the browser to
	tick the "Buat M&R" box live.
	"""
	damage_type = row.get("damage_type")
	repair_code = row.get("repair_code")
	real_damage = damage_type and damage_type != ACCEPTABLE_DAMAGE_CODE
	real_repair = repair_code and repair_code != NO_ACTION_REPAIR_CODE
	noted = bool((row.get("damage_description") or "").strip())
	uncoded = not damage_type and not repair_code
	return bool(real_damage or real_repair or noted or uncoded)


def eir_needs_mr(inspection) -> bool:
	"""True when the EIR carries at least one indication of damage (→ M&R is due) — a real
	damage code, a real repair code, a note the surveyor typed, or a checklist row with no
	codes filled in yet."""
	return bool(eir_real_damage_rows(inspection))


# --- creation (idempotent; NOT auto-called) ----------------------------------
def create_cleaning_order_from_eir(inspection, ignore_permissions=True, force=False):
	"""Create a Pending Cleaning Order for an Empty-Dirty EIR's container. Idempotent:
	returns the existing open order (Pending / In_Progress) if one already exists.
	Returns the Cleaning Order name, or ``None`` when no cleaning is due.

	``force`` skips the Empty-Dirty test. The "Buat Cleaning Order" checkbox is the
	operator's own call — they may know the tank needs washing for a reason the EIR's
	tank_status does not spell out — so a ticked box files the order whatever the status
	says. Automatic callers leave ``force`` off and keep the evidence test."""
	insp = frappe.db.get_value(
		"Inspection", inspection, ["container", "tank_status", "depot"], as_dict=True
	)
	if not insp or not insp.container:
		return None
	if not force and insp.tank_status != EMPTY_DIRTY:
		return None
	# This EIR already filed a Cleaning Order once — hand back the same one whatever state
	# it has reached, instead of filing a second order for the same visit. An EIR can be
	# submitted more than once (``eir.revert_to_draft`` sends it back for correction), and
	# the order it spawned the first time is NOT undone by that revert: it may already be
	# finished and billed. Checked before the open-order lookup below, which only sees
	# orders still in play and would happily duplicate a Completed one.
	spawned = frappe.db.get_value(
		"Cleaning Order", {"inspection": inspection, "status": ["!=", "Cancelled"]}, "name"
	)
	if spawned:
		return spawned
	existing = frappe.db.exists(
		"Cleaning Order",
		{"container": insp.container, "status": ["in", ["Service Setup", "Pending", "In_Progress"]]},
	)
	if existing:
		return existing
	co = frappe.new_doc("Cleaning Order")
	co.container = insp.container
	co.inspection = inspection  # EIR -> Cleaning Order
	# Reff Doc is NOT inherited from the EIR: a cleaning ordered by the principal usually
	# quotes their own instruction number, which is not the paper the tank arrived on. Left
	# blank for whoever files the order to type what the customer actually gave them.
	# Order yang lahir dari EIR-In tank kotor SELALU cleaning standar. Tiga jenis khusus
	# (PP Wash / Methanol Rinse / Steam Wash) adalah permintaan principal atas tank yang
	# sudah bersih dan parkir di yard — tidak pernah punya EIR-In kotor sebagai pemicu.
	# Jadi jenis di sini sekaligus menandai ASAL order, yang dibaca dashboard dan register
	# per jenis. Admin Ops tetap bebas mengubahnya di Service Setup kalau principal minta.
	co.cleaning_type = "Standard Cleaning"
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


def create_repair_order_from_eir(inspection, ignore_permissions=True, force=False):
	"""Create a **Draft** M&R (Repair Order) for an EIR with real damage findings — the
	team then edits it (picks inventory parts to replace/repair) before completing it.

	Idempotent **per container**: returns the container's existing open M&R if one is
	already in play (so an EIR-In draft and a later Detailed Survey don't double up).
	Seeds one estimation line per real damage finding (component + description) as a
	starting worklist. Returns the Repair Order name, or ``None`` when nothing is due.

	``force`` skips the damage-finding test — same reasoning as the Cleaning Order above:
	a ticked "Buat M&R" box is a decision, not a guess, and the M&R is born a Draft the
	team fills in anyway. Forced without findings it simply seeds no damage lines."""
	rows = eir_real_damage_rows(inspection)
	if not rows and not force:
		return None
	insp = frappe.db.get_value(
		"Inspection", inspection, ["container", "depot"], as_dict=True
	)
	if not insp or not insp.container:
		return None
	# Same rule as the Cleaning Order: one M&R per EIR, forever. ``open_repair_order`` below
	# only knows about orders still in play, so a re-submitted EIR whose M&R was already
	# completed would otherwise get a second Draft — with the parts of the first one already
	# issued and billed.
	spawned = frappe.db.get_value(
		"Repair Order", {"inspection": inspection, "status": ["!=", "Cancelled"]}, "name"
	)
	if spawned:
		return spawned
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
		return existing
	ro = frappe.new_doc("Repair Order")
	ro.container = insp.container
	ro.inspection = inspection  # EIR -> M&R -> (parts issued on completion)
	# Reff Doc deliberately left blank — same reason as the Cleaning Order above: the repair
	# is approved on the owner's own paperwork, not on the bon the tank came in with.
	ro.status = "Draft"
	ro.billing_status = "Unbilled"
	depot = insp.depot or frappe.db.get_value("Container", insp.container, "depot")
	if depot:
		ro.depot = depot
	seed_damages_from_eir(ro, inspection)
	ro.insert(ignore_permissions=ignore_permissions)
	return ro.name


# --- the inverse: unwinding what a submit filed ------------------------------
def release_followups_for_eir(inspection) -> dict:
	"""Cancel the Cleaning Order / M&R that submitting this EIR filed, when nobody has
	touched them yet — the counterpart of the two ``create_*_from_eir`` calls above.

	Voiding an EIR is saying the inspection never happened, so the work it ordered off the
	back of it must not stay on the depot's queues: an untouched auto-order left behind is a
	wash nobody asked for sitting in Admin Ops' Service Setup list, or an empty M&R draft the
	team keeps opening to find nothing in it.

	Deliberately narrow — an order is only dropped while it is still exactly as it was born:

	* **Cleaning Order** — still a draft in ``Service Setup`` / ``Pending`` and never started.
	  The link is exact: ``create_cleaning_order_from_eir`` only stamps ``inspection`` on an
	  order it CREATED (the branch that adopts an already-open order deliberately does not).
	* **M&R** — still ``Draft``, no estimate line, no parts issued, and raised after this EIR
	  existed. That last test is what keeps an M&R the depot raised by hand — which the
	  creation call may have adopted and stamped — out of it.

	Anything past those states is real work: the wash may be half done, the estimate may
	already be with the owner. That stays, and the depot closes it itself. Cancelled, never
	deleted: the queues read ``status``, and an order somebody saw is worth being able to
	find.
	"""
	from container_depot.container_depot.notify import revoke

	out = {"cleaning": [], "repair": []}
	if not inspection:
		return out
	created = frappe.db.get_value("Inspection", inspection, "creation")

	for name in frappe.get_all(
		"Cleaning Order",
		filters={
			"inspection": inspection,
			"docstatus": 0,
			"status": ["in", ["Service Setup", "Pending"]],
			"cleaning_start": ["is", "not set"],
		},
		pluck="name",
	):
		frappe.db.set_value("Cleaning Order", name, "status", "Cancelled", update_modified=False)
		# Raw write, so the controller's own revoke never runs — the "tank kotor, siap
		# dicuci" prompt has to be taken out of the bell by hand.
		revoke("Cleaning Order", name)
		out["cleaning"].append(name)

	for name in frappe.get_all(
		"Repair Order",
		filters={
			"inspection": inspection,
			"status": "Draft",
			"stock_entry": ["is", "not set"],
			"creation": [">=", created],
		},
		pluck="name",
	):
		if frappe.db.count("Repair Used Item", {"parent": name, "parenttype": "Repair Order"}):
			continue  # somebody has started estimating — that is work, not a phantom
		frappe.db.set_value("Repair Order", name, "status", "Cancelled", update_modified=False)
		revoke("Repair Order", name)
		out["repair"].append(name)

	return out
