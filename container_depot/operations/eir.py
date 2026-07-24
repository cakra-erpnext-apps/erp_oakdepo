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
from frappe.utils import cint, getdate, now_datetime, time_diff_in_seconds, today

from container_depot.operations.user_branch import assert_in_user_branch, get_user_depots

# Damage code "v" = Acceptable — it is recorded as a condition but does not mean
# the tank "has damage". Repair code "X" = No Action. A part left at Acceptable +
# No Action (the form default) carries no finding and is not stored.
ACCEPTABLE_DAMAGE_CODE = "v"
NO_ACTION_REPAIR_CODE = "X"


def _guard_container_branch(container_name) -> None:
	"""Block EIR actions on a container whose depot is outside the user's branch."""
	depot = frappe.db.get_value("Container", container_name, "depot")
	assert_in_user_branch(depot=depot)


def _attach_allowed_codes(checklist: list) -> None:
	"""Attach each checklist part's valid defect / repair codes (from the workbook-seeded
	tables on ``Inspection Checklist Item``) so the PWA can narrow its pickers to the codes
	that make sense for that part. A part with an empty table keeps the full code list.

	Repairs keep the workbook's primary (✓) vs optional (○) split: primaries come first.
	"""
	names = [c["item_code"] for c in checklist]
	if not names:
		return
	damages, repairs = {}, {}
	for row in frappe.get_all(
		"Inspection Checklist Damage Option",
		filters={"parent": ["in", names], "parenttype": "Inspection Checklist Item"},
		fields=["parent", "damage_code"],
		order_by="idx asc",
	):
		damages.setdefault(row.parent, []).append(row.damage_code)
	for row in frappe.get_all(
		"Inspection Checklist Repair Option",
		filters={"parent": ["in", names], "parenttype": "Inspection Checklist Item"},
		fields=["parent", "repair_code", "is_primary"],
		order_by="is_primary desc, idx asc",
	):
		repairs.setdefault(row.parent, []).append(row.repair_code)
	for c in checklist:
		c["damage_codes"] = damages.get(c["item_code"], [])
		c["repair_codes"] = repairs.get(c["item_code"], [])


def get_eir_masters() -> dict:
	"""Checklist taxonomy + active damage / repair code lists for the EIR grid."""
	checklist = frappe.get_all(
		"Inspection Checklist Item",
		filters={"is_active": 1},
		fields=["item_code", "printed_no", "area", "item_name", "sequence"],
		order_by="sequence asc",
	)
	_attach_allowed_codes(checklist)
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


def _voucher_depot(doctype: str, voucher: str | None) -> str | None:
	"""The depot behind a bon: ``voucher.booking`` -> ``Container Booking.depot``.

	An EIR created from a bon should record the booking's depot (where the tank is
	being handled per that order), not necessarily the Container master's current depot.
	"""
	if not voucher:
		return None
	booking = frappe.db.get_value(doctype, voucher, "booking")
	if not booking:
		return None
	return frappe.db.get_value("Container Booking", booking, "depot")


def _voucher_reff_doc(doctype: str, voucher: str | None) -> str | None:
	"""The reference doc carried by a bon's Container Booking (``voucher.booking`` ->
	``Container Booking.reff_doc``). This is what makes a Reff Doc entered on the booking
	flow down the chain: Booking -> bon -> EIR -> Cleaning Order / M&R.
	"""
	if not voucher:
		return None
	booking = frappe.db.get_value(doctype, voucher, "booking")
	if not booking:
		return None
	return frappe.db.get_value("Container Booking", booking, "reff_doc")


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
		"depot": None,
		"reff_doc": None,
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
	snap["depot"] = _voucher_depot(doctype, voucher)
	snap["reff_doc"] = _voucher_reff_doc(doctype, voucher)
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
	# Depot follows the bon's booking when one is referenced; left untouched when the
	# voucher is cleared (so it falls back to the Container master depot set at creation).
	if snap.get("depot"):
		doc.depot = snap["depot"]
	# Reff Doc flows down from the bon's Container Booking, but only fills an EIR that has
	# none yet — a value entered by hand on the EIR (or later cleared deliberately) wins.
	if snap.get("reff_doc") and not doc.reff_doc:
		doc.reff_doc = snap["reff_doc"]


def latest_voucher_for_container(container: str | None, inspection_type: str) -> str | None:
	"""The most recent *submitted* bon that carries ``container``, or ``None``.

	EIR-In looks at Order Bongkar (unloading bon), EIR-Out at Order Muat (loading bon).
	Used to auto-reference the bon on a freshly created EIR draft so the operator never
	has to retype the same voucher. "Latest" = newest by creation among submitted bons.
	"""
	if not container:
		return None
	doctype = _voucher_doctype(inspection_type)
	parents = frappe.get_all(
		_VOUCHER_CHILD[doctype],
		filters={"container": container, "parenttype": doctype},
		pluck="parent",
	)
	if not parents:
		return None
	rows = frappe.get_all(
		doctype,
		filters={"name": ["in", list(set(parents))], "docstatus": 1},
		pluck="name",
		order_by="creation desc",
		limit=1,
	)
	return rows[0] if rows else None


def latest_eir_in(container: str | None) -> str | None:
	"""The newest *submitted* EIR-In for a container — the baseline an EIR-Out compares to."""
	if not container:
		return None
	return frappe.db.get_value(
		"Inspection",
		{"container": container, "docstatus": 1, "inspection_type": "EIR-In"},
		"name",
		order_by="creation desc",
	)


def provision_eir_out_for_order_muat(order_name: str) -> list:
	"""Submit-time hook for an Order Muat: create one DRAFT EIR-Out per container, each
	referencing the container's latest submitted EIR-In (the load-out baseline) and the
	row's container.

	Mirrors :func:`provision_eirs_for_order_bongkar` (EIR-In): the surveyor never types a
	container — the EIR-Out is born from the loading bon. The surveyor opens the draft from
	the EIR-Out worklist, verifies exterior / seals vs the referenced EIR-In, then submits.
	Idempotent per container (skips when an open EIR-Out draft already exists); best-effort
	per row — one failure is logged and never blocks the bon submit.
	"""
	rows = frappe.get_all(
		"Order Container Item",
		filters={"parent": order_name, "parenttype": "Order Muat"},
		fields=["container"],
	)
	created = []
	for row in rows:
		container = row.get("container")
		if not container:
			continue
		# Dedup: never open a second EIR-Out draft for a container (scoped to EIR-Out so an
		# unrelated EIR-In draft never blocks it).
		if frappe.db.exists(
			"Inspection",
			{"container": container, "docstatus": 0, "inspection_type": "EIR-Out"},
		):
			continue
		try:
			doc = frappe.new_doc("Inspection")
			doc.inspection_type = "EIR-Out"
			doc.container = container
			doc.inspector = frappe.session.user
			cdepot, ccargo = frappe.db.get_value("Container", container, ["depot", "last_cargo"]) or (None, None)
			doc.depot = cdepot
			doc.cargo = ccargo
			# Reference THIS Order Muat: truck / driver / driver phone / shipper / booking depot.
			_apply_voucher(doc, order_name)
			snap = fetch_voucher(order_name, "EIR-Out", container=container)
			doc.tank_status = snap.get("tank_status") or doc.tank_status
			doc.cargo = snap.get("cargo") or doc.cargo
			# Baseline EIR-In for the comparison panel.
			doc.reference_eir_in = latest_eir_in(container)
			doc.insert(ignore_permissions=True)  # system automation on bon submit
			created.append(doc.name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"auto EIR-Out for {container} on {order_name}")
	return created


def get_eir_out_reference(inspection) -> dict:
	"""Comparison payload for an EIR-Out: the referenced EIR-In's summary (date, tank
	status, remarks, damage findings + photos). Best-effort — sections come back ``None``
	when there is no baseline EIR-In.
	"""
	doc = inspection if hasattr(inspection, "doctype") else frappe.get_doc("Inspection", inspection)
	out = {"reference_eir_in": doc.get("reference_eir_in"), "eir_in": None}

	ref = doc.get("reference_eir_in")
	if ref:
		ein = frappe.db.get_value(
			"Inspection", ref,
			["name", "inspection_id", "eir_date", "tank_status", "remarks", "has_damage"],
			as_dict=True,
		)
		if ein:
			names = {
				r.item_code: r.item_name
				for r in frappe.get_all("Inspection Checklist Item", fields=["item_code", "item_name"])
			}
			photos_by_item: dict = {}
			for p in frappe.get_all(
				"Inspection Item Photo", filters={"parent": ref, "parenttype": "Inspection"},
				fields=["checklist_item", "photo"],
			):
				if p.photo:
					photos_by_item.setdefault(p.checklist_item, []).append(p.photo)
			damages = []
			for d in frappe.get_all(
				"Inspection Damage Entry", filters={"parent": ref, "parenttype": "Inspection"},
				fields=["checklist_item", "area", "component", "damage_type", "repair_code", "damage_description"],
				order_by="idx asc",
			):
				damages.append({
					"item": d.checklist_item,
					"item_name": names.get(d.checklist_item) or d.checklist_item,
					"area": d.area,
					"component": d.component,
					"damage_type": d.damage_type,
					"repair_code": d.repair_code,
					"damage_description": d.damage_description,
					"photos": list(photos_by_item.get(d.checklist_item, [])),
				})
			out["eir_in"] = {
				"name": ein.name,
				"inspection_id": ein.inspection_id,
				"eir_date": str(ein.eir_date) if ein.eir_date else None,
				"tank_status": ein.tank_status,
				"remarks": ein.remarks,
				"has_damage": ein.has_damage,
				"damages": damages,
				"photos": [u for lst in photos_by_item.values() for u in lst],
			}
	return out


def provision_eirs_for_order_bongkar(order_name: str) -> list:
	"""Submit-time hook for an Order Bongkar: create one DRAFT EIR-In per container and
	stamp the bon as each container's latest Order Bongkar voucher (surfaced in the depot
	/ Container lists).

	Each draft references this bon and pre-fills tank_status / cargo / truck / driver /
	shipper from its booking line, so the surveyor only fills the checklist. This is the
	ONLY way an EIR is born in the PWA flow — the operator no longer types a container to
	create one.

	Idempotent: a container that already has an open (draft) EIR is left untouched, so
	re-submitting the bon never duplicates. Best-effort per container — one failure is
	logged and never blocks the others (or the bon submit).
	"""
	containers = frappe.get_all(
		"Container Booking Item",
		filters={"parent": order_name, "parenttype": "Order Bongkar"},
		pluck="container",
	)
	created = []
	for container in containers:
		if not container:
			continue
		# Stamp the latest voucher on the container for the list views (cheap, idempotent).
		frappe.db.set_value(
			"Container", container, "last_order_bongkar", order_name, update_modified=False
		)
		# Dedup: never open a second EIR-In draft for a container (scoped to EIR-In so an
		# EIR-Out draft from the load-out flow never blocks it).
		if frappe.db.exists(
			"Inspection",
			{"container": container, "docstatus": 0, "inspection_type": "EIR-In"},
		):
			continue
		try:
			doc = frappe.new_doc("Inspection")
			doc.inspection_type = "EIR-In"
			doc.container = container
			doc.inspector = frappe.session.user
			cdepot, ccargo = frappe.db.get_value(
				"Container", container, ["depot", "last_cargo"]
			) or (None, None)
			doc.depot = cdepot
			doc.cargo = ccargo
			# Reference THIS bon: truck / driver / driver phone / shipper / booking depot.
			_apply_voucher(doc, order_name)
			snap = fetch_voucher(order_name, "EIR-In", container=container)
			doc.tank_status = snap.get("tank_status") or doc.tank_status
			doc.cargo = snap.get("cargo") or doc.cargo
			doc.insert(ignore_permissions=True)  # system automation on bon submit
			created.append(doc.name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"auto EIR for {container} on {order_name}")
	return created


def release_eirs_for_cancelled_order(order_name: str, inspection_type: str = "EIR-In") -> dict:
	"""Cancel-time counterpart of the provisioning above: unwind the draft EIRs that a
	now-cancelled bon created, so none is left pointing at a voided voucher.

	Without this a cancelled bon strands its EIRs: the draft still references it, and the
	replacement bon does not adopt them (provisioning dedups on "container already has a
	draft EIR-In"), so the tank's inspection is stuck for good.

	Per draft, in order:

    * a **replacement** submitted bon already carries the container → re-point at it, so
      the surveyor keeps working against the bon the tank actually arrived on;
    * else **never started** → delete. ``save_draft`` refuses to write before "Mulai", so
      an EIR with no ``work_started_on`` provably holds no work; it only existed because
      of this bon, exactly like the phantom containers a cancelled booking deletes;
    * else → keep the work and just drop the dangling link. The stamped truck / driver /
      shipper stay: they record the truck that really showed up, which the surveyor may
      still be relying on.

	Best-effort per draft — mirrors ``provision_eirs_for_order_bongkar``: one failure is
	logged and never blocks the cancel.
	"""
	drafts = frappe.get_all(
		"Inspection",
		filters={"referred_voucher": order_name, "docstatus": 0, "inspection_type": inspection_type},
		fields=["name", "container", "work_started_on"],
	)
	out = {"repointed": [], "deleted": [], "detached": []}
	for d in drafts:
		try:
			# The bon is already at docstatus 2 by the time on_cancel runs, so this can
			# never hand back the very bon being cancelled.
			replacement = latest_voucher_for_container(d.container, inspection_type)
			if replacement:
				doc = frappe.get_doc("Inspection", d.name)
				_apply_voucher(doc, replacement)
				doc.save(ignore_permissions=True)
				out["repointed"].append(d.name)
			elif not d.work_started_on:
				frappe.delete_doc("Inspection", d.name, ignore_permissions=True)
				out["deleted"].append(d.name)
			else:
				frappe.db.set_value("Inspection", d.name, "referred_voucher", None, update_modified=False)
				out["detached"].append(d.name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"release EIR {d.name} on {order_name}")
	return out


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
	order_muat: str | None = None,
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
	elif not name and order_muat:
		booking = frappe.db.get_value("Order Muat", order_muat, "booking")
		row = frappe.db.get_value(
			"Order Container Item",
			{"parent": order_muat, "parenttype": "Order Muat"},
			["container", "booking_code"], as_dict=True, order_by="idx asc",
		)
		if row:
			name, bc_name = row.container, row.booking_code
		if bc_name:
			direction = frappe.db.get_value("Booking Code", bc_name, "direction")

	if not name:
		frappe.throw(_("Provide a container number (or a booking_code / order_bongkar / order_muat)."))

	c = frappe.db.get_value(
		"Container", name,
		["name", "container_no", "serial_no", "manufacture_date", "capacity",
		 "tare_weight", "max_gross_weight", "last_test_date", "last_cargo", "ex_vessel",
		 "depot", "principal", "eir_in_date", "eir_out_date"],
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
		# EIR gate dates from the Container master (date-only for clean display). The PWA
		# header shows EIR-In Date here since last_test_date (periodic test) is rarely set.
		"eir_in_date": str(c.eir_in_date)[:10] if c.eir_in_date else None,
		"eir_out_date": str(c.eir_out_date)[:10] if c.eir_out_date else None,
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
		# A part with no real finding — Acceptable (or blank) damage AND No Action (or
		# blank) repair AND no remark — is the default condition and is not stored.
		is_acceptable = damage_code in (None, ACCEPTABLE_DAMAGE_CODE)
		is_no_action = repair_code in (None, NO_ACTION_REPAIR_CODE)
		if is_acceptable and is_no_action and not line_remarks:
			continue

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
	"""Map a flat ``[{item_code, photo}]`` payload to Inspection Item Photo rows.

	A row is kept whenever it carries a ``photo``. ``item_code`` is OPTIONAL: blank
	means "foto cepat" (bulk) not yet sorted into a section — stored with a null
	``checklist_item`` for the admin to assign later. Only a non-blank *unknown*
	code is rejected. (Rows with no photo are dropped.)
	"""
	rows = []
	for ph in photos:
		item_code = (ph.get("item_code") or "").strip()
		photo = (ph.get("photo") or "").strip()
		if not photo:
			continue
		if item_code and item_code not in items:
			frappe.throw(_("Unknown checklist item_code for photo: {0}").format(item_code))
		rows.append({"checklist_item": item_code or None, "photo": photo})
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
	reff_doc: str | None = None,
	create_cleaning_order=None,
	create_repair_order=None,
	lines=None,
	photos=None,
	exterior_condition=None,
	exterior_remark=None,
	seals_intact=None,
	seal_remark=None,
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
	doc.reff_doc = reff_doc  # optional reference doc; flows into auto-created Cleaning / M&R
	# Follow-up opt-outs (default checked via the doctype) — only overridden when supplied.
	if create_cleaning_order is not None:
		doc.create_cleaning_order = 1 if _as_bool(create_cleaning_order) else 0
	if create_repair_order is not None:
		doc.create_repair_order = 1 if _as_bool(create_repair_order) else 0
	if referred_voucher:
		_apply_voucher(doc, referred_voucher)  # overrides truck_no; sets driver / driver_phone / shipper
	doc.has_damage = 1 if has_damage else 0
	if order_ref:
		doc.order_doctype = order_doctype or "Order Bongkar"
		doc.order_ref = order_ref
	# EIR-Out verification fields (only meaningful for EIR-Out; harmless otherwise).
	if exterior_condition is not None:
		doc.exterior_condition = exterior_condition or None
	if exterior_remark is not None:
		doc.exterior_remark = exterior_remark or None
	if seals_intact is not None:
		doc.seals_intact = 1 if _as_bool(seals_intact) else 0
	if seal_remark is not None:
		doc.seal_remark = seal_remark or None
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


def _resolve_booking_code_for_eir(doc) -> str | None:
	"""The booking code behind this EIR's container, read from its referred bon's line.

	``prefill(container=…)`` can't know it (no bon in the args), so opening an EIR by
	container/name leaves ``booking_code`` blank. The draft DOES carry the bon
	(``referred_voucher``); its per-container line holds the booking code. EIR-In refers an
	Order Bongkar (its ``containers`` ARE Container Booking Item rows); EIR-Out an Order
	Muat (Order Container Item rows). Best-effort — never raises.
	"""
	voucher = doc.get("referred_voucher")
	if not (voucher and doc.container):
		return None
	child = {"Order Bongkar": "Container Booking Item", "Order Muat": "Order Container Item"}.get(
		doc.get("voucher_doctype")
	)
	if not child:
		return None
	return frappe.db.get_value(
		child,
		{"parent": voucher, "parenttype": doc.get("voucher_doctype"), "container": doc.container},
		"booking_code",
	)


def _draft_payload(doc, header: dict) -> dict:
	"""Merge a draft Inspection's saved state onto the master-derived ``header``.

	The tank fields stay sourced from the Container master (actual current data); the
	checklist lines, photos and user-entered fields come from the draft.
	"""
	header["inspection"] = doc.name
	# prefill() only fills booking_code when resolved from a bon; opening by container
	# leaves it blank, so recover it from the draft's referred bon for the PWA header.
	header["booking_code"] = _resolve_booking_code_for_eir(doc) or header.get("booking_code")
	header["inspection_id"] = doc.inspection_id or doc.name
	header["inspection_type"] = doc.inspection_type
	header["eir_date"] = doc.eir_date
	header["tank_status"] = doc.tank_status
	header["cargo"] = doc.cargo  # draft's chosen cargo (defaults to the master's last_cargo)
	# Follow-up opt-outs (default checked) so the PWA can pre-fill the toggles.
	header["create_cleaning_order"] = int(bool(doc.get("create_cleaning_order")))
	header["create_repair_order"] = int(bool(doc.get("create_repair_order")))
	# The draft's depot wins over the master's: it starts from the Container depot but is
	# overridden by the referred bon's booking depot (see _apply_voucher).
	header["depot"] = doc.depot or header.get("depot")
	header["reff_doc"] = doc.reff_doc
	header["referred_voucher"] = doc.referred_voucher
	header["voucher_doctype"] = doc.voucher_doctype
	header["truck_no"] = doc.truck_no
	header["driver"] = doc.driver
	header["driver_phone"] = doc.driver_phone
	header["shipper"] = doc.shipper
	header["emkl"] = doc.emkl
	header["doc_remarks"] = doc.remarks
	header["inspector_signature"] = doc.inspector_signature
	# Work-timing gate: the PWA locks the form until the operator presses "Mulai"
	# (work_started_on), and stamps work_ended_on / work_duration on submit.
	header["work_started_on"] = str(doc.work_started_on) if doc.work_started_on else None
	header["work_ended_on"] = str(doc.work_ended_on) if doc.work_ended_on else None
	header["work_duration"] = doc.work_duration or 0
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

	# Dedup the SAME inspection_type only — an open EIR-In draft must never be returned for
	# an EIR-Out request (and vice versa); the two flows are independent.
	existing = frappe.get_all(
		"Inspection",
		filters={"container": name, "docstatus": 0, "inspection_type": inspection_type},
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
		# Auto-reference the latest submitted bon for this container so the operator
		# never retypes it: EIR-In -> newest Order Bongkar, EIR-Out -> newest Order Muat.
		# Applied ONCE, only on first draft creation; re-opening keeps the saved state.
		# Defensive: a voucher hiccup must never block opening the EIR.
		try:
			voucher = latest_voucher_for_container(name, inspection_type)
			if voucher:
				_apply_voucher(doc, voucher)  # truck / driver / driver phone / shipper
				snap = fetch_voucher(voucher, inspection_type, container=name)
				# tank_status / cargo come from the bon line as editable defaults.
				doc.tank_status = snap.get("tank_status") or doc.tank_status
				doc.cargo = snap.get("cargo") or doc.cargo
		except Exception:
			frappe.log_error(title="EIR auto-voucher", message=frappe.get_traceback())
		# EIR-Out: stamp the EIR-In baseline for the comparison panel.
		if inspection_type == "EIR-Out":
			doc.reference_eir_in = latest_eir_in(name)
		doc.insert()  # NOT ignore_permissions — only EIR creators can open a draft.

	return _draft_payload(doc, header)


def open_eir_out(inspection: str) -> dict:
	"""Open a draft EIR-Out for editing (worklist → form) with its EIR-In comparison plus
	the saved EIR-Out verification fields."""
	payload = open_draft_by_name(inspection)
	doc = frappe.get_doc("Inspection", inspection)
	if doc.inspection_type != "EIR-Out":
		frappe.throw(_("{0} is not an EIR-Out.").format(inspection))
	payload["reference"] = get_eir_out_reference(doc)
	payload["exterior_condition"] = doc.get("exterior_condition")
	payload["exterior_remark"] = doc.get("exterior_remark")
	payload["seals_intact"] = int(bool(doc.get("seals_intact")))
	payload["seal_remark"] = doc.get("seal_remark")
	return payload


def start_eir(inspection: str) -> dict:
	"""Begin work on a draft EIR — stamps ``work_started_on`` (once) and unlocks editing.

	The PWA keeps the checklist read-only until this is called, so the elapsed time from
	Mulai → Submit measures how long the inspection actually took. Idempotent: a second
	call keeps the original start time. Permissions + branch are enforced (no bypass)."""
	if not inspection:
		frappe.throw(_("inspection is required."))
	doc = frappe.get_doc("Inspection", inspection)
	if doc.docstatus != 0:
		frappe.throw(_("EIR {0} is no longer a draft.").format(inspection))
	_guard_container_branch(doc.container)
	doc.check_permission("write")
	if not doc.work_started_on:
		# Stamp who started it too, so the PWA can scope the "next/prev EIR" navigator to
		# the EIRs this account is working (idempotent: keep the original starter).
		doc.db_set({"work_started_on": now_datetime(), "work_started_by": frappe.session.user})
	return {
		"success": True,
		"inspection": doc.name,
		"work_started_on": str(doc.work_started_on),
		"work_started_by": doc.work_started_by,
	}


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
	reff_doc: str | None = None,
	create_cleaning_order=None,
	create_repair_order=None,
	lines=None,
	photos=None,
	exterior_condition=None,
	exterior_remark=None,
	seals_intact=None,
	seal_remark=None,
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
	# Work-timing gate: editing is only allowed after the operator has pressed "Mulai"
	# (see ``start_eir``), so every saved EIR carries a real work-start timestamp.
	if not doc.work_started_on:
		frappe.throw(_("Tekan \"Mulai\" dulu sebelum mengisi EIR ini."))

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
	# Optional reference doc — only overwritten when sent (EIR-Out saves omit it), so it isn't cleared.
	if reff_doc is not None:
		doc.reff_doc = reff_doc
	doc.inspector_signature = signature
	# Follow-up opt-outs: only set when the caller sends a value (the PWA always does), so a
	# Desk-set choice is never silently overwritten by an omitted param.
	if create_cleaning_order is not None:
		doc.create_cleaning_order = 1 if _as_bool(create_cleaning_order) else 0
	if create_repair_order is not None:
		doc.create_repair_order = 1 if _as_bool(create_repair_order) else 0
	# The voucher owns truck_no / driver / driver_phone / shipper (read-only snapshot);
	# the legacy ``truck_no`` arg is ignored. No voucher -> these are cleared.
	#
	# Only re-resolved when it actually CHANGES. The PWA echoes back the voucher it was
	# handed (the field is read-only there), so re-validating an unchanged one is pure
	# overhead — and it was the first thing to blow up when a bon got cancelled
	# ("… is not submitted yet" on every auto-save). Note this alone does NOT make such
	# a draft savable: Frappe's own link check then raises CancelledLinkError. The fix
	# is to never leave a draft on a voided bon — see release_eirs_for_cancelled_order.
	if (referred_voucher or None) != (doc.referred_voucher or None):
		_apply_voucher(doc, referred_voucher)
	doc.has_damage = 1 if has_damage else 0
	doc.set("damage_log", damage_rows)
	doc.set("item_photos", photo_rows)
	# EIR-Out verification fields (only sent by the EIR-Out form; omitted = left untouched).
	if exterior_condition is not None:
		doc.exterior_condition = exterior_condition or None
	if exterior_remark is not None:
		doc.exterior_remark = exterior_remark or None
	if seals_intact is not None:
		doc.seals_intact = 1 if _as_bool(seals_intact) else 0
	if seal_remark is not None:
		doc.seal_remark = seal_remark or None

	if submit:
		# Stamp the end + elapsed work time (Mulai → Submit) before finalizing.
		doc.work_ended_on = now_datetime()
		if doc.work_started_on:
			doc.work_duration = max(0, int(time_diff_in_seconds(doc.work_ended_on, doc.work_started_on)))
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


def unsorted_photos(inspection: str) -> dict:
	"""Foto cepat (bulk) yang belum diberi section pada sebuah EIR.

	Untuk layar sortir PWA: kembalikan tiap baris ``item_photos`` tanpa
	``checklist_item`` sebagai ``{row, photo}`` (``row`` = nama child row, dipakai
	untuk ``assign_photo_section``). Branch-scoped.
	"""
	doc = frappe.get_doc("Inspection", inspection)
	_guard_container_branch(doc.container)
	photos = [
		{"row": p.name, "photo": p.photo}
		for p in doc.item_photos
		if not p.checklist_item
	]
	return {
		"inspection": doc.name,
		"inspection_id": doc.inspection_id or doc.name,
		"container_no": doc.container_no,
		"docstatus": doc.docstatus,
		"photos": photos,
	}


def assign_photo_section(inspection: str, row: str, item_code: str) -> dict:
	"""Assign a bulk photo to a checklist section — the admin "sortir" action.

	Sets ``checklist_item`` on one ``item_photos`` child row (identified by its child
	``name``, or falling back to a matching ``photo`` URL). ``area``/``item_name`` then
	fetch from the linked master. Works on a SUBMITTED EIR because those fields are
	``allow_on_submit``. Permissions + branch are enforced (no bypass).
	"""
	item_code = (item_code or "").strip()
	if not item_code:
		frappe.throw(_("item_code is required to assign a section."))
	if item_code not in _checklist_items():
		frappe.throw(_("Unknown checklist item_code: {0}").format(item_code))

	doc = frappe.get_doc("Inspection", inspection)
	_guard_container_branch(doc.container)

	target = None
	for p in doc.item_photos:
		if p.name == row or (not target and p.photo == row):
			target = p
			if p.name == row:
				break
	if not target:
		frappe.throw(_("Photo row {0} not found on EIR {1}.").format(row, inspection))

	target.checklist_item = item_code
	# Refresh the fetched columns immediately (fetch_from only runs on the parent save
	# path; set them so the return value is accurate even before reload).
	master = _checklist_items()[item_code]
	target.area = master.area
	target.item_name = master.item_name

	doc.save()  # NOT ignore_permissions; allow_on_submit lets this pass on a submitted doc.
	# Persist the recomputed flag explicitly: on a submitted doc `validate`'s write to a
	# parent field is only kept when the field is allow_on_submit; db_set guarantees it
	# regardless and keeps the in-memory value in sync.
	unsorted = 1 if any(not p.checklist_item for p in doc.item_photos) else 0
	doc.db_set("has_unsorted_photos", unsorted)
	return {
		"success": True,
		"inspection": doc.name,
		"row": target.name,
		"checklist_item": item_code,
		"area": target.area,
		"item_name": target.item_name,
		"has_unsorted_photos": unsorted,
	}


def list_my_eirs(user=None, search=None, start=0, page_length=10, docstatus=None) -> dict:
	"""The caller's own EIR inspections — newest first, searchable + paginated.

	Hard-scoped to ``owner == user`` (and EIR-In / EIR-Out) so a user only ever sees the
	EIRs they created. ``frappe.get_all`` is used deliberately (it ignores row-level
	permissions) — the owner filter is the security boundary. Search matches the container
	number or the EIR id; ``start`` / ``page_length`` paginate. Optional ``docstatus``
	(0 = drafts, 1 = submitted) narrows the list for the checklist landing's quick lists.
	"""
	user = user or frappe.session.user
	start = max(0, cint(start))
	page_length = min(max(1, cint(page_length or 10)), 50)

	filters = {"owner": user, "inspection_type": ["in", ["EIR-In", "EIR-Out"]]}
	if docstatus is not None and str(docstatus) != "":
		filters["docstatus"] = cint(docstatus)
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


def list_pending_eirs(search=None, start=0, page_length=20) -> dict:
	"""Open (draft) EIR inspections in the user's branch scope — the PWA EIR worklist.

	EIRs are auto-provisioned (one per container) when an Order Bongkar is submitted, so
	the surveyor works from this list instead of creating an EIR by hand. Branch-scoped by
	the Inspection's depot (empty user-branch = all depots). Newest first; searchable by
	container number / EIR id / referred voucher; paginated. ``frappe.get_all`` is used so
	a surveyor sees every pending EIR in their branch (not only the ones they own — the bon
	that created them is owned by whoever submitted it).
	"""
	start = max(0, cint(start))
	page_length = min(max(1, cint(page_length or 20)), 50)

	# EIR-In only — EIR-Out drafts have their own worklist (``list_pending_eir_out``).
	filters = {"docstatus": 0, "inspection_type": "EIR-In"}
	allowed = get_user_depots()
	if allowed is not None:
		if not allowed:
			return {"items": [], "total": 0, "start": start, "page_length": page_length}
		filters["depot"] = ["in", allowed]

	# Tolerate client quirks: an absent filter can arrive as the literal "undefined" /
	# "null" string (frappe-ui serialising an undefined param), which must NOT become a
	# LIKE "%undefined%" that hides every pending EIR. Mirrors yard.zone_tank_list.
	term = str(search).strip() if search is not None else ""
	if term.lower() in ("undefined", "null", "none"):
		term = ""
	or_filters = None
	if term:
		s = f"%{term}%"
		or_filters = [
			["container_no", "like", s],
			["inspection_id", "like", s],
			["referred_voucher", "like", s],
		]

	total = len(frappe.get_all(
		"Inspection", filters=filters, or_filters=or_filters, pluck="name", limit_page_length=0
	))
	items = frappe.get_all(
		"Inspection",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name", "inspection_id", "container", "container_no", "inspection_type",
			"tank_status", "referred_voucher", "voucher_doctype", "depot", "eir_date", "creation",
			# Empty = not started yet, set = in progress (stamped by ``start_eir``). Drives
			# the PWA worklist's belum / dikerjakan split; work_started_by scopes the
			# next/prev EIR navigator to the account that is working them.
			"work_started_on", "work_started_by",
		],
		order_by="creation desc",
		limit_start=start,
		limit_page_length=page_length,
	)
	return {"items": items, "total": total, "start": start, "page_length": page_length}


def list_unsorted_eirs(search=None, start=0, page_length=20) -> dict:
	"""EIRs (any status, In or Out) that still carry bulk "foto cepat" without a section —
	the admin's photo-sorting worklist. Branch-scoped by depot (empty user-branch = all);
	newest first; searchable by container no / EIR id. Uses ``frappe.get_all`` so the admin
	sees every unsorted EIR in their branch, not only ones they own.
	"""
	start = max(0, cint(start))
	page_length = min(max(1, cint(page_length or 20)), 50)

	filters = {"has_unsorted_photos": 1}
	allowed = get_user_depots()
	if allowed is not None:
		if not allowed:
			return {"items": [], "total": 0, "start": start, "page_length": page_length}
		filters["depot"] = ["in", allowed]

	term = str(search).strip() if search is not None else ""
	if term.lower() in ("undefined", "null", "none"):
		term = ""
	or_filters = None
	if term:
		s = f"%{term}%"
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
			"docstatus", "depot", "eir_date", "creation",
		],
		order_by="creation desc",
		limit_start=start,
		limit_page_length=page_length,
	)
	return {"items": items, "total": total, "start": start, "page_length": page_length}


def list_pending_eir_out(search=None, start=0, page_length=20) -> dict:
	"""Open (draft) EIR-Out inspections in the user's branch — the PWA EIR-Out worklist.

	Auto-provisioned (one per container) when an Order Muat is submitted
	(``provision_eir_out_for_order_muat``), so the surveyor works from this list instead of
	creating one by hand. Branch-scoped by the Inspection depot; newest first; searchable by
	container number / EIR id / referred Order Muat; paginated.
	"""
	start = max(0, cint(start))
	page_length = min(max(1, cint(page_length or 20)), 50)

	filters = {"docstatus": 0, "inspection_type": "EIR-Out"}
	allowed = get_user_depots()
	if allowed is not None:
		if not allowed:
			return {"items": [], "total": 0, "start": start, "page_length": page_length}
		filters["depot"] = ["in", allowed]

	term = str(search).strip() if search is not None else ""
	if term.lower() in ("undefined", "null", "none"):
		term = ""
	or_filters = None
	if term:
		s = f"%{term}%"
		or_filters = [
			["container_no", "like", s],
			["inspection_id", "like", s],
			["referred_voucher", "like", s],
		]

	total = len(frappe.get_all(
		"Inspection", filters=filters, or_filters=or_filters, pluck="name", limit_page_length=0
	))
	items = frappe.get_all(
		"Inspection",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name", "inspection_id", "container", "container_no", "tank_status",
			"referred_voucher", "depot", "eir_date", "creation",
			# See list_pending_eirs: empty = not started, set = in progress; work_started_by
			# scopes the next/prev EIR navigator to the account working them.
			"work_started_on", "work_started_by",
		],
		order_by="creation desc",
		limit_start=start,
		limit_page_length=page_length,
	)
	return {"items": items, "total": total, "start": start, "page_length": page_length}


def open_draft_by_name(inspection: str) -> dict:
	"""Open an existing draft EIR by name and return it with the master-derived header.

	The PWA worklist picks a pending (auto-created) EIR from ``list_pending_eirs`` and this
	loads its header + saved checklist state for editing. It NEVER creates — EIRs are
	provisioned from Order Bongkar, never typed by hand in the PWA.
	"""
	if not inspection:
		frappe.throw(_("inspection is required."))
	doc = frappe.get_doc("Inspection", inspection)
	if doc.inspection_type not in ("EIR-In", "EIR-Out"):
		frappe.throw(_("{0} is not an EIR.").format(inspection))
	if doc.docstatus != 0:
		frappe.throw(_("EIR {0} is no longer a draft.").format(inspection))
	_guard_container_branch(doc.container)
	header = prefill(container=doc.container)
	return _draft_payload(doc, header)


def view_eir(inspection: str) -> dict:
	"""Read-only view of ANY EIR (draft or submitted) for the PWA "Riwayat" detail.

	Unlike :func:`open_draft_by_name` (drafts only, for editing) this never throws on a
	submitted EIR — it returns a compact header + recorded damages for display + print.
	"""
	if not inspection:
		frappe.throw(_("inspection is required."))
	doc = frappe.get_doc("Inspection", inspection)
	if doc.inspection_type not in ("EIR-In", "EIR-Out"):
		frappe.throw(_("{0} is not an EIR.").format(inspection))
	_guard_container_branch(doc.container)
	names = {
		r.item_code: r.item_name
		for r in frappe.get_all("Inspection Checklist Item", fields=["item_code", "item_name"])
	}
	damages = [
		{
			"item": d.checklist_item,
			"item_name": names.get(d.checklist_item) or d.checklist_item,
			"damage_type": d.damage_type,
			"repair_code": d.repair_code,
			"damage_description": d.damage_description,
		}
		for d in doc.damage_log
		if (d.get("damage_type") or d.get("repair_code") or d.get("damage_description"))
	]
	return {
		"name": doc.name,
		"inspection_id": doc.inspection_id,
		"inspection_type": doc.inspection_type,
		"container": doc.container,
		"container_no": doc.container_no,
		"tank_status": doc.tank_status,
		"status": doc.status,
		"docstatus": doc.docstatus,
		"eir_date": str(doc.eir_date) if doc.eir_date else None,
		"depot": doc.depot,
		"reff_doc": doc.get("reff_doc"),
		"referred_voucher": doc.get("referred_voucher"),
		"truck_no": doc.get("truck_no"),
		"driver": doc.get("driver"),
		"driver_phone": doc.get("driver_phone"),
		"emkl": doc.get("emkl"),
		"shipper": doc.get("shipper"),
		"remarks": doc.get("remarks"),
		"damages": damages,
		"damage_count": len(damages),
	}


def request_revision(inspection: str, reason: str | None = None) -> dict:
	"""Operator asks Admin Ops to reopen a submitted EIR for edit/revision.

	A submitted EIR can't be edited in the PWA, so this raises a request instead of
	touching the record: it drops an audit comment on the EIR timeline and notifies Admin
	Ops (+ ops oversight) in the container's branch via a Notification Log. Reopening
	itself stays a human decision on the Desk side (``revert_to_draft``).
	"""
	from container_depot.operations import notify as _notify

	if not inspection:
		frappe.throw(_("inspection is required."))
	doc = frappe.get_doc("Inspection", inspection)
	if doc.inspection_type not in ("EIR-In", "EIR-Out"):
		frappe.throw(_("{0} is not an EIR.").format(inspection))
	if doc.docstatus != 1:
		frappe.throw(_("Hanya EIR yang sudah selesai (submitted) yang bisa diajukan revisi."))
	_guard_container_branch(doc.container)

	reason = (reason or "").strip()
	user = frappe.session.user
	note = _("Permintaan revisi EIR oleh {0}").format(user)
	if reason:
		note += ": " + reason
	# Audit trail on the EIR timeline (visible in Desk). Best-effort — the notification
	# is what matters, so a comment-permission hiccup must not fail the request.
	try:
		doc.add_comment("Comment", note)
	except Exception:
		frappe.log_error(title="EIR revision comment", message=frappe.get_traceback())

	eir_id = doc.inspection_id or doc.name
	subject = _("Minta revisi EIR {0} • {1} • oleh {2}").format(
		eir_id, doc.container_no or doc.container, user
	)
	if reason:
		subject += f" — {reason}"
	sent = _notify.notify(
		doctype="Inspection",
		name=doc.name,
		subject=subject,
		branch=_notify._depot_branch(doc.depot) if doc.get("depot") else None,
		roles={_notify.PWA_ROLE, "Admin Ops", "Ops Supervisor"},
		notification_type="Alert",
	)
	return {"success": True, "notified": sent, "inspection": doc.name}


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
