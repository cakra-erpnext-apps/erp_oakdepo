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
from frappe.utils import cint

from container_depot.operations.user_branch import assert_in_user_branch

# Damage code "v" = Acceptable — it is recorded as a condition but does not mean
# the tank "has damage".
ACCEPTABLE_DAMAGE_CODE = "v"


def _guard_container_branch(container_name) -> None:
	"""Block EIR actions on a container whose depot is outside the user's branch."""
	depot = frappe.db.get_value("Container", container_name, "depot")
	assert_in_user_branch(depot=depot)


def get_eir_masters() -> dict:
	"""Checklist taxonomy + active damage / repair code lists for the EIR grid."""
	checklist = frappe.get_all(
		"Inspection Checklist Item",
		filters={"is_active": 1},
		fields=["item_code", "printed_no", "area", "item_name", "sequence"],
		order_by="sequence asc",
	)
	damage_codes = frappe.get_all(
		"Inspection Damage Code",
		filters={"is_active": 1},
		fields=["name as code", "description"],
		order_by="code asc",
	)
	repair_codes = frappe.get_all(
		"Inspection Repair Code",
		filters={"is_active": 1},
		fields=["name as code", "description"],
		order_by="code asc",
	)
	# Active cargos for the EIR's "set last cargo" picker (name == cargo_name).
	cargos = frappe.get_all("Cargo", filters={"is_active": 1}, pluck="name", order_by="name asc")
	return {
		"checklist": checklist,
		"damage_codes": damage_codes,
		"repair_codes": repair_codes,
		"cargos": cargos,
	}


def _voucher_doctype(inspection_type: str | None) -> str:
	"""EIR-In references the unloading bon (Order Bongkar); every other EIR (EIR-Out)
	references the loading bon (Order Muat)."""
	return "Order Bongkar" if inspection_type == "EIR-In" else "Order Muat"


_VOUCHER_CHILD = {
	"Order Bongkar": "Container Booking Item",
	"Order Muat": "Order Container Item",
}


def _voucher_has_container(doctype: str, voucher: str, container: str) -> bool:
	"""True if ``container`` is one of the bon's container rows."""
	return bool(frappe.db.exists(
		_VOUCHER_CHILD[doctype],
		{"parent": voucher, "parenttype": doctype, "container": container},
	))


# Container Booking Item.condition (UPPER) -> Inspection.tank_status (Title).
_CONDITION_TO_TANK_STATUS = {
	"EMPTY CLEAN": "Empty Clean",
	"EMPTY DIRTY": "Empty Dirty",
	"LADEN": "Laden",
}

# Per-container detail fields read from a Container Booking Item row.
_CBI_DETAIL = ["truck_plate", "driver", "driver_phone", "condition", "cargo"]


def _booking_item_detail(booking, container):
	"""The booking's Container Booking Item line for ``container`` (per-container detail)."""
	if not (booking and container):
		return frappe._dict()
	return frappe.db.get_value(
		"Container Booking Item",
		{"parent": booking, "parenttype": "Container Booking", "container": container},
		_CBI_DETAIL, as_dict=True,
	) or frappe._dict()


def _voucher_detail(doctype, voucher, container):
	"""Per-container shipment detail (truck / driver / driver phone / condition / cargo)
	from Container Booking Item.

	Order Bongkar's own ``containers`` ARE Container Booking Item rows, so the detail is
	read straight from the matching row. Order Muat uses Order Container Item (no detail)
	and carries truck/driver on its header — its condition/cargo come from the booking's
	Container Booking Item line for the same container.
	"""
	if doctype == "Order Bongkar":
		return frappe.db.get_value(
			"Container Booking Item",
			{"parent": voucher, "parenttype": "Order Bongkar", "container": container},
			_CBI_DETAIL, as_dict=True,
		) or frappe._dict()
	header = frappe.db.get_value(
		"Order Muat", voucher,
		["truck_plate", "driver_name", "driver_phone", "booking"], as_dict=True,
	) or frappe._dict()
	bk = _booking_item_detail(header.get("booking"), container)
	return frappe._dict(
		truck_plate=header.get("truck_plate"),
		driver=header.get("driver_name"),
		driver_phone=header.get("driver_phone"),
		condition=bk.get("condition"),
		cargo=bk.get("cargo"),
	)


def fetch_voucher(voucher: str | None, inspection_type: str = "EIR-In", container: str | None = None) -> dict:
	"""Read the EIR's shipment snapshot for ``container`` from a referred voucher (bon).

	The per-container detail (truck no, driver, driver phone, tank status, cargo) comes
	from **Container Booking Item**: for EIR-In the Order Bongkar's own rows carry it; for
	EIR-Out the Order Muat keeps truck/driver on its header and the condition/cargo come
	from the booking line. ``shipper`` is the bon header. truck/driver/phone are stored
	read-only on the EIR; tank_status/cargo are returned as editable defaults. Missing
	fields come back ``None``; ``voucher=None`` yields an all-None snapshot.

	The voucher must be **submitted** and (when ``container`` is given) must actually
	carry that container — an EIR can only reference the bon the tank is really on.
	"""
	doctype = _voucher_doctype(inspection_type)
	snap = {
		"voucher_doctype": doctype,
		"referred_voucher": None,
		"truck_no": None,
		"driver": None,
		"driver_phone": None,
		"shipper": None,
		"tank_status": None,
		"cargo": None,
	}
	if not voucher:
		return snap
	vdoc = frappe.db.get_value(doctype, voucher, ["name", "docstatus"], as_dict=True)
	if not vdoc:
		frappe.throw(_("{0} {1} not found.").format(doctype, voucher))
	if vdoc.docstatus != 1:
		frappe.throw(_("{0} {1} is not submitted yet.").format(doctype, voucher))
	if container and not _voucher_has_container(doctype, voucher, container):
		frappe.throw(_("Container {0} is not on {1} {2}.").format(container, doctype, voucher))
	snap["referred_voucher"] = voucher
	snap["shipper"] = frappe.db.get_value(doctype, voucher, "shipper")
	detail = _voucher_detail(doctype, voucher, container)
	snap["truck_no"] = detail.get("truck_plate")
	snap["driver"] = detail.get("driver")
	snap["driver_phone"] = detail.get("driver_phone")
	snap["tank_status"] = _CONDITION_TO_TANK_STATUS.get((detail.get("condition") or "").strip().upper())
	snap["cargo"] = detail.get("cargo")
	return snap


def _apply_voucher(doc, referred_voucher: str | None) -> None:
	"""Stamp the read-only shipment snapshot from ``referred_voucher`` onto an Inspection
	(or clear it when no voucher). The voucher doctype follows the inspection type."""
	snap = fetch_voucher(referred_voucher, doc.inspection_type, container=doc.container)
	doc.voucher_doctype = snap["voucher_doctype"]
	doc.referred_voucher = snap["referred_voucher"]
	doc.truck_no = snap["truck_no"]
	doc.driver = snap["driver"]
	doc.driver_phone = snap["driver_phone"]
	doc.shipper = snap["shipper"]


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
		 "tare_weight", "max_gross_weight", "last_test_date", "last_cargo", "ex_vessel",
		 "depot", "principal"],
		as_dict=True,
	)
	if not c:
		frappe.throw(_("Container {0} not found.").format(name))

	_guard_container_branch(c.name)

	# Principal / tank owner and the ex-vessel are properties of the container itself
	# (ex_vessel is stamped onto the Container when its Order Bongkar is submitted).
	principal = c.principal
	ex_vessel = c.ex_vessel

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
			"Inspection Checklist Item", fields=["item_code", "printed_no", "item_name", "area"]
		)
	}


def _build_damage_rows(lines, items):
	"""Map checklist payload lines to Inspection Damage Entry rows (only filled lines).

	Blank ("Acceptable") lines are skipped. reqd Inspection Damage Entry fields are defaulted
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
			description = frappe.db.get_value("Inspection Damage Code", damage_code, "description")
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
	"""Map a flat ``[{item_code, photo}]`` payload to Inspection Item Photo rows (blanks skipped)."""
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
	signature: str | None = None,
	referred_voucher: str | None = None,
	cargo: str | None = None,
	eir_date: str | None = None,
	lines=None,
	photos=None,
	submit=False,
) -> dict:
	"""Build an Inspection (EIR) from a checklist payload.

	Only lines carrying a ``damage_code``, ``repair_code`` or ``remarks`` become
	Inspection Damage Entry rows — blank ("Acceptable") lines are not stored. The reqd Damage
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
	_guard_container_branch(container)

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
	doc.vessel = vessel
	doc.truck_no = truck_no
	doc.emkl = emkl
	doc.remarks = remarks
	doc.depot = depot
	doc.inspector = frappe.session.user
	doc.inspector_signature = signature
	doc.eir_date = eir_date
	doc.cargo = cargo
	if referred_voucher:
		_apply_voucher(doc, referred_voucher)  # overrides truck_no; sets driver / driver_phone / shipper
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
	header["eir_date"] = doc.eir_date
	header["tank_status"] = doc.tank_status
	header["cargo"] = doc.cargo  # draft's chosen cargo (defaults to the master's last_cargo)
	header["referred_voucher"] = doc.referred_voucher
	header["voucher_doctype"] = doc.voucher_doctype
	header["truck_no"] = doc.truck_no
	header["driver"] = doc.driver
	header["driver_phone"] = doc.driver_phone
	header["shipper"] = doc.shipper
	header["emkl"] = doc.emkl
	header["doc_remarks"] = doc.remarks
	header["inspector_signature"] = doc.inspector_signature
	if doc.vessel:
		header["vessel"] = doc.vessel  # legacy free-text vessel (kept for back-compat)
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
		doc.cargo = header.get("last_cargo")  # start from the container's current cargo
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
	signature: str | None = None,
	referred_voucher: str | None = None,
	cargo: str | None = None,
	eir_date: str | None = None,
	lines=None,
	photos=None,
	submit=False,
) -> dict:
	"""Update an existing draft EIR — the PWA auto-save (and finalize) action.

	The PWA owns the draft's checklist state, so ``damage_log`` + ``item_photos`` (and
	the EIR-creator ``inspector_signature``) are replaced wholesale from the payload. The
	truck/driver/shipper snapshot is re-resolved from ``referred_voucher``; ``cargo`` is
	recorded on the draft but only written back to ``Container.last_cargo`` on submit.
	``submit`` finalizes the EIR: the Inspection is submitted and its ``on_submit`` drives
	the container's status + cargo writeback (we never set status here). Permissions are
	enforced (no bypass).
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
	doc.vessel = vessel  # legacy free-text; ex_vessel now comes from the Container master
	doc.emkl = emkl
	doc.remarks = remarks
	doc.eir_date = eir_date
	doc.cargo = cargo  # written to Container.last_cargo only on submit (drafts never touch the master)
	doc.inspector_signature = signature
	# The voucher owns truck_no / driver / driver_phone / shipper (read-only snapshot);
	# the legacy ``truck_no`` arg is ignored. No voucher -> these are cleared.
	_apply_voucher(doc, referred_voucher)
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


def list_my_eirs(user=None, search=None, start=0, page_length=10) -> dict:
	"""The caller's own EIR inspections — newest first, searchable + paginated.

	Hard-scoped to ``owner == user`` (and EIR-In / EIR-Out) so a user only ever sees the
	EIRs they created. ``frappe.get_all`` is used deliberately (it ignores row-level
	permissions) — the owner filter is the security boundary. Search matches the container
	number or the EIR id; ``start`` / ``page_length`` paginate.
	"""
	user = user or frappe.session.user
	start = max(0, cint(start))
	page_length = min(max(1, cint(page_length or 10)), 50)

	filters = {"owner": user, "inspection_type": ["in", ["EIR-In", "EIR-Out"]]}
	or_filters = None
	if search and str(search).strip():
		s = f"%{str(search).strip()}%"
		or_filters = [["container_no", "like", s], ["inspection_id", "like", s]]

	total = len(frappe.get_all(
		"Inspection", filters=filters, or_filters=or_filters, pluck="name", limit_page_length=0
	))
	items = frappe.get_all(
		"Inspection",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name", "inspection_id", "container", "container_no", "inspection_type",
			"status", "tank_status", "docstatus", "eir_date", "creation",
		],
		order_by="creation desc",
		limit_start=start,
		limit_page_length=page_length,
	)
	return {"items": items, "total": total, "start": start, "page_length": page_length}


@frappe.whitelist()
def revert_to_draft(name: str) -> dict:
	"""Cancel a submitted EIR back to Draft so it can be edited again (Desk-only action).

	Rule (per ops): every EIR for the container must be submitted first — there must be
	NO other draft Inspection for the same container. This keeps the one-draft-per-
	container invariant the PWA's ``open_draft`` relies on (it returns the single
	``docstatus=0`` EIR for a container). The container status / last-cargo this EIR
	applied on submit are undone from the pre-submit snapshot, then the SAME record is
	flipped back to an editable draft (so it opens again in the PWA and in Desk).
	"""
	doc = frappe.get_doc("Inspection", name)
	doc.check_permission("cancel")

	if doc.docstatus != 1:
		frappe.throw(_("Hanya EIR yang sudah disubmit yang bisa dikembalikan ke draft."))

	# Detailed Survey spawns M&R downstream docs (Repair Order / Survey Request); reverting
	# those safely is out of scope here — cancel via the M&R flow instead.
	if doc.inspection_type == "Detailed Survey":
		frappe.throw(_(
			"Detailed Survey tidak bisa dikembalikan ke draft dari sini karena sudah "
			"membuat Repair Order / menutup Survey Request. Gunakan alur M&R."
		))

	# Guard: no OTHER draft EIR for the same container.
	others = frappe.get_all(
		"Inspection",
		filters={"container": doc.container, "docstatus": 0, "name": ["!=", doc.name]},
		pluck="name",
	)
	if others:
		frappe.throw(_(
			"Masih ada EIR draft untuk container {0}: {1}. Submit dulu semua draft "
			"sebelum mengembalikan EIR ini ke draft."
		).format(doc.container, ", ".join(others)))

	_restore_container_on_revert(doc)

	# Flip back to an editable draft (same record — editable in the PWA + Desk).
	frappe.db.set_value("Inspection", doc.name, {"docstatus": 0, "status": "Draft"})

	# Append an inverse activity for the audit trail (the on_submit one stays — the log
	# is append-only). Never let a logging failure block the revert.
	try:
		from container_depot.operations.container_activity import log_container_activity
		log_container_activity(
			doc.container, "Inspection (EIR)",
			reference_doctype=doc.doctype, reference_name=doc.name,
			summary=_("{0} dikembalikan ke draft").format(doc.inspection_id or doc.name),
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "revert_to_draft activity log")

	return {"name": doc.name, "docstatus": 0, "status": "Draft"}


def _restore_container_on_revert(doc) -> None:
	"""Undo the Container status / last_cargo change this EIR applied on submit, using the
	snapshot captured in ``Inspection.on_submit``. Only writes when something differs."""
	container = frappe.get_doc("Container", doc.container)
	changed = False

	prev_status = doc.get("container_status_before_submit")
	if prev_status and container.status != prev_status:
		container.status = prev_status
		changed = True

	# Restore last_cargo only when THIS EIR carried a cargo (i.e. could have changed it).
	if doc.get("cargo"):
		prev_cargo = doc.get("container_last_cargo_before_submit") or None
		if container.last_cargo != prev_cargo:
			container.last_cargo = prev_cargo
			changed = True

	if not changed:
		return

	# Controller-driven status change: bypass the manual-transition guard.
	frappe.flags.in_status_automation = True
	try:
		container.save(ignore_permissions=True)
	finally:
		frappe.flags.in_status_automation = False
