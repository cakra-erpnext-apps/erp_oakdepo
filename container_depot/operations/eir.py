"""Core EIR (Equipment Interchange Receipt) logic for the web/checklist flow.

Deliberately free of ``@frappe.whitelist`` so the exact same functions back both
the ESS PWA wrappers (``ess/inspections.py``) and any Desk / automation caller —
the endpoint layer only adds auth + whitelisting. All resolution and build rules
live here.

Hard rule: this module NEVER writes ``Container.status``. Status transitions stay
in ``Inspection.on_submit`` (the established controller); we only build the
Inspection and let submit drive the container.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

# Damage code "v" = Acceptable — it is recorded as a condition but does not mean
# the tank "has damage".
ACCEPTABLE_DAMAGE_CODE = "v"


def get_eir_masters() -> dict:
	"""Checklist taxonomy + active damage / repair code lists for the EIR grid."""
	checklist = frappe.get_all(
		"EIR Checklist Item",
		filters={"is_active": 1},
		fields=["item_code", "printed_no", "area", "item_name", "sequence"],
		order_by="sequence asc",
	)
	damage_codes = frappe.get_all(
		"EIR Damage Code",
		filters={"is_active": 1},
		fields=["name as code", "description"],
		order_by="code asc",
	)
	repair_codes = frappe.get_all(
		"EIR Repair Code",
		filters={"is_active": 1},
		fields=["name as code", "description"],
		order_by="code asc",
	)
	return {"checklist": checklist, "damage_codes": damage_codes, "repair_codes": repair_codes}


def iso6346_parts(container_no: str | None) -> dict:
	"""Display-only ISO 6346 split of a container number — NOT stored anywhere.

	prefix = first 4 letters, number = next 6 digits, cd = the final check digit.
	Returns ``None`` parts for anything too short to split.
	"""
	if not container_no:
		return {"prefix": None, "number": None, "cd": None}
	cn = container_no.strip().upper()
	return {
		"prefix": cn[:4] if len(cn) >= 4 else cn or None,
		"number": cn[4:10] if len(cn) >= 5 else None,
		"cd": cn[10] if len(cn) >= 11 else None,
	}


def prefill(
	container: str | None = None,
	container_no: str | None = None,
	booking_code: str | None = None,
	order_bongkar: str | None = None,
) -> dict:
	"""Resolve EIR header defaults for the Container being inspected.

	The EIR inspects a physical container, so the **Container is the key**: its
	template fields (serial, manufacture, capacity, tare, MWG, last test/cargo,
	depot) and its ``principal`` (tank owner) come straight from the Container
	master — whose name equals the container number (autoname ``field:container_no``).

	``booking_code`` / ``order_bongkar`` remain accepted for back-compat and
	automation: they only resolve the container when one was not supplied and enrich
	``ex_vessel`` / ``direction`` — never the required entry point. Also returns the
	display-only ISO 6346 prefix/number/cd derived from the container number.
	"""
	name = container or container_no
	booking = direction = bc_name = None

	if not name and booking_code:
		bc = frappe.db.get_value(
			"Booking Code", booking_code,
			["name", "container", "container_no", "booking", "direction"], as_dict=True,
		)
		if not bc:
			frappe.throw(_("Booking Code {0} not found.").format(booking_code))
		bc_name, booking, direction = bc.name, bc.booking, bc.direction
		name = bc.container or (
			frappe.db.get_value("Container", {"container_no": bc.container_no})
			if bc.container_no else None
		)
	elif not name and order_bongkar:
		ob = frappe.db.get_value("Order Bongkar", order_bongkar, ["name", "booking"], as_dict=True)
		if not ob:
			frappe.throw(_("Order Bongkar {0} not found.").format(order_bongkar))
		booking = ob.booking
		row = frappe.db.get_value(
			"Container Booking Item",
			{"parent": order_bongkar, "parenttype": "Order Bongkar"},
			["container", "booking_code"], as_dict=True, order_by="idx asc",
		)
		if row:
			name, bc_name = row.container, row.booking_code
		if bc_name:
			direction = frappe.db.get_value("Booking Code", bc_name, "direction")

	if not name:
		frappe.throw(_("Provide a container number (or a booking_code / order_bongkar)."))

	c = frappe.db.get_value(
		"Container", name,
		["name", "container_no", "serial_no", "manufacture_date", "capacity",
		 "tare_weight", "max_gross_weight", "last_test_date", "last_cargo", "depot", "principal"],
		as_dict=True,
	)
	if not c:
		frappe.throw(_("Container {0} not found.").format(name))

	# Principal / tank owner is a property of the container itself.
	principal = c.principal

	ex_vessel = frappe.db.get_value("Order Bongkar", order_bongkar, "ex_vessel") if order_bongkar else None
	if not ex_vessel and booking:
		ex_vessel = frappe.db.get_value("Order Bongkar", {"booking": booking}, "ex_vessel")

	parts = iso6346_parts(c.container_no)
	return {
		"booking_code": bc_name,
		"booking": booking,
		"direction": direction,
		"container": c.name,
		"container_no": c.container_no,
		"serial_no": c.serial_no,
		"manufacture_date": c.manufacture_date,
		"capacity": c.capacity,
		"tare_weight": c.tare_weight,
		"max_gross_weight": c.max_gross_weight,
		"last_test_date": c.last_test_date,
		"last_cargo": c.last_cargo,
		"depot": c.depot,
		"principal": principal,
		"ex_vessel": ex_vessel,
		# Display-only — derived, never persisted.
		"prefix": parts["prefix"],
		"number": parts["number"],
		"cd": parts["cd"],
	}


def _coerce_lines(lines) -> list:
	if lines is None:
		return []
	if isinstance(lines, str):
		try:
			lines = json.loads(lines)
		except json.JSONDecodeError:
			frappe.throw(_("lines must be a JSON array."))
	if not isinstance(lines, list):
		frappe.throw(_("lines must be a list of checklist rows."))
	return lines


def _as_bool(value) -> bool:
	if isinstance(value, str):
		return value.strip().lower() in ("1", "true", "yes", "on")
	return bool(value)


def _checklist_items() -> dict:
	"""item_code -> {printed_no, item_name, area} for every checklist item."""
	return {
		i.item_code: i
		for i in frappe.get_all(
			"EIR Checklist Item", fields=["item_code", "printed_no", "item_name", "area"]
		)
	}


def _build_damage_rows(lines, items):
	"""Map checklist payload lines to Damage Entry rows (only filled lines).

	Blank ("Acceptable") lines are skipped. reqd Damage Entry fields are defaulted
	server-side (severity=Minor; description from remark, else damage code desc, else
	item name). Returns ``(rows, has_damage)`` — has_damage true for any real damage
	code (not "v").
	"""
	rows, has_damage = [], False
	for ln in lines:
		item_code = (ln.get("item_code") or "").strip()
		damage_code = (ln.get("damage_code") or "").strip() or None
		repair_code = (ln.get("repair_code") or "").strip() or None
		line_remarks = (ln.get("remarks") or "").strip() or None
		if not (damage_code or repair_code or line_remarks):
			continue  # Acceptable / empty — not stored.

		item = items.get(item_code)
		if not item:
			frappe.throw(_("Unknown checklist item_code: {0}").format(item_code or "(blank)"))

		description = line_remarks
		if not description and damage_code:
			description = frappe.db.get_value("EIR Damage Code", damage_code, "description")
		if not description:
			description = item.item_name

		if damage_code and damage_code != ACCEPTABLE_DAMAGE_CODE:
			has_damage = True

		rows.append({
			"checklist_item": item_code,
			"component": f"{item.printed_no}. {item.item_name}",
			"damage_type": damage_code,
			"repair_code": repair_code,
			"damage_description": description,  # fulfils reqd (B2)
			"severity": "Minor",               # default fulfils reqd (B2)
		})
	return rows, has_damage


def _build_photo_rows(photos, items):
	"""Map a flat ``[{item_code, photo}]`` payload to EIR Item Photo rows (blanks skipped)."""
	rows = []
	for ph in photos:
		item_code = (ph.get("item_code") or "").strip()
		photo = (ph.get("photo") or "").strip()
		if not (item_code and photo):
			continue
		if item_code not in items:
			frappe.throw(_("Unknown checklist item_code for photo: {0}").format(item_code or "(blank)"))
		rows.append({"checklist_item": item_code, "photo": photo})
	return rows


def create_eir(
	inspection_type: str,
	container: str,
	tank_status: str | None = None,
	booking_code: str | None = None,
	order_ref: str | None = None,
	order_doctype: str | None = None,
	vessel: str | None = None,
	truck_no: str | None = None,
	emkl: str | None = None,
	remarks: str | None = None,
	depot: str | None = None,
	lines=None,
	photos=None,
	submit=False,
) -> dict:
	"""Build an Inspection (EIR) from a checklist payload.

	Only lines carrying a ``damage_code``, ``repair_code`` or ``remarks`` become
	Damage Entry rows — blank ("Acceptable") lines are not stored. The reqd Damage
	Entry fields are defaulted server-side (severity=Minor; damage_description from
	the line remarks, else the damage code's description, else the item name) so the
	checklist flow never trips validation (B2).

	``has_damage`` is true when any line carries a real damage code (not "v").
	``inspector`` is the session user. Status transitions are NOT done here — when
	``submit`` is true the Inspection is submitted and its ``on_submit`` drives the
	container. Permissions are NOT bypassed: Frappe rejects roles lacking Inspection
	create/submit.
	"""
	if inspection_type not in ("EIR-In", "EIR-Out"):
		frappe.throw(_("inspection_type must be EIR-In or EIR-Out."))
	if not container:
		frappe.throw(_("container is required."))

	lines = _coerce_lines(lines)
	photos = _coerce_lines(photos)
	submit = _as_bool(submit)

	items = _checklist_items()
	damage_rows, has_damage = _build_damage_rows(lines, items)
	photo_rows = _build_photo_rows(photos, items)

	doc = frappe.new_doc("Inspection")
	doc.inspection_type = inspection_type
	doc.container = container
	doc.tank_status = tank_status
	doc.booking_code = booking_code
	doc.vessel = vessel
	doc.truck_no = truck_no
	doc.emkl = emkl
	doc.remarks = remarks
	doc.depot = depot
	doc.inspector = frappe.session.user
	doc.has_damage = 1 if has_damage else 0
	if order_ref:
		doc.order_doctype = order_doctype or "Order Bongkar"
		doc.order_ref = order_ref
	doc.set("damage_log", damage_rows)
	doc.set("item_photos", photo_rows)

	doc.insert()  # NOT ignore_permissions — let Frappe enforce Inspection create.
	if submit:
		doc.submit()  # on_submit moves the Container; we never set status here.

	return {
		"success": True,
		"name": doc.name,
		"inspection_id": doc.inspection_id,
		"docstatus": doc.docstatus,
		"has_damage": doc.has_damage,
		"damage_rows": len(damage_rows),
		"photo_rows": len(photo_rows),
	}


def _draft_payload(doc, header: dict) -> dict:
	"""Merge a draft Inspection's saved state onto the master-derived ``header``.

	The tank fields stay sourced from the Container master (actual current data); the
	checklist lines, photos and user-entered fields come from the draft.
	"""
	header["inspection"] = doc.name
	header["inspection_type"] = doc.inspection_type
	header["tank_status"] = doc.tank_status
	header["truck_no"] = doc.truck_no
	header["emkl"] = doc.emkl
	header["doc_remarks"] = doc.remarks
	if doc.vessel:
		header["vessel"] = doc.vessel  # draft overrides the master-derived ex_vessel
	header["lines"] = [
		{
			"item_code": d.checklist_item,
			"damage_code": d.damage_type or "",
			"repair_code": d.repair_code or "",
			"remarks": d.damage_description or "",
		}
		for d in doc.damage_log if d.checklist_item
	]
	header["photos"] = [
		{"item_code": p.checklist_item, "photo": p.photo} for p in doc.item_photos
	]
	return header


def open_draft(container=None, container_no=None, inspection_type="EIR-In") -> dict:
	"""Get-or-create a draft EIR for a container and return it with the master header.

	The EIR is auto-created on first fetch so the result is recorded even if the user
	leaves before saving; a later fetch of the same container returns the SAME draft
	(deduped by container + docstatus=0) instead of a duplicate. The tank header always
	reflects the Container master; lines / photos / user fields come from the draft.
	"""
	if inspection_type not in ("EIR-In", "EIR-Out"):
		inspection_type = "EIR-In"

	header = prefill(container=container, container_no=container_no)
	name = header["container"]

	existing = frappe.get_all(
		"Inspection",
		filters={"container": name, "docstatus": 0, "inspection_type": ["in", ["EIR-In", "EIR-Out"]]},
		pluck="name", order_by="creation desc", limit=1,
	)
	if existing:
		doc = frappe.get_doc("Inspection", existing[0])
	else:
		doc = frappe.new_doc("Inspection")
		doc.inspection_type = inspection_type
		doc.container = name
		doc.depot = header.get("depot")
		doc.inspector = frappe.session.user
		doc.insert()  # NOT ignore_permissions — only EIR creators can open a draft.

	return _draft_payload(doc, header)


def save_draft(
	inspection: str,
	inspection_type: str | None = None,
	tank_status: str | None = None,
	vessel: str | None = None,
	truck_no: str | None = None,
	emkl: str | None = None,
	remarks: str | None = None,
	lines=None,
	photos=None,
	submit=False,
) -> dict:
	"""Update an existing draft EIR — the PWA auto-save (and finalize) action.

	The PWA owns the draft's checklist state, so ``damage_log`` + ``item_photos`` are
	replaced wholesale from the payload. ``submit`` finalizes the EIR: the Inspection
	is submitted and its ``on_submit`` drives the container (we never set status here).
	Permissions are enforced (no bypass).
	"""
	doc = frappe.get_doc("Inspection", inspection)
	if doc.docstatus != 0:
		frappe.throw(_("EIR {0} is no longer a draft.").format(inspection))

	submit = _as_bool(submit)
	items = _checklist_items()
	damage_rows, has_damage = _build_damage_rows(_coerce_lines(lines), items)
	photo_rows = _build_photo_rows(_coerce_lines(photos), items)

	if inspection_type in ("EIR-In", "EIR-Out"):
		doc.inspection_type = inspection_type
	doc.tank_status = tank_status
	doc.vessel = vessel
	doc.truck_no = truck_no
	doc.emkl = emkl
	doc.remarks = remarks
	doc.has_damage = 1 if has_damage else 0
	doc.set("damage_log", damage_rows)
	doc.set("item_photos", photo_rows)

	if submit:
		doc.submit()  # on_submit moves the Container; we never set status here.
	else:
		doc.save()  # NOT ignore_permissions.

	return {
		"success": True,
		"inspection": doc.name,
		"docstatus": doc.docstatus,
		"has_damage": doc.has_damage,
		"damage_rows": len(damage_rows),
		"photo_rows": len(photo_rows),
	}
