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
from frappe.utils import cint, flt, getdate, now_datetime, time_diff_in_seconds, today

from container_depot.container_depot.container_activity import log_doc_note
from container_depot.container_depot.exceptions import AlreadySettled
from container_depot.container_depot.worklist import priority_date, sort_by_priority
from container_depot.container_depot.user_branch import assert_in_user_branch, get_user_depots

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
	# Master data is stored once, in one language; the PWA reads it in the operator's
	# (depot_lang.py). Translated here, at output, so the stored value never changes —
	# the client posts back only item_code / codes / fitting_item, never these words.
	for c in checklist:
		c["area"], c["item_name"] = _(c["area"]), _(c["item_name"])
	damage_codes = frappe.get_all(
		"Inspection Damage Code",
		filters={"is_active": 1},
		fields=["name as code", "description"],
		order_by="code asc",
	)
	for d in damage_codes:
		d["description"] = _(d["description"])
	repair_codes = frappe.get_all(
		"Inspection Repair Code",
		filters={"is_active": 1},
		fields=["name as code", "description"],
		order_by="code asc",
	)
	for r in repair_codes:
		r["description"] = _(r["description"])
	# Kelengkapan tank (kotak isian pada form EIR cetak). Bukan checklist kerusakan —
	# lihat ``eir_fitting_data``; the PWA renders one input per row, grouped by compartment.
	fittings = frappe.get_all(
		"Inspection Fitting Item",
		filters={"is_active": 1},
		fields=[
			"name as fitting_item",
			"compartment",
			"printed_no",
			"item_label",
			"slot_label",
			"value_type",
			"options",
			"uom",
			"sequence",
		],
		order_by="sequence asc",
	)
	for f in fittings:
		f["options"] = [o for o in (f.get("options") or "").split("\n") if o.strip()]
		# `options` stay raw: the picked one is posted back and stored as the value.
		f["option_labels"] = {o: _(o) for o in f["options"]}
		for k in ("compartment", "item_label", "slot_label"):
			f[k] = _(f[k])
	# Active cargos for the EIR's "set last cargo" picker (name == cargo_name).
	cargos = frappe.get_all("Cargo", filters={"is_active": 1}, pluck="name", order_by="name asc")
	# Pilihan Tipe / Ukuran untuk kolom Data Tank yang bisa diisi dari EIR — dibaca dari
	# doctype Container supaya menambah opsi di sana cukup sekali, tidak perlu menyalin
	# daftarnya ke PWA.
	meta = frappe.get_meta("Container")
	tank_options = {
		f: [o for o in (meta.get_field(f).options or "").split("\n") if o]
		for f in ("container_type", "equipment_type", "size")
	}
	return {
		"checklist": checklist,
		"damage_codes": damage_codes,
		"repair_codes": repair_codes,
		"fittings": fittings,
		"cargos": cargos,
		"tank_options": tank_options,
	}


def component_label(component: str | None) -> str | None:
	"""A stored component ("1. Front Top Rail") in the reader's language: the printed-number
	prefix kept, the part name translated. Display only — the stored text never changes."""
	if not component:
		return component
	no, sep, rest = component.partition(". ")
	return f"{no}. {_(rest)}" if sep else _(component)


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


def _voucher_depot(doctype: str, voucher: str | None, container: str | None = None) -> str | None:
	"""The depot behind a bon: ``voucher.booking`` -> the booking's answer for THIS tank.

	An EIR created from a bon should record the depot the tank is being handled at per that
	order, not necessarily the Container master's current depot.

	The booking's own row is asked first. An outbound booking may collect from two depots of
	one branch, and then its header carries no depot at all — reading the header alone would
	leave every EIR on such a booking without one.
	"""
	if not voucher:
		return None
	booking = frappe.db.get_value(doctype, voucher, "booking")
	if not booking:
		return None
	if container:
		row_depot = frappe.db.get_value(
			"Container Booking Item",
			{"parent": booking, "parenttype": "Container Booking", "container": container},
			"depot",
		)
		if row_depot:
			return row_depot
	return frappe.db.get_value("Container Booking", booking, "depot")


def _voucher_reff_doc(doctype: str, voucher: str | None) -> str | None:
	"""The reference doc carried by a bon's Container Booking (``voucher.booking`` ->
	``Container Booking.reff_doc``). This is what makes a Reff Doc entered on the booking
	reach the EIR: Booking -> bon -> EIR.

	And it stops there. The Cleaning Order / M&R the EIR spawns are ordered on the owner's
	OWN paperwork — an instruction number that has nothing to do with the paper the tank
	arrived on — so they are left blank for whoever files them to type (see
	``eir_followups``). Each of those numbers is mirrored onto the tank master in its own
	field, never merged with this one (see ``last_orders``).
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
	from the booking line. ``emkl`` and ``shipper`` are the bon header. truck/driver/phone are stored
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
		"emkl": None,
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
	snap["emkl"], snap["shipper"] = frappe.db.get_value(doctype, voucher, ["emkl", "shipper"])
	snap["depot"] = _voucher_depot(doctype, voucher, container)
	snap["reff_doc"] = _voucher_reff_doc(doctype, voucher)
	detail = _voucher_detail(doctype, voucher, container)
	snap["truck_no"] = detail.get("truck_plate")
	snap["driver"] = detail.get("driver")
	snap["driver_phone"] = detail.get("driver_phone")
	snap["tank_status"] = _CONDITION_TO_TANK_STATUS.get((detail.get("condition") or "").strip().upper())
	snap["cargo"] = detail.get("cargo")
	return snap


# The shipment detail an EIR copies off its bon — read-only on the EIR, kept in step with the
# booking line wherever it is corrected (``order_generation.refresh_bon_followers``).
_SNAPSHOT_FIELDS = ("truck_no", "driver", "driver_phone", "emkl", "shipper")


def _apply_voucher(doc, referred_voucher: str | None) -> None:
	"""Stamp the read-only shipment snapshot from ``referred_voucher`` onto an Inspection
	(or clear it when no voucher). The voucher doctype follows the inspection type."""
	snap = fetch_voucher(referred_voucher, doc.inspection_type, container=doc.container)
	doc.voucher_doctype = snap["voucher_doctype"]
	doc.referred_voucher = snap["referred_voucher"]
	doc.truck_no = snap["truck_no"]
	doc.driver = snap["driver"]
	doc.driver_phone = snap["driver_phone"]
	doc.emkl = snap["emkl"]
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


def provision_eir_out_for_survey(survey_tank: str) -> str | None:
	"""Tie the tank's EIR-Out to its survey row the moment the row is CLOSED.

	**Since 2026-10-02 the EIR-Out is born with the booking** (:func:`provision_eir_out_for_booking`),
	so closing a survey normally finds that draft and claims it rather than raising one. A
	survey finished after the tank already left (switch "Wajibkan Semua Order" OFF) points at
	the EIR-Out it left on. Raising a fresh one is now only the fallback for a booking whose
	provisioning never ran. What follows is the original reasoning, still true of the draft:

	``survey_tank`` is a ``Survey Order Tank`` row name — one tank on one day's schedule. This
	is where an EIR-Out is born. It used to be born at the loading bon (Order Muat) instead,
	and that was too late in the day to be useful: the bon is cut when the truck is effectively
	already there, so the one inspection standing between a tank and the gate was only handed
	to a surveyor at the last minute. The survey is the moment somebody has actually looked the
	tank over, which is the moment the outbound record should start.

	**The draft is deliberately born WITHOUT a bon.** No Order Muat exists yet — that is the
	whole point of moving this earlier — so ``referred_voucher`` stays empty and the truck /
	driver / EMKL boxes stay blank until the bon is cut and adopts it
	(:func:`attach_order_muat_to_eirs`). Until then the EIR-Out can be filled in but NOT
	submitted; ``Inspection.before_submit`` refuses it, because an EIR-Out with no bon behind it
	would let a tank through the gate on no paperwork at all.

	(A bon that somehow already exists for this tank IS picked up straight away — a yard that
	worked out of order should not be punished with a document it then has to re-link by hand.)

	Idempotent: returns the existing draft, claiming it for this survey row when it is unclaimed.
	Returns the EIR-Out's name, or ``None`` when there is nothing to raise one for.
	"""
	row = frappe.db.get_value(
		"Survey Order Tank", survey_tank, ["name", "parent", "container", "depot"], as_dict=True
	)
	if not row or not row.container:
		return None
	container = row.container

	# Dedup, in the order the two questions actually differ. First: has this very survey row
	# already raised one (including a SUBMITTED one — a reopened-then-reclosed survey must not
	# raise a second EIR for a tank that has already been through the gate)?
	mine = frappe.db.get_value(
		"Inspection", {"survey_tank": survey_tank, "docstatus": ["!=", 2]}, "name"
	)
	if mine:
		return mine
	# Second: is there an unrelated open EIR-Out draft for this tank? Adopt it rather than
	# opening a rival — the PWA fetches THE single draft for a container, and two would hand the
	# surveyor a coin flip.
	existing = frappe.db.get_value(
		"Inspection",
		{"container": container, "docstatus": 0, "inspection_type": "EIR-Out"},
		"name",
	)
	if existing:
		frappe.db.set_value(
			"Inspection", existing,
			{"survey_tank": survey_tank, "survey_order": row.parent},
			update_modified=False,
		)
		return existing

	booking = frappe.db.get_value("Survey Order", row.parent, "booking")
	left_on = booking and frappe.db.get_value(
		"Inspection",
		{"container": container, "container_booking": booking, "inspection_type": "EIR-Out", "docstatus": 1},
		"name",
	)
	if left_on:
		return left_on
	return _new_eir_out(container, row.depot, booking, survey_tank=survey_tank, survey_order=row.parent)


def _new_eir_out(container: str, depot: str | None, booking: str | None, **links) -> str:
	"""Insert one draft EIR-Out. Born from the Tank Out booking
	(:func:`provision_eir_out_for_booking`); a closed survey only falls back to it
	(:func:`provision_eir_out_for_survey`). ``links`` = the fields that say which one."""
	eir = frappe.new_doc("Inspection")
	eir.inspection_type = "EIR-Out"
	eir.container = container
	eir.inspector = frappe.session.user
	cdepot, ccargo = frappe.db.get_value("Container", container, ["depot", "last_cargo"]) or (None, None)
	eir.depot = depot or cdepot
	eir.cargo = ccargo
	eir.update(links)
	# Baseline EIR-In for the comparison panel.
	eir.reference_eir_in = latest_eir_in(container)
	# Only if the yard ran out of order and the bon is already out; normally None.
	voucher = latest_voucher_for_container(container, "EIR-Out")
	if voucher:
		_apply_voucher(eir, voucher)
		snap = fetch_voucher(voucher, "EIR-Out", container=container)
		eir.tank_status = snap.get("tank_status") or eir.tank_status
		eir.cargo = snap.get("cargo") or eir.cargo
	else:
		eir.update(booking_item_party(booking, container))
	eir.insert(ignore_permissions=True)  # system automation (survey close / booking save)
	return eir.name


def provision_eir_out_for_booking(booking_name: str, withdraw_draft: bool = False) -> dict:
	"""Satu draft EIR-Out per tank, langsung dari booking Tank Out — dengan atau tanpa survey.

	Sejak 2026-10-02 (permintaan user) EIR-Out lahir bersama Survey Order, bukan menunggu
	survey selesai: survey yang tidak dikerjakan tidak boleh lagi membuat tank tidak punya
	EIR-Out sama sekali. Survey yang ditutup belakangan memakai EIR-Out ini
	(:func:`provision_eir_out_for_survey`); kapan ia boleh disubmit diputuskan
	``Inspection.before_submit`` + saklar "Wajibkan Semua Order".

	Lahir saat booking di-Confirm (submit), bukan dari draft (user, 2026-10-08): draft masih bisa
	batal. Simpan draft tidak menyentuh apa pun — EIR-Out yang terbit dengan aturan lama tetap —
	dan ``withdraw_draft`` (Kembali ke Draft) menarik yang diterbitkan Confirm.

	Dipanggil tiap booking disimpan (juga draft, cancel dan void), jadi total dan idempoten:

	* booking hidup → tank yang belum punya EIR-Out dari booking ini dibuatkan (draft EIR-Out
	  terbuka yang sudah ada untuk tank itu diadopsi, bukan disaingi). "Punya" = EIR-Out yang
	  distempel booking ini, lahir dari survey-nya, atau menempel di bon muat-nya — jadi tank
	  yang sudah keluar lewat jalur lama tidak dibuatkan EIR-Out kedua. Tank berstatus
	  Gate_Out juga dilewati: ia sudah pergi;
	* tank yang keluar dari booking, atau booking di-void → draft milik booking ini ditarik:
	  yang belum disentuh (belum "Mulai", belum ada bon) dihapus, yang sudah diisi dibiarkan
	  dengan catatan. Draft yang sudah diklaim survey (``survey_tank``) diurus jadwalnya
	  (``tank_survey.close_survey_order_with_booking``).

	Penandanya ``Inspection.container_booking``, distempel saat lahir; ``stamp_container_booking``
	mempertahankannya selama EIR belum punya bon. EIR-Out ini boleh disubmit sebelum atau sesudah
	bon muat terbit — bon itulah yang mengeluarkan tank (``gate.depart_bon``) dan mengadopsinya.
	"""
	b = frappe.db.get_value(
		"Container Booking", booking_name,
		["name", "direction", "use_survey", "booking_status", "docstatus"], as_dict=True,
	)
	if not b or b.direction != "Tank Out":
		return {"created": [], "withdrawn": []}
	draft = cint(b.docstatus) == 0 and b.booking_status != "Cancelled"
	if draft and not withdraw_draft:
		return {"created": [], "withdrawn": []}
	live = not draft and b.booking_status != "Cancelled" and cint(b.docstatus) != 2
	items = frappe.get_all(
		"Container Booking Item",
		filters={"parent": b.name, "parenttype": "Container Booking"},
		fields=["container", "depot"], order_by="idx asc",
	)
	# A LADEN tank taken without an EIR gets none: its Order Muat is its departure (no_eir.py).
	# A draft raised before the switch went off is withdrawn below like any other the booking
	# no longer asks for.
	from container_depot.container_depot.no_eir import no_eir_containers

	skip = no_eir_containers(b.name)
	wanted = {r.container: r.depot for r in items if r.container and r.container not in skip} if live else {}
	out = {"created": [], "withdrawn": []}

	mine = frappe.get_all(
		"Inspection",
		filters={"container_booking": b.name, "inspection_type": "EIR-Out", "docstatus": ["!=", 2]},
		fields=["name", "container", "docstatus", "work_started_on", "referred_voucher", "survey_tank"],
	)
	have = _eir_outs_of_booking(b.name)
	for e in mine:
		if e.container in wanted:
			continue
		if e.docstatus != 0 or e.survey_tank:
			continue
		try:
			if not e.work_started_on and not e.referred_voucher:
				frappe.delete_doc("Inspection", e.name, ignore_permissions=True)
			else:
				log_doc_note("Inspection", e.name, _(
					"Booking {0} tidak lagi meminta EIR-Out ini — isian dipertahankan."
				).format(b.name))
			out["withdrawn"].append(e.name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"withdraw EIR-Out {e.name} of {b.name}")

	gone = set(
		frappe.get_all(
			"Container", filters={"name": ["in", list(wanted) or [""]], "status": "Gate_Out"}, pluck="name"
		)
	)
	for container, depot in wanted.items():
		if container in have or container in gone:
			continue
		try:
			existing = frappe.db.get_value(
				"Inspection",
				{"container": container, "docstatus": 0, "inspection_type": "EIR-Out"},
				["name", "container_booking"],
				as_dict=True,
			)
			if existing and existing.container_booking not in (None, "", b.name) and _booking_live(
				existing.container_booking
			):
				# Another live booking's EIR-Out: not ours to take, and a rival draft would hand
				# the PWA two for one tank. This booking gets its own once that one is settled.
				continue
			if existing:
				frappe.db.set_value("Inspection", existing.name, "container_booking", b.name, update_modified=False)
				out["created"].append(existing.name)
			else:
				out["created"].append(_new_eir_out(container, depot, b.name, container_booking=b.name))
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"provision EIR-Out for {container} on {b.name}")
	return out


def _booking_live(booking: str) -> bool:
	row = frappe.db.get_value("Container Booking", booking, ["booking_status", "docstatus"], as_dict=True)
	return bool(row) and row.booking_status != "Cancelled" and cint(row.docstatus) != 2


def _eir_outs_of_booking(booking: str) -> set:
	"""Tanks that already have a live EIR-Out for this booking, whichever way it was born:
	stamped by the booking, raised by its survey, or carried by its bon muat."""
	surveys = frappe.get_all("Survey Order", filters={"booking": booking}, pluck="name")
	bons = frappe.get_all("Order Muat", filters={"booking": booking, "docstatus": ["!=", 2]}, pluck="name")
	have = set()
	for field, values in (("container_booking", [booking]), ("survey_order", surveys), ("referred_voucher", bons)):
		if values:
			have.update(frappe.get_all(
				"Inspection",
				filters={field: ["in", values], "inspection_type": "EIR-Out", "docstatus": ["!=", 2]},
				pluck="container",
			))
	return have


def booking_party_for_eir_out(survey_order: str, container: str) -> dict:
	""":func:`booking_item_party` for a survey-born EIR-Out (kept for patch v1_15)."""
	return booking_item_party(frappe.db.get_value("Survey Order", survey_order, "booking"), container)


def booking_item_party(booking: str | None, container: str) -> dict:
	"""EMKL / shipper / truck / driver for an EIR-Out that has no bon yet, read from the tank's
	row on its Container Booking.

	The EIR-Out is raised before the Order Muat exists, so without this the printed EIR says
	"Received by —" until the bon is cut. The booking row already names the EMKL; the bon, once
	submitted, overwrites all of it via :func:`_apply_voucher`.
	"""
	if not booking:
		return {}
	item = frappe.db.get_value(
		"Container Booking Item",
		{"parent": booking, "parenttype": "Container Booking", "container": container},
		["emkl", "shipper", "truck_plate", "driver", "driver_phone"],
		as_dict=True,
	)
	if not item:
		return {}
	return {
		"emkl": item.emkl,
		"shipper": item.shipper,
		"truck_no": item.truck_plate,
		"driver": item.driver,
		"driver_phone": item.driver_phone,
	}


def attach_order_muat_to_eirs(order_name: str) -> dict:
	"""Submit-time hook for an Order Muat: point each tank's EXISTING EIR-Out draft at this
	bon and stamp the shipment detail onto it. **Creates nothing.**

	The EIR-Out is raised by the position survey now (:func:`provision_eir_out_for_survey`),
	so by the time a bon is cut the document is already sitting in the surveyor's worklist,
	half filled in. What the bon adds is the half only it knows — truck, driver, driver phone,
	EMKL, reff doc — and the reference that ties the EIR to its departure. So everything typed
	on the Generate Bon screen lands straight on the EIR already raised, instead of on a second
	one raised beside it. An EIR-Out finished before the bon is adopted the same way.

	A tank with NO open EIR-Out draft is reported back rather than given one. That is the
	deliberate consequence of a single birthplace: no survey, no EIR-Out, and inventing one
	here would put the old duplicate right back. ``missing`` is returned for callers and
	tests to read; the bon does NOT put it on screen (see ``OrderMuat._attach_eir_out``) —
	closing the survey raises the EIR and the next pass of this function adopts it, and the
	gate is what refuses a tank that never got one.

	Best-effort per row — one failure is logged and never blocks the bon submit. Returns
	``{"attached": [...], "missing": [container_no, ...]}``.
	"""
	rows = frappe.get_all(
		"Order Container Item",
		filters={"parent": order_name, "parenttype": "Order Muat"},
		fields=["container", "container_no"],
	)
	booking = frappe.db.get_value("Order Muat", order_name, "booking")
	out = {"attached": [], "missing": []}
	for row in rows:
		container = row.get("container")
		if not container:
			continue
		draft = frappe.db.get_value(
			"Inspection",
			{"container": container, "docstatus": 0, "inspection_type": "EIR-Out"},
			"name",
		)
		if not draft:
			# Already submitted against this very bon? Then there is nothing missing — this is
			# a re-submit of a bon that was reverted to draft (order_generation), and the EIR
			# it stamped is done.
			if frappe.db.exists(
				"Inspection",
				{"container": container, "inspection_type": "EIR-Out", "referred_voucher": order_name},
			):
				continue
			# Finished BEFORE the bon (the bon is the gate, the EIR-Out may come first): it is
			# this booking's, still with no bon, and takes the bon's detail like a draft would.
			done = booking and frappe.db.get_value(
				"Inspection",
				{
					"container": container, "inspection_type": "EIR-Out", "docstatus": 1,
					"container_booking": booking, "referred_voucher": ["is", "not set"],
				},
				"name",
			)
			if not done:
				out["missing"].append(row.get("container_no") or container)
				continue
			try:
				snap = fetch_voucher(order_name, "EIR-Out", container=container)
				update = {k: snap[k] for k in ("voucher_doctype", "referred_voucher", *_SNAPSHOT_FIELDS)}
				if not frappe.db.get_value("Inspection", done, "reff_doc") and snap.get("reff_doc"):
					update["reff_doc"] = snap["reff_doc"]
				frappe.db.set_value("Inspection", done, update)
				out["attached"].append(done)
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"attach EIR-Out for {container} on {order_name}")
			continue
		try:
			doc = frappe.get_doc("Inspection", draft)
			_apply_voucher(doc, order_name)
			snap = fetch_voucher(order_name, "EIR-Out", container=container)
			# Defaults, not overwrites: the surveyor has had this draft open since the survey
			# closed, and a condition they corrected on the tank in front of them beats the
			# condition the booking was written with days ago.
			doc.tank_status = doc.tank_status or snap.get("tank_status")
			doc.cargo = doc.cargo or snap.get("cargo")
			doc.save(ignore_permissions=True)  # system automation on bon submit
			out["attached"].append(draft)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"attach EIR-Out for {container} on {order_name}")
	return out


def get_eir_out_reference(inspection) -> dict:
	"""Comparison payload for an EIR-Out: the referenced EIR-In's summary (date, tank
	status, remarks, damage findings + photos, kelengkapan tank). Best-effort — sections
	come back ``None`` when there is no baseline EIR-In.

	The kelengkapan half answers a different question from the damage half, which is why
	both are here: the checklist says what was BROKEN on the way in, the fittings say what
	the tank CARRIED. A strap that arrived and is not on the tank now is neither a damage
	nor an empty box — it only shows up as a difference against this list. The same numbers
	also reach the form per-box (``_fitting_payload``'s ``baseline``); this is the whole
	sheet in one place, for a surveyor reading before touching anything.
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
			# `{photo, caption}` and not a bare url: the caption is the surveyor's own words
			# about THIS frame, and the EIR-Out panel is read to decide what the tank arrived
			# with — a picture shown without them says less than the surveyor recorded.
			photos_by_item: dict = {}
			for table in ("Inspection Damage Photo", "Inspection Item Photo"):
				for p in frappe.get_all(
					table, filters={"parent": ref, "parenttype": "Inspection"},
					fields=["checklist_item", "photo", "caption"],
				):
					if p.photo:
						photos_by_item.setdefault(p.checklist_item, []).append(
							{"photo": p.photo, "caption": p.caption or ""}
						)
			damages = []
			for d in frappe.get_all(
				"Inspection Damage Entry", filters={"parent": ref, "parenttype": "Inspection"},
				fields=["checklist_item", "area", "component", "damage_type", "repair_code", "damage_description"],
				order_by="idx asc",
			):
				# Real findings only — a part the EIR-In surveyor checked and found
				# acceptable is stored (see ``_build_damage_rows``) but is not something
				# for the EIR-Out comparison panel to raise.
				if not is_real_finding(d.damage_type, d.repair_code):
					continue
				damages.append({
					"item": d.checklist_item,
					"item_name": _(names.get(d.checklist_item) or d.checklist_item),
					"area": _(d.area),
					"component": component_label(d.component),
					"damage_type": d.damage_type,
					"repair_code": d.repair_code,
					"damage_description": d.damage_description,
					"photos": list(photos_by_item.get(d.checklist_item, [])),
				})
			# Labels off the ROW, not the master: they were stamped when the EIR-In was
			# written (``_build_fitting_rows``), so a slot renamed since then still reads
			# back the way the surveyor saw it. Blank values never reach the table at all —
			# an unanswered box is not a recorded zero.
			fittings = [
				{
					"compartment": _(r.compartment),
					"item_label": _(r.item_label),
					"slot_label": _(r.slot_label),
					"uom": r.uom,
					"value": r.value,
				}
				for r in frappe.get_all(
					"Inspection Fitting",
					filters={"parent": ref, "parenttype": "Inspection"},
					fields=["compartment", "item_label", "slot_label", "uom", "value"],
					order_by="idx asc",
				)
			]
			out["eir_in"] = {
				"name": ein.name,
				"inspection_id": ein.inspection_id,
				"eir_date": str(ein.eir_date) if ein.eir_date else None,
				"tank_status": ein.tank_status,
				"remarks": ein.remarks,
				"has_damage": ein.has_damage,
				"damages": damages,
				"fittings": fittings,
				"photos": [row for lst in photos_by_item.values() for row in lst],
			}
	return out


def _already_provisioned(container: str, inspection_type: str, voucher: str) -> bool:
	"""True when this bon has ALREADY raised an EIR of this type for this container.

	A bon can be submitted more than once: ``order_generation.revert_order_to_draft`` sends a
	submitted Order Bongkar / Order Muat back to an editable draft, and re-submitting it runs
	the provisioning again. The "is there an open draft?" test each caller does first cannot
	see the EIR from the first submit once the surveyor has SUBMITTED it — so a second, empty
	EIR was opened for the same arrival, and the PWA (which fetches the single draft for a
	container) handed the surveyor that duplicate to fill in.

	Keyed on the voucher rather than on time: a tank that genuinely comes back on a NEW bon
	must still get its own EIR. Cancelled (docstatus 2) EIRs do not count — a voided EIR is
	work that no longer exists, and the bon may legitimately raise a replacement.
	"""
	return bool(frappe.db.exists("Inspection", {
		"container": container,
		"inspection_type": inspection_type,
		"referred_voucher": voucher,
		"docstatus": ["!=", 2],
	}))


def provision_eirs_for_order_bongkar(order_name: str) -> list:
	"""Submit-time hook for an Order Bongkar: create one DRAFT EIR-In per container and
	stamp the bon as each container's latest Order Bongkar voucher (surfaced in the depot
	/ Container lists).

	Each draft references this bon and pre-fills tank_status / cargo / truck / driver /
	EMKL from its booking line, so the surveyor only fills the checklist. This is the
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
	from container_depot.container_depot.no_eir import no_eir_containers

	skip = no_eir_containers(order_name, "Order Bongkar")
	created = []
	for container in containers:
		if not container:
			continue
		# Stamp the latest voucher on the container for the list views (cheap, idempotent).
		frappe.db.set_value(
			"Container", container, "last_order_bongkar", order_name, update_modified=False
		)
		# A LADEN tank taken without an EIR: no EIR-In, it is Available on arrival (no_eir.py).
		if container in skip:
			continue
		# Dedup: never open a second EIR-In draft for a container (scoped to EIR-In so an
		# EIR-Out draft from the load-out flow never blocks it).
		if frappe.db.exists(
			"Inspection",
			{"container": container, "docstatus": 0, "inspection_type": "EIR-In"},
		):
			continue
		# ... nor a second one for a bon that has been through submit before.
		if _already_provisioned(container, "EIR-In", order_name):
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
			# Reference THIS bon: truck / driver / driver phone / EMKL / shipper / booking depot.
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
      EMKL stay: they record the truck that really showed up, which the surveyor may
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
			# An EIR-Out is NEVER this bon's to delete. The bon only ever adopted it
			# (``attach_order_muat_to_eirs``); the document belongs to the survey that closed
			# or to the no-survey booking that raised it, and deleting it would leave the tank
			# with no EIR-Out at all — nothing raises a second one. It is detached instead,
			# and the next bon for the same tank adopts it again.
			elif not d.work_started_on and inspection_type != "EIR-Out":
				frappe.delete_doc("Inspection", d.name, ignore_permissions=True)
				out["deleted"].append(d.name)
			else:
				frappe.db.set_value("Inspection", d.name, "referred_voucher", None, update_modified=False)
				# Raw write (update_modified=False on purpose), so nothing else records it —
				# say on the EIR's own timeline why its bon link vanished.
				log_doc_note("Inspection", d.name, _(
					"Bon {0} dibatalkan — link bon dilepas, isian EIR dipertahankan."
				).format(order_name))
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
		["name", "container_no", "container_type", "equipment_type", "size", "serial_no", "manufacture_date",
		 "capacity", "tare_weight", "max_gross_weight", "last_test_date", "last_cargo",
		 "ex_vessel", "depot", "principal"],
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
		"container_type": c.container_type,
		"equipment_type": c.equipment_type,
		"size": c.size,
		"serial_no": c.serial_no,
		"manufacture_date": c.manufacture_date,
		"capacity": c.capacity,
		"tare_weight": c.tare_weight,
		"max_gross_weight": c.max_gross_weight,
		"last_test_date": c.last_test_date,
		# The latest EIR-In's own date, read off the EIR itself: the master no longer holds
		# it (its in_date is the bon's day, visit_dates). The PWA header shows it.
		"eir_in_date": frappe.db.get_value(
			"Inspection",
			{"container": c.name, "inspection_type": "EIR-In", "docstatus": 1},
			"eir_date", order_by="eir_date desc, creation desc",
		),
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

	Blank ("Acceptable") lines are skipped unless the operator opened the card (``added``).
	``severity`` is defaulted server-side (Minor); ``damage_description`` carries the
	operator's own remark and nothing else — an untouched finding has none. Returns
	``(rows, has_damage)`` — has_damage true for any real damage code (not "v").
	"""
	rows, has_damage = [], False
	for ln in lines:
		item_code = (ln.get("item_code") or "").strip()
		damage_code = (ln.get("damage_code") or "").strip() or None
		repair_code = (ln.get("repair_code") or "").strip() or None
		line_remarks = (ln.get("remarks") or "").strip() or None
		# A part with no real finding — Acceptable (or blank) damage AND No Action (or
		# blank) repair AND no remark — is the default condition and is not stored.
		#
		# Unless the operator OPENED that part's card ("added"): then it is a part somebody
		# deliberately walked up to, and dropping it meant the card vanished at the next
		# reload — along with any photo already hung on it, which came back as an unsorted
		# Foto Cepat because its line no longer existed. Stored, it reads as what it is: this
		# part was checked and found acceptable.
		is_acceptable = damage_code in (None, ACCEPTABLE_DAMAGE_CODE)
		is_no_action = repair_code in (None, NO_ACTION_REPAIR_CODE)
		if is_acceptable and is_no_action and not line_remarks and not _as_bool(ln.get("added")):
			continue

		item = items.get(item_code)
		if not item:
			frappe.throw(_("Unknown checklist item_code: {0}").format(item_code or "(blank)"))

		# Keterangan = apa yang DITULIS petugas, titik. Dulu baris kosong diisi deskripsi
		# kode kerusakan lalu nama item supaya field reqd terpenuhi — hasilnya kolom "Ket"
		# penuh gema kode ("Acceptable", "Front Top Rail") yang terbaca seperti catatan orang
		# padahal tidak ada yang menulisnya. Field-nya kini boleh kosong.
		description = line_remarks

		if damage_code and damage_code != ACCEPTABLE_DAMAGE_CODE:
			has_damage = True

		rows.append({
			"checklist_item": item_code,
			"component": f"{item.printed_no}. {item.item_name}",
			"damage_type": damage_code,
			"repair_code": repair_code,
			"damage_description": description,  # catatan petugas; boleh kosong
			"severity": "Minor",               # default fulfils reqd (B2)
		})
	return rows, has_damage


def _build_photo_rows(photos, items):
	"""Map a flat ``[{item_code, photo, caption}]`` payload to Inspection Item Photo rows.

	A row is kept whenever it carries a ``photo``. ``item_code`` is OPTIONAL: blank
	means "foto cepat" (bulk) not yet sorted into a section — stored with a null
	``checklist_item`` for the admin to assign later. Only a non-blank *unknown*
	code is rejected. (Rows with no photo are dropped.)

	``caption`` is the operator's own words about THIS frame ("bocor di sambungan bawah",
	"nomor seal terbaca dari sini") and is optional too. It is stored verbatim: the codes
	already say what kind of defect it is, and what the caption adds is the part no code
	has a slot for — which is exactly why a Desk reader must be able to see it.
	"""
	rows = []
	for ph in photos:
		item_code = (ph.get("item_code") or "").strip()
		photo = (ph.get("photo") or "").strip()
		if not photo:
			continue
		if item_code and item_code not in items:
			frappe.throw(_("Unknown checklist item_code for photo: {0}").format(item_code))
		rows.append({
			"checklist_item": item_code or None,
			"photo": photo,
			"caption": (ph.get("caption") or "").strip() or None,
		})
	return rows


def is_real_finding(damage_type, repair_code) -> bool:
	"""True when a checklist row records an actual defect, not just "sudah diperiksa".

	Acceptable ("v") with No Action ("X") is what an opened-but-clean card carries — it is
	stored so the card (and its photos) survive a reload, but it is not a damage: no M&R,
	no entry in the Riwayat damage list, and no damage photo.
	"""
	return (damage_type or "") not in ("", ACCEPTABLE_DAMAGE_CODE) or (repair_code or "") not in (
		"",
		NO_ACTION_REPAIR_CODE,
	)


def _split_damage_photos(photo_rows: list, damage_rows: list) -> tuple:
	"""Split one flat photo payload into (Foto per Item, Foto Kerusakan).

	A photo taken WHILE FILLING a checklist card belongs to that card, so it goes to the
	damage album — whatever the card ends up saying. The code on the row is not the test:
	"Acceptable / No Action" is still a part somebody walked up to, photographed and
	recorded, and its picture reads as noise in the general inspection album.

	What stays in Foto per Item is what was never taken on a card: foto cepat that has not
	been sorted yet, and photos assigned to a part that carries no checklist row at all.

	The split is derived, never sent by the client — remove the card and its photos come
	back on the next save.
	"""
	damaged = {r["checklist_item"] for r in damage_rows if r.get("checklist_item")}
	item_rows, damage_photo_rows = [], []
	for row in photo_rows:
		(damage_photo_rows if row.get("checklist_item") in damaged else item_rows).append(row)
	return item_rows, damage_photo_rows


def _fitting_items() -> dict:
	"""fitting_code -> master row for every ACTIVE kelengkapan slot (see ``eir_fitting_data``)."""
	return {
		f.name: f
		for f in frappe.get_all(
			"Inspection Fitting Item",
			filters={"is_active": 1},
			fields=[
				"name",
				"compartment",
				"printed_no",
				"item_label",
				"slot_label",
				"uom",
				"sequence",
			],
		)
	}


def _build_fitting_rows(fittings, items):
	"""Map the kelengkapan payload to ``Inspection Fitting`` rows.

	A blank value is dropped rather than stored: a slot nobody filled must read back as
	"not recorded", never as "recorded zero" — the difference decides whether a missing
	strap is a finding or just an unanswered box.

	Labels travel onto the row (compartment / item / slot / uom) instead of being resolved
	through the Link at read time, so editing the master later cannot rewrite what a
	submitted EIR says the tank carried. Same rule as ``Inspection Damage Entry``.
	"""
	rows = []
	seen = set()
	for f in fittings:
		if not isinstance(f, dict):
			continue
		code = (f.get("fitting_item") or "").strip()
		item = items.get(code)
		if not item or code in seen:
			continue
		value = str(f.get("value") if f.get("value") is not None else "").strip()
		if not value:
			continue
		seen.add(code)
		rows.append(
			{
				"fitting_item": code,
				"compartment": item.compartment,
				"printed_no": item.printed_no,
				"item_label": item.item_label,
				"slot_label": item.slot_label,
				"uom": item.uom,
				"value": value,
			}
		)
	rows.sort(key=lambda r: items[r["fitting_item"]].sequence or 0)
	return rows


def _saved_fittings(inspection: str) -> dict:
	"""fitting_code -> recorded value on a stored EIR."""
	return {
		r.fitting_item: r.value
		for r in frappe.get_all(
			"Inspection Fitting",
			filters={"parent": inspection, "parenttype": "Inspection"},
			fields=["fitting_item", "value"],
		)
		if r.fitting_item
	}


def _build_seal_rows(seals):
	"""Map the EIR-Out seal payload to Inspection Seal rows.

	Accepts either bare strings (``["ABC123", "DEF456"]``) or dicts
	(``[{"seal_no": "ABC123", "remarks": "top hatch"}]``) — the PWA sends the second,
	an integration might reasonably send the first. Blank numbers are dropped rather
	than saved as empty rows, and duplicates within one EIR are collapsed: the same
	physical seal cannot be fitted twice, so a repeat is a double-tap, not a fact.
	"""
	rows = []
	seen = set()
	for seal in seals:
		if isinstance(seal, str):
			seal = {"seal_no": seal}
		if not isinstance(seal, dict):
			continue
		seal_no = (seal.get("seal_no") or "").strip()
		if not seal_no or seal_no.upper() in seen:
			continue
		seen.add(seal_no.upper())
		rows.append({"seal_no": seal_no, "remarks": (seal.get("remarks") or "").strip() or None})
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
	fittings=None,
	submit=False,
) -> dict:
	"""Build an Inspection (EIR) from a checklist payload.

	Only lines carrying a ``damage_code``, ``repair_code``, ``remarks`` or the PWA's
	``added`` marker become Inspection Damage Entry rows — an untouched ("Acceptable") line
	is not stored. ``severity`` is defaulted server-side (Minor) so the checklist flow never
	trips validation (B2); ``damage_description`` holds the operator's remark and nothing
	else.

	``fittings`` is the kelengkapan tank (the printed sheet's fill-in boxes) — separate
	from ``lines`` because it records what the tank CARRIES, not what is wrong with it.

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
	doc.remarks = remarks
	# Depot yang diminta, kalau tidak ada ikut depot tangkinya. TIDAK boleh kosong: depot
	# inilah satu-satunya yang menyaring EIR ke branch penggunanya (``get_user_depots``), jadi
	# baris tanpa depot menghilang dari worklist DAN dari angka Beranda setiap akun yang
	# ber-branch — sementara akun tak terbatas tetap melihatnya, yang membuatnya terlihat
	# seperti "cuma dia yang punya datanya". Bukan fetch_from di doctype-nya karena depot
	# sebuah EIR boleh berbeda dari master tangkinya (lihat ``_voucher_depot``).
	doc.depot = depot or frappe.db.get_value("Container", container, "depot")
	doc.inspector = frappe.session.user
	doc.inspector_signature = signature
	doc.eir_date = eir_date
	doc.cargo = cargo
	doc.reff_doc = reff_doc  # this EIR's own reference doc (defaults from the booking)
	# Follow-up opt-outs (default checked via the doctype) — only overridden when supplied.
	if create_cleaning_order is not None:
		doc.create_cleaning_order = 1 if _as_bool(create_cleaning_order) else 0
	if create_repair_order is not None:
		doc.create_repair_order = 1 if _as_bool(create_repair_order) else 0
	if referred_voucher:
		_apply_voucher(doc, referred_voucher)  # overrides truck_no; sets driver / driver_phone / EMKL / shipper
	doc.has_damage = 1 if has_damage else 0
	if order_ref:
		doc.order_doctype = order_doctype or "Order Bongkar"
		doc.order_ref = order_ref
	doc.set("damage_log", damage_rows)
	item_rows, damage_photo_rows = _split_damage_photos(photo_rows, damage_rows)
	doc.set("item_photos", item_rows)
	doc.set("damage_photos", damage_photo_rows)
	doc.set("fittings", _build_fitting_rows(_coerce_lines(fittings), _fitting_items()))

	# Created and finished in one call: there is no draft for anyone to pick up, so the
	# "siap diperiksa" bell would point Team EIR at a submitted document (Inspection.after_insert).
	doc.flags.skip_created_notify = submit
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
		"fitting_rows": len(doc.get("fittings") or []),
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


def _fitting_payload(doc) -> list:
	"""Kelengkapan tank recorded on this draft, as ``{fitting_item, value, baseline}``.

	``baseline`` is what the SAME slot held on the container's last EIR-In, so the EIR-Out
	screen can show "masuk 2 pcs" beside the box the surveyor is filling — that comparison
	is the whole reason the numbers are recorded at both gates.

	An EIR-Out that has recorded nothing yet starts pre-filled from that baseline: the
	surveyor confirms or corrects instead of retyping 24 boxes. The prefill is all-or-
	nothing on purpose — once ANY slot is saved the draft owns its own values, so a box
	the surveyor deliberately cleared does not come back on the next open.
	"""
	saved = {r.fitting_item: r.value for r in (doc.get("fittings") or []) if r.fitting_item}
	baseline = {}
	if doc.inspection_type == "EIR-Out":
		ref = doc.get("reference_eir_in") or latest_eir_in(doc.container)
		if ref:
			baseline = _saved_fittings(ref)
	prefill = not saved and bool(baseline)
	return [
		{
			"fitting_item": code,
			"value": saved.get(code) or (baseline.get(code) if prefill else "") or "",
			"baseline": baseline.get(code) or "",
		}
		for code in sorted(set(saved) | set(baseline))
	]


def _draft_payload(doc, header: dict) -> dict:
	"""Merge a draft Inspection's saved state onto the master-derived ``header``.

	The tank fields stay sourced from the Container master (actual current data); the
	checklist lines, photos and user-entered fields come from the draft.
	"""
	header["inspection"] = doc.name
	# prefill() only fills booking_code when resolved from a bon; opening by container
	# leaves it blank, so recover it from the draft's referred bon for the PWA header.
	header["booking_code"] = _resolve_booking_code_for_eir(doc) or header.get("booking_code")
	header["inspection_id"] = doc.name
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
	header["emkl"] = doc.emkl
	header["shipper"] = doc.shipper
	header["doc_remarks"] = doc.remarks
	header["inspector_signature"] = doc.inspector_signature
	# Siapa yang terakhir menyentuh EIR ini, dan kapan. Frappe sudah mencatatnya sendiri
	# (``modified_by`` + baris Version, karena Inspection track_changes) — yang belum ada
	# adalah jalannya ke HP. Sejak satu order boleh dikerjakan bergantian (pagar klaim
	# dicabut 2026-09-10) inilah satu-satunya cara operator kedua tahu bahwa isian yang baru
	# saja muncul di layarnya bukan tulisannya sendiri.
	header["updated_on"] = str(doc.modified) if doc.modified else None
	header["updated_by"] = doc.modified_by
	header["updated_by_name"] = _fullname(doc.modified_by)
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
	header["fittings"] = _fitting_payload(doc)
	# Both albums travel as one list: the PWA hangs a photo on its damage card when the
	# card exists and drops the rest into Foto Cepat, which is the same rule the split on
	# the way in uses. Nothing in the client has to know there are two tables.
	header["photos"] = [
		{"item_code": p.checklist_item, "photo": p.photo, "caption": p.get("caption") or ""}
		for p in list(doc.item_photos) + list(doc.damage_photos)
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
				_apply_voucher(doc, voucher)  # truck / driver / driver phone / EMKL / shipper
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


def survey_interior_photos(doc) -> list:
	"""Interior photos the survey took of this EIR-Out's tank, ``[{photo, caption}]``.

	Read from the Survey Order (``Survey Order Photo``), never copied: the survey owns them,
	and a redone survey replaces them there.
	"""
	if not (doc.get("survey_order") and doc.get("survey_tank")):
		return []
	return frappe.get_all(
		"Survey Order Photo",
		filters={"parent": doc.survey_order, "survey_tank": doc.survey_tank},
		fields=["photo", "caption"],
		order_by="idx asc",
	)


@frappe.whitelist()
def get_survey_interior_photos(inspection: str) -> list:
	"""Desk Inspection form: the survey's interior photos for this EIR-Out."""
	doc = frappe.get_doc("Inspection", inspection)
	doc.check_permission("read")
	return survey_interior_photos(doc)


def open_eir_out(inspection: str, revise=None) -> dict:
	"""Open a draft EIR-Out for editing (worklist → form) with its EIR-In comparison."""
	payload = open_draft_by_name(inspection, revise=revise)
	doc = frappe.get_doc("Inspection", inspection)
	if doc.inspection_type != "EIR-Out":
		frappe.throw(_("{0} is not an EIR-Out.").format(inspection))
	payload["reference"] = get_eir_out_reference(doc)
	payload["seals"] = [
		{"seal_no": s.seal_no, "remarks": s.remarks} for s in (doc.get("out_seals") or [])
	]
	payload["interior_photos"] = survey_interior_photos(doc)
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
		frappe.throw(_("EIR {0} is no longer a draft.").format(inspection), exc=AlreadySettled)
	_guard_container_branch(doc.container)
	doc.check_permission("write")
	# Idempotent, and shared: a colleague pressing Mulai on an EIR somebody already started
	# joins it rather than being refused. The first press keeps the stamp — `work_started_on`
	# is how long the inspection took, and `work_started_by` who opened it, neither of which a
	# second press changes.
	if not doc.work_started_on:
		# Stamp who started it too, so the PWA can scope the "next/prev EIR" navigator to
		# the EIRs this account is working (idempotent: keep the original starter).
		# doc.save() and not db_set: Inspection tracks changes, and only the document path
		# writes the Version row that puts "Mulai" on the EIR's timeline. Safe here — the
		# doc is still a draft (guarded above), so neither field needs allow_on_submit.
		doc.work_started_on = now_datetime()
		doc.work_started_by = frappe.session.user
		doc.save()
	return {
		"success": True,
		"inspection": doc.name,
		"work_started_on": str(doc.work_started_on),
		"work_started_by": doc.work_started_by,
	}


# Facts about the TANK ITSELF that a surveyor may complete from an EIR, with how each one
# is read off the payload. The EIR is the moment somebody is standing at the tank with the
# data plate in front of them, so a half-empty Container master gets filled in there rather
# than in a separate Desk trip that never happens.
#
# ``equipment_type`` (FOO / CHM) belongs here for the same reason: foodgrade service is
# declared on the tank itself — the old EIR workbook literally had the surveyor check for a
# "Sticker FOO" — so it is something seen, not something looked up.
#
# ``last_test_date`` joined them on 2026-09-09. It used to be excluded as "something the
# depot writes by itself", and it was: the Periodic Test feature stamped it. That feature
# was deleted in v0_66, which kept the FIELD precisely because it is plate data ("the tank's
# plate test date… tank master data that happened to be stamped by the periodic test") — and
# left it with no writer at all outside the Desk. It is printed on the EIR, read by M&R and
# cleaning, and drives the Periodic Test Register's fallback, so a blank one is a real gap;
# the surveyor reading the plate is the only person who can close it.
#
# What is deliberately NOT here: everything the depot writes by itself — status, inventory
# stage, depot, last cargo, ex vessel, the gate dates — plus ``principal``, because who owns
# a tank is a commercial fact that decides billing, not something read off its side.
# ``container_no`` is the Container's own name and can never be edited from anywhere.
#
# None of these is ever REQUIRED to send an EIR: they describe the tank, not the inspection,
# and most arrive already filled from the master. The PWA states that outright — see the
# "Data tank" step in EirInForm.vue.
TANK_MASTER_FIELDS = {
	"container_type": "data",
	"equipment_type": "data",
	"size": "data",
	"serial_no": "data",
	"manufacture_date": "date",
	"last_test_date": "date",
	"capacity": "float",
	"tare_weight": "float",
	"max_gross_weight": "float",
}


def _tank_value(kind: str, value):
	"""Normalise one tank field so an unchanged value never counts as an edit."""
	if kind == "float":
		return flt(value)
	if kind == "date":
		return getdate(value) if value else None
	return (str(value).strip() or None) if value is not None else None


def _apply_tank_master(container: str, tank) -> list:
	"""Write the tank's own facts from an EIR back onto its Container master.

	Only the keys the payload actually carries are touched, so a form that shows three of
	the fields can never blank the other four. Returns the field names that really changed
	— an unchanged auto-save writes nothing at all.

	Saved with ``ignore_permissions``: the field roles hold Container **read** (§8.1) and
	are not about to be handed blanket write over the master, where ``status`` and ``depot``
	also live. The grant is this narrow list, reached only through an EIR the caller already
	has write permission on (``save_draft`` saves the Inspection under real permissions
	first) and only for a tank inside the caller's own branch.
	"""
	if isinstance(tank, str):
		try:
			tank = json.loads(tank)
		except json.JSONDecodeError:
			frappe.throw(_("tank must be a JSON object."))
	if not (container and isinstance(tank, dict) and tank):
		return []

	_guard_container_branch(container)
	doc = frappe.get_doc("Container", container)
	changed = []
	for field, kind in TANK_MASTER_FIELDS.items():
		if field not in tank:
			continue
		value = _tank_value(kind, tank.get(field))
		if _tank_value(kind, doc.get(field)) == value:
			continue
		doc.set(field, value)
		changed.append(field)
	if changed:
		doc.save(ignore_permissions=True)
	return changed


def save_draft(
	inspection: str,
	inspection_type: str | None = None,
	tank_status: str | None = None,
	vessel: str | None = None,
	truck_no: str | None = None,
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
	seals=None,
	fittings=None,
	tank=None,
	submit=False,
	revise=False,
) -> dict:
	"""Update an existing draft EIR — the PWA auto-save (and finalize) action.

	``revise`` saves a SUBMITTED EIR in place instead — Revisi Data from the PWA (see
	``revision.py``): one save, the record only, by someone holding the right.

	The PWA owns the draft's checklist state, so ``damage_log`` + ``item_photos`` (and
	the EIR-creator ``inspector_signature``) are replaced wholesale from the payload. The
	truck/driver/EMKL snapshot is re-resolved from ``referred_voucher``; ``cargo`` is
	recorded on the draft but only written back to ``Container.last_cargo`` on submit.
	``submit`` finalizes the EIR: the Inspection is submitted and its ``on_submit`` drives
	the container's status + cargo writeback (we never set status here). Permissions are
	enforced (no bypass).

	``tank`` completes the Container master from the tank in front of the surveyor — serial,
	type, size, build date, capacity, tare, MGW (see ``TANK_MASTER_FIELDS``). Unlike
	``cargo`` this is written straight away rather than on submit: it is not EIR state that a
	review could still change, it is the tank's own data, and an EIR that never gets finished
	should not take the correction down with it.
	"""
	doc = frappe.get_doc("Inspection", inspection)
	revising = _as_bool(revise) and doc.docstatus == 1
	if revising:
		from container_depot.container_depot import revision

		revision.assert_can_revise(doc)
	if doc.docstatus != 0 and not revising:
		frappe.throw(_("EIR {0} is no longer a draft.").format(inspection), exc=AlreadySettled)
	# Branch, on the save as well as on the open. It used to lean on the claim gate that sat
	# here — which only ever refused an EIR somebody else had STARTED, so an untouched draft
	# in another branch was writable by anyone who knew its name. Every other PWA mutator
	# (cleaning, M&R, start_eir) asks this question; this one has to as well.
	_guard_container_branch(doc.container)
	# Work-timing gate: editing is only allowed after the operator has pressed "Mulai"
	# (see ``start_eir``), so every saved EIR carries a real work-start timestamp.
	if not doc.work_started_on and not revising:
		frappe.throw(_("Tekan \"Mulai\" dulu sebelum mengisi EIR ini."))

	submit = _as_bool(submit)
	items = _checklist_items()
	damage_rows, has_damage = _build_damage_rows(_coerce_lines(lines), items)
	photo_rows = _build_photo_rows(_coerce_lines(photos), items)

	if inspection_type in ("EIR-In", "EIR-Out") and not revising:
		doc.inspection_type = inspection_type
	doc.tank_status = tank_status
	doc.vessel = vessel  # legacy free-text; ex_vessel now comes from the Container master
	doc.remarks = remarks
	doc.eir_date = eir_date
	doc.cargo = cargo  # written to Container.last_cargo only on submit (drafts never touch the master)
	# Optional reference doc — only overwritten when sent (EIR-Out saves omit it), so it isn't cleared.
	if reff_doc is not None:
		doc.reff_doc = reff_doc
	doc.inspector_signature = signature
	# Follow-up opt-outs: only set when the caller sends a value (the PWA always does), so a
	# Desk-set choice is never silently overwritten by an omitted param. A revision leaves
	# them: the orders were filed (or not) when the EIR was submitted.
	if create_cleaning_order is not None and not revising:
		doc.create_cleaning_order = 1 if _as_bool(create_cleaning_order) else 0
	if create_repair_order is not None and not revising:
		doc.create_repair_order = 1 if _as_bool(create_repair_order) else 0
	# The voucher owns truck_no / driver / driver_phone / emkl / shipper (read-only snapshot);
	# the legacy ``truck_no`` arg is ignored. No voucher -> these are cleared.
	#
	# Only re-resolved when it actually CHANGES. The PWA echoes back the voucher it was
	# handed (the field is read-only there), so re-validating an unchanged one is pure
	# overhead — and it was the first thing to blow up when a bon got cancelled
	# ("… is not submitted yet" on every auto-save). Note this alone does NOT make such
	# a draft savable: Frappe's own link check then raises CancelledLinkError. The fix
	# is to never leave a draft on a voided bon — see release_eirs_for_cancelled_order.
	if (referred_voucher or None) != (doc.referred_voucher or None) and not revising:
		_apply_voucher(doc, referred_voucher)
	doc.has_damage = 1 if has_damage else 0
	doc.set("damage_log", damage_rows)
	item_rows, damage_photo_rows = _split_damage_photos(photo_rows, damage_rows)
	doc.set("item_photos", item_rows)
	doc.set("damage_photos", damage_photo_rows)
	# EIR-Out seal numbers. Only replaced when the caller sends the key at all, so an
	# EIR-In save (which never carries seals) cannot wipe a Desk-entered list.
	if seals is not None:
		doc.set("out_seals", _build_seal_rows(_coerce_lines(seals)))
	# Kelengkapan tank. Same "only when the key is sent" rule as the seals above, so a
	# client that does not know about fittings cannot wipe a list entered on the Desk.
	if fittings is not None:
		doc.set("fittings", _build_fitting_rows(_coerce_lines(fittings), _fitting_items()))

	if revising:
		doc.flags.revision = True
		doc.save()  # update after submit — Inspection.before_update_after_submit polices it
		return {
			"success": True,
			"inspection": doc.name,
			"docstatus": doc.docstatus,
			"status": doc.status,
			"pending_review": False,
			"revision": 1,
			"has_damage": doc.has_damage,
			"damage_rows": len(damage_rows),
			"photo_rows": len(photo_rows),
			# The tank master is today's tank; an old EIR does not get to rewrite it.
			"tank_updated": False,
		}

	if submit and doc.inspection_type == "EIR-Out":
		# EIR-Out: the field team finishes it themselves (user, 2026-10-07) — no review.
		# The real Submit, so its own guards (bon, survey, Leak Check, open work) answer the
		# operator directly and on_submit is the gate-out. Team EIR holds submit on Inspection.
		doc.work_ended_on = now_datetime()
		if doc.work_started_on:
			doc.work_duration = max(0, int(time_diff_in_seconds(doc.work_ended_on, doc.work_started_on)))
		doc.save()  # NOT ignore_permissions.
		doc.submit()
	elif submit:
		# EIR-In: the field operator "submits" from the PWA → this does NOT finalize the EIR.
		# It moves to Pending Review (still a draft) for Admin Ops to check/classify, then
		# Admin Ops does the real Submit (docstatus 1) on the Desk — which is what fires
		# on_submit (container move + follow-up Cleaning/M&R orders + notify).
		doc.work_ended_on = now_datetime()
		if doc.work_started_on:
			doc.work_duration = max(0, int(time_diff_in_seconds(doc.work_ended_on, doc.work_started_on)))
		doc.status = "Pending Review"
		doc.save()  # NOT ignore_permissions — stays docstatus 0.
		# Ping the reviewers (Admin Ops + oversight) — this is the only signal they get
		# that an EIR is waiting; on_submit's crew notification only fires later, when
		# Admin Ops does the real Desk Submit.
		from container_depot.container_depot.notify import notify_eir_pending_review
		notify_eir_pending_review(doc)
	else:
		doc.save()  # NOT ignore_permissions.

	tank_updated = _apply_tank_master(doc.container, tank)

	return {
		"success": True,
		"inspection": doc.name,
		"docstatus": doc.docstatus,
		"status": doc.status,
		"pending_review": bool(submit) and doc.docstatus == 0,
		"has_damage": doc.has_damage,
		"damage_rows": len(damage_rows),
		"photo_rows": len(photo_rows),
		"tank_updated": tank_updated,
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
		{"row": p.name, "photo": p.photo, "caption": p.get("caption") or ""}
		for p in doc.item_photos
		if not p.checklist_item
	]
	return {
		"inspection": doc.name,
		"inspection_id": doc.name,
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


def list_my_eirs(user=None, search=None, start=0, page_length=10, docstatus=None, status=None) -> dict:
	"""The caller's own EIR inspections — newest first, searchable + paginated.

	Hard-scoped to ``owner == user`` (and EIR-In / EIR-Out) so a user only ever sees the
	EIRs they created. ``frappe.get_all`` is used deliberately (it ignores row-level
	permissions) — the owner filter is the security boundary. Search matches the container
	number or the EIR id; ``start`` / ``page_length`` paginate. Optional ``docstatus``
	(0 = drafts, 1 = submitted) narrows the list for the checklist landing's quick lists;
	optional ``status`` (e.g. "Pending Review") narrows to a single workflow state.
	"""
	user = user or frappe.session.user
	start = max(0, cint(start))
	page_length = min(max(1, cint(page_length or 10)), 50)

	filters = {"owner": user, "inspection_type": ["in", ["EIR-In", "EIR-Out"]]}
	if docstatus is not None and str(docstatus) != "":
		filters["docstatus"] = cint(docstatus)
	if status and str(status).strip():
		filters["status"] = str(status).strip()
	else:
		# Menunggu Review is not history — it sits under the EIR list's own Review pill (same as
		# Cleaning / M&R Riwayat). Its detail still opens here by deep link (?open=).
		filters["status"] = ["!=", "Pending Review"]
	or_filters = None
	if search and str(search).strip():
		s = f"%{str(search).strip()}%"
		or_filters = [["container_no", "like", s], ["name", "like", s], ["inspection_id", "like", s]]

	total = len(frappe.get_all(
		"Inspection", filters=filters, or_filters=or_filters, pluck="name", limit_page_length=0
	))
	items = frappe.get_all(
		"Inspection",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name", "inspection_id", "container", "container_no", "container_principal",
			"inspection_type", "status", "tank_status", "docstatus", "revision_requested",
			"eir_date", "creation", "inspector", "modified",
		],
		order_by="creation desc",
		limit_start=start,
		limit_page_length=page_length,
	)
	return {"items": _stamp_who(items), "total": total, "start": start, "page_length": page_length}


def _by_lift_on(items: list, start: int, page_length: int) -> list:
	"""The shared PWA worklist order, with the EIR's own test for "sedang dikerjakan".

	An EIR is in hand once ``start_eir`` has stamped ``work_started_on`` — the same field the
	screen's Belum / Dikerjakan split reads, so the list order and the filter tabs can never
	disagree. Everything else about the ordering lives in ``worklist.sort_by_priority``.
	"""
	return sort_by_priority(items, lambda r: bool(r.get("work_started_on")), start, page_length, date_of=_eir_due)


def _eir_due(row):
	"""The day an EIR is worked to: the outbound booking's date (``priority_date``), else —
	for an EIR-In — its own EIR Date. A tank coming IN has no pickup deadline (targets are
	stamped by Tank Out bookings only, lift_on.py), and the EIR Date is the day it is being
	checked in — so it sorts and groups by that instead of falling into "Tanpa target
	tanggal". Rows without ``inspection_type`` (the EIR-Out list) never take this branch."""
	return priority_date(row) or (row.get("eir_date") if row.get("inspection_type") == "EIR-In" else None)


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
	# Exclude "Pending Review": those are done from the field, awaiting Admin Ops on Desk.
	filters = {"docstatus": 0, "inspection_type": "EIR-In", "status": ["!=", "Pending Review"]}
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
			["name", "like", s],
			["inspection_id", "like", s],
			["referred_voucher", "like", s],
		]

	items = frappe.get_all(
		"Inspection",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name", "inspection_id", "container", "container_no", "container_principal",
			"inspection_type", "tank_status", "referred_voucher", "voucher_doctype", "depot",
			"eir_date", "creation",
			# Empty = not started yet, set = in progress (stamped by ``start_eir``). Drives
			# the PWA worklist's belum / dikerjakan split; work_started_by names who opened
			# it — shown on the row, and it scopes the next/prev EIR navigator.
			"work_started_on", "work_started_by",
			# The outbound booking's stamp — sorts and badges this worklist by pickup urgency.
			"target_lift_on", "target_survey_on", "target_urgent_on",
		],
		order_by="creation desc",
		limit_page_length=0,
	)
	# Whole list, then sort, then slice: the priority order is decided in Python (see
	# _by_lift_on), so SQL cannot page it. The open EIR list is bounded by the tanks in the
	# yard, which is what makes that affordable.
	total = len(items)
	items = _stamp_worker(_by_lift_on(items, start, page_length))
	return {"items": items, "total": total, "start": start, "page_length": page_length}


def _fullname(user) -> str | None:
	"""Nama yang enak dibaca, jatuh ke login-nya. ``None`` tetap ``None`` supaya klien bisa
	menyembunyikan barisnya, bukan mencetak nama berbentuk kosong."""
	if not user:
		return None
	return frappe.db.get_value("User", user, "full_name") or user


def _user_names(users) -> dict:
	"""``{login: full name}`` for a set of logins, in one query. Blank set = no query."""
	users = {u for u in users if u}
	if not users:
		return {}
	return {
		u.name: (u.full_name or u.name)
		for u in frappe.get_all(
			"User", filters={"name": ("in", list(users))}, fields=["name", "full_name"]
		)
	}


def _stamp_worker(items: list[dict]) -> list[dict]:
	"""Attach ``started_by_name`` — who already has this EIR open.

	Sejak pagar klaim dicabut (2026-09-10) sebuah EIR yang sudah ditekan "Mulai" tetap berada
	di worklist semua orang. Itu memang yang diminta, tapi berarti barisnya harus menyebut
	siapa yang sudah di dalamnya: dua orang mengisi checklist tangki yang sama sekarang
	mungkin terjadi, dan satu baris nama adalah bedanya antara "dikerjakan bergantian" dan
	"kaget di akhir shift". Alamat email tidak menjawab itu dari jarak satu meter; nama iya.

	Hanya untuk satu halaman, jadi satu query untuk baris yang benar-benar tampil.
	"""
	names = _user_names(i.get("work_started_by") for i in items)
	for i in items:
		if i.get("work_started_by"):
			i["started_by_name"] = names.get(i["work_started_by"]) or i["work_started_by"]
	return items


def _stamp_who(items: list[dict]) -> list[dict]:
	"""Attach ``inspector_name`` — the person, not their login.

	The worklist is branch-scoped, so every row can belong to somebody else and "who is
	holding this one" / "who finished it" are the questions a shift lead asks first. An email
	address answers neither at arm's length on a phone; a name (and the initials a row can be
	tagged with) does. One query for the whole page, not one per row.
	"""
	names = _user_names(i.get("inspector") for i in items)
	for i in items:
		if i.get("inspector"):
			i["inspector_name"] = names.get(i["inspector"]) or i["inspector"]
	return items


def list_review_eirs(search=None, start=0, page_length=20) -> dict:
	"""EIRs (In + Out) awaiting Admin Ops review — the PWA "Diajukan Review" list.

	These were "Kirim untuk Review" from the field: docstatus 0, status "Pending Review",
	not yet finalized. Branch-scoped by depot (empty user-branch = all) exactly like the
	worklist — NOT owner-scoped: auto-provisioned EIRs are owned by whoever submitted the
	bon, not the operator, so any operator in the branch can see (and pull back) them.
	Newest first; searchable by container no / EIR id.
	"""
	start = max(0, cint(start))
	page_length = min(max(1, cint(page_length or 20)), 50)

	filters = {
		"docstatus": 0,
		"status": "Pending Review",
		"inspection_type": ["in", ["EIR-In", "EIR-Out"]],
	}
	allowed = get_user_depots()
	if allowed is not None:
		if not allowed:
			return {"items": [], "total": 0, "start": start, "page_length": page_length}
		filters["depot"] = ["in", allowed]

	term = str(search).strip() if search is not None else ""
	if term.lower() in ("undefined", "null", "none"):
		term = ""
	or_filters = [["container_no", "like", f"%{term}%"], ["name", "like", f"%{term}%"], ["inspection_id", "like", f"%{term}%"]] if term else None

	items = frappe.get_all(
		"Inspection",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name", "inspection_id", "container", "container_no", "container_principal",
			"inspection_type", "status", "tank_status", "docstatus", "eir_date", "creation",
			"target_lift_on", "target_survey_on", "target_urgent_on", "inspector", "modified",
		],
		order_by="creation desc",
		limit_page_length=0,
	)
	# Whole list, then sort, then slice: the priority order is decided in Python (see
	# _by_lift_on), so SQL cannot page it. The open EIR list is bounded by the tanks in the
	# yard, which is what makes that affordable.
	total = len(items)
	items = _by_lift_on(items, start, page_length)
	return {"items": _stamp_who(items), "total": total, "start": start, "page_length": page_length}


def withdraw_review(inspection: str) -> dict:
	"""Operator pulls a "Pending Review" EIR back to Draft to fix it — before Admin Ops
	finalizes. No Admin Ops needed; the EIR becomes editable again and re-enters the
	worklist, then goes back through "Kirim untuk Review".

	Branch-scoped (not owner) to mirror the worklist: the auto-provisioned EIR is owned by
	the bon submitter, so any operator in the branch may withdraw it. Only valid while the
	EIR is actually awaiting review (docstatus 0 + Pending Review)."""
	if not inspection:
		frappe.throw(_("inspection is required."))
	doc = frappe.get_doc("Inspection", inspection)
	if doc.inspection_type not in ("EIR-In", "EIR-Out"):
		frappe.throw(_("{0} is not an EIR.").format(inspection))
	_guard_container_branch(doc.container)
	if doc.docstatus != 0 or doc.status != "Pending Review":
		frappe.throw(_("Hanya EIR yang berstatus 'Menunggu Review' yang bisa ditarik untuk diperbaiki."))

	# Back to an editable draft. Clear the review-submit stamps so the next "Kirim untuk
	# Review" re-times the work; work_started_on stays so the form stays "started" (no need
	# to press Mulai again to edit).
	doc.status = "Draft"
	doc.work_ended_on = None
	doc.work_duration = 0
	doc.save()  # NOT ignore_permissions — the operator holds Inspection write.

	# Audit trail on the timeline (best-effort — must not fail the withdraw).
	log_doc_note("Inspection", doc.name, _(
		"EIR ditarik dari review untuk diperbaiki oleh {0}"
	).format(frappe.session.user))

	return {
		"success": True,
		"inspection": doc.name,
		"docstatus": doc.docstatus,
		"status": doc.status,
		"inspection_type": doc.inspection_type,
	}


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
		or_filters = [["container_no", "like", s], ["name", "like", s], ["inspection_id", "like", s]]

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

	Auto-provisioned (one per container) when a position survey is CLOSED
	(``provision_eir_out_for_survey``), so the surveyor works from this list instead of
	creating one by hand. A draft here may still have no bon against it — the Order Muat
	adopts it later and only then can it be submitted. Branch-scoped by the Inspection depot;
	newest first; searchable by container number / EIR id / referred Order Muat; paginated.
	"""
	start = max(0, cint(start))
	page_length = min(max(1, cint(page_length or 20)), 50)

	# Exclude "Pending Review" — field-done EIR-Out awaiting Admin Ops submit on Desk.
	filters = {"docstatus": 0, "inspection_type": "EIR-Out", "status": ["!=", "Pending Review"]}
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
			["name", "like", s],
			["inspection_id", "like", s],
			["referred_voucher", "like", s],
		]

	items = frappe.get_all(
		"Inspection",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name", "inspection_id", "container", "container_no", "container_principal",
			"tank_status", "referred_voucher", "depot", "eir_date", "creation",
			# See list_pending_eirs: empty = not started, set = in progress; work_started_by
			# names who opened it.
			"work_started_on", "work_started_by",
			# The tank is on its way out — the plan's stamp says whether that is today.
			"target_lift_on", "target_survey_on", "target_urgent_on",
		],
		order_by="creation desc",
		limit_page_length=0,
	)
	# See list_pending_eirs: priority is decided in Python, so SQL cannot page it.
	total = len(items)
	items = _stamp_worker(_by_lift_on(items, start, page_length))
	return {"items": items, "total": total, "start": start, "page_length": page_length}


# Pil daftar EIR (PWA): open = docstatus 0. "Selesai" tinggal di Riwayat (list_my_eirs).
EIR_TODO, EIR_DOING, EIR_REVIEW = "todo", "doing", "review"


def _eir_state(r) -> str:
	if r.status == "Pending Review":
		return EIR_REVIEW
	return EIR_DOING if r.work_started_on else EIR_TODO


def list_eirs(status=None, search=None, inspection_type=None, depot=None, principal=None,
			  day=None, sort=None, start=0, page_length=20) -> dict:
	"""Open EIRs (In + Out, draft + Pending Review) in the user's branch — the PWA list, same
	shape as ``leak_check.list_leak_checks``.

	Default sort = ``worklist.sort_by_priority`` (the order the worklist always had);
	``sort="newest"`` = creation desc. Each row carries ``group`` — the date the screen groups
	on: the target day (urgent / survey / lift-on) under priority, the creation day otherwise
	("" = no target yet, "urgent" = tier 0). ``day`` matches either date. ``counts`` ignore every filter."""
	start = max(0, cint(start))
	page_length = min(max(1, cint(page_length or 20)), 50)
	scope = {"docstatus": 0, "inspection_type": ["in", ["EIR-In", "EIR-Out"]]}
	allowed = get_user_depots()
	if allowed is not None:
		scope["depot"] = ["in", allowed or [""]]

	filters = dict(scope)
	if inspection_type in ("EIR-In", "EIR-Out"):
		filters["inspection_type"] = inspection_type
	if depot:
		filters["depot"] = depot if allowed is None or depot in allowed else ""
	if principal:
		filters["container_principal"] = principal
	term = str(search or "").strip()
	if term.lower() in ("undefined", "null", "none"):
		term = ""
	or_filters = None
	if term:
		s = f"%{term}%"
		or_filters = [[f, "like", s] for f in (
			"container_no", "inspection_id", "name", "referred_voucher", "reff_doc", "container_booking",
		)]

	rows = frappe.get_all(
		"Inspection", filters=filters, or_filters=or_filters,
		fields=[
			"name", "inspection_id", "container", "container_no", "container_principal",
			"inspection_type", "status", "tank_status", "referred_voucher", "voucher_doctype",
			"depot", "reff_doc", "container_booking", "emkl", "shipper", "eir_date", "creation",
			"modified", "inspector", "work_started_on", "work_started_by",
			"target_lift_on", "target_survey_on", "target_urgent_on",
		],
		order_by="creation desc", limit_page_length=0,
	)
	if status in (EIR_TODO, EIR_DOING, EIR_REVIEW):
		rows = [r for r in rows if _eir_state(r) == status]
	else:
		# "Semua" leaves out Menunggu Review — in Admin Ops' hands now, reached through its own
		# pill (same as Cleaning and M&R).
		rows = [r for r in rows if _eir_state(r) != EIR_REVIEW]
	for r in rows:
		r["state"] = _eir_state(r)
		r["day"] = str(getdate(r.creation))
		due = r.target_urgent_on or _eir_due(r)
		r["due"] = str(due) if due else ""
	if day:
		d = str(getdate(day))
		rows = [r for r in rows if d in (r["day"], r["due"])]

	# Whole list, then sort, then slice — same as list_pending_eirs (bounded by the yard).
	if sort == "newest":
		for r in rows:
			r["group"] = r["day"]
		items = rows[start:start + page_length]
	else:
		for r in rows:
			# Tier mendesak = satu grup sendiri: tanggalnya bisa sama dengan tanggal survey biasa.
			r["group"] = "urgent" if r.target_urgent_on else r["due"]
		items = _by_lift_on(rows, start, page_length)
	day_counts: dict = {}
	for r in rows:
		day_counts[r["group"]] = day_counts.get(r["group"], 0) + 1
	total = len(rows)
	items = _stamp_who(_stamp_worker(items))
	for it in items:
		for k in ("creation", "modified", "work_started_on"):
			it[k] = str(it[k]) if it.get(k) else None

	counts = {"all": 0, EIR_TODO: 0, EIR_DOING: 0, EIR_REVIEW: 0, "EIR-In": 0, "EIR-Out": 0}
	for r in frappe.get_all("Inspection", filters=scope,
							fields=["status", "work_started_on", "inspection_type"], limit_page_length=0):
		counts["all"] += _eir_state(r) != EIR_REVIEW
		counts[_eir_state(r)] += 1
		counts[r.inspection_type] += 1

	def opts(field):
		return sorted({v for v in frappe.get_all("Inspection", filters=scope, pluck=field, distinct=True) if v})

	return {
		"items": items, "total": total, "start": start, "page_length": page_length,
		"counts": counts, "day_counts": day_counts,
		"depots": opts("depot"), "principals": opts("container_principal"),
	}


def open_draft_by_name(inspection: str, revise=None) -> dict:
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
	# Revisi Data: the same form, editing a submitted EIR in place (see revision.py).
	revising = _as_bool(revise) and doc.docstatus == 1
	if revising:
		from container_depot.container_depot import revision

		revision.assert_can_revise(doc)
	if doc.docstatus != 0 and not revising:
		frappe.throw(_("EIR {0} is no longer a draft.").format(inspection), exc=AlreadySettled)
	_guard_container_branch(doc.container)
	header = prefill(container=doc.container)
	payload = _draft_payload(doc, header)
	payload["revision"] = 1 if revising else 0
	return payload


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
		r.item_code: _(r.item_name)
		for r in frappe.get_all("Inspection Checklist Item", fields=["item_code", "item_name"])
	}
	# Evidence per finding, and the walk-around album on its own — the same two lists the
	# Desk form shows, so a reviewer checking an EIR from the phone sees what the office sees.
	# `{photo, caption}` and not a bare url: a caption the operator typed at the tank is
	# invisible wherever the photo is shown without it, which is the whole point of storing it.
	photos_by_item: dict = {}
	for p in doc.damage_photos:
		if p.photo:
			photos_by_item.setdefault(p.checklist_item, []).append(
				{"photo": p.photo, "caption": p.get("caption") or ""}
			)
	# Codes are keys, not words: "v" / "X" mean nothing on a phone. The Desk grid shows the
	# master's description because a Link renders its title; the PWA has to be handed it.
	code_names = {
		dt: {c.name: _(c.description) for c in frappe.get_all(dt, fields=["name", "description"])}
		for dt in ("Inspection Damage Code", "Inspection Repair Code")
	}

	# EVERY checklist card, exactly the list the Desk form shows under "Checklist Kerusakan"
	# — including the ones that came back Acceptable. Hiding those would drop their photos
	# into the inspection album, where a reviewer counting "2 foto inspeksi" finds five.
	# ``is_finding`` says which ones are actual defects so the UI can mark them apart.
	damages = [
		{
			"item": d.checklist_item,
			"item_name": names.get(d.checklist_item) or d.checklist_item,
			"damage_type": d.damage_type,
			"damage_label": code_names["Inspection Damage Code"].get(d.damage_type) or d.damage_type,
			"repair_code": d.repair_code,
			"repair_label": code_names["Inspection Repair Code"].get(d.repair_code) or d.repair_code,
			"damage_description": d.damage_description,
			"is_finding": 1 if is_real_finding(d.get("damage_type"), d.get("repair_code")) else 0,
			"photos": photos_by_item.get(d.checklist_item, []),
		}
		for d in doc.damage_log
	]
	# The album is what was never taken on a card: foto cepat and photos of parts with no
	# checklist row at all.
	photos = [
		{
			"item": p.checklist_item,
			"item_name": names.get(p.checklist_item) or p.checklist_item,
			"photo": p.photo,
			"caption": p.get("caption") or "",
		}
		for p in doc.item_photos
		if p.photo
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
		"revision_requested": 1 if doc.get("revision_requested") else 0,
		"revision_note": doc.get("revision_note"),
		# Revisi Data / Ajukan Revisi / Tolak — see revision.state.
		"revision": revision_state(doc),
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
		"finding_count": sum(1 for d in damages if d["is_finding"]),
		"photos": photos,
		"photo_count": len(photos),
		"interior_photos": survey_interior_photos(doc),
		"fittings": [
			{
				"fitting_item": f.fitting_item,
				"compartment": _(f.compartment),
				"printed_no": f.printed_no,
				"item_label": _(f.item_label),
				"slot_label": _(f.slot_label),
				"value": f.value,
				"uom": f.uom,
			}
			for f in doc.get("fittings") or []
		],
	}


def request_revision(inspection: str, reason: str | None = None) -> dict:
	"""Operator asks Admin Ops to correct a submitted EIR ("Ajukan Revisi").

	A request, not an edit — the shared flow in ``revision.request``: refused on an invoiced
	visit, a timeline note, the "Revisi Diminta" flag with its reason, and a notification to
	Admin Ops (+ ops oversight) in the container's branch. Admin Ops answers with Revisi Data,
	Kembalikan ke Draft, or Tolak Revisi.
	"""
	from container_depot.container_depot import notify as _notify
	from container_depot.container_depot import revision

	if not inspection:
		frappe.throw(_("inspection is required."))
	doc = frappe.get_doc("Inspection", inspection)
	if doc.inspection_type not in ("EIR-In", "EIR-Out"):
		frappe.throw(_("{0} is not an EIR.").format(inspection))
	out = revision.request(doc, reason, _notify.notify_eir_revision_requested)
	return {**out, "inspection": doc.name}


@frappe.whitelist()
def revert_to_draft(name: str) -> dict:
	"""Cancel a submitted EIR back to Draft so it can be edited again (Desk-only action).

	Rule (per ops): every EIR for the container must be submitted first — there must be
	NO other draft Inspection for the same container. This keeps the one-draft-per-
	container invariant the PWA's ``open_draft`` relies on (it returns the single
	``docstatus=0`` EIR for a container). The container status / last-cargo this EIR
	applied on submit are undone from the pre-submit snapshot, then the SAME record is
	flipped back to an editable draft (so it opens again in the PWA and in Desk).

	An EIR-Out never moved the tank (the bon is the gate-out), so reverting one leaves the tank,
	its bon and its gate log where they are.
	"""
	doc = frappe.get_doc("Inspection", name)
	doc.check_permission("cancel")

	if doc.docstatus != 1:
		frappe.throw(_("Hanya EIR yang sudah disubmit yang bisa dikembalikan ke draft."))
	# The snapshot below is only true for the newest EIR — see "Revisi Data" at the end.
	newer = newer_eir(doc)
	if newer:
		frappe.throw(_(
			"Sudah ada EIR yang lebih baru untuk tank ini ({0}). EIR lama tidak bisa dikembalikan "
			"ke Draft — pakai Revisi Data."
		).format(newer), title=_("Bukan EIR Terbaru"))
	invoice = storage_invoice_lock(doc)
	if invoice:
		frappe.throw(locked_message(invoice), title=_("EIR Terkunci"))

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

	unwind_submitted_eir(doc)

	# Flip back to an editable draft (same record — editable in the PWA + Desk). Clear any
	# pending revision request now that it has been actioned.
	frappe.db.set_value("Inspection", doc.name, {"docstatus": 0, "status": "Draft", "closed_by_admin": 0})
	# A pending Ajukan Revisi is answered by this — tell whoever asked.
	if cint(doc.get("revision_requested")):
		from container_depot.container_depot import revision

		revision.close_request(doc, done=True)
	# A backwards docstatus flip can never go through doc.save(), so no Version row is
	# written — put it on the EIR's timeline by hand.
	log_doc_note("Inspection", doc.name, _(
		"EIR dikembalikan ke draft oleh {0} (dari Submitted)."
	).format(frappe.session.user))

	# The snapshot says where the tank WAS; whether it is BUSY is decided by the work open
	# right now — and this EIR is open work again as of the line above. Recomputed here,
	# after the docstatus flip, because a still-submitted EIR is invisible to
	# `container_open_orders`. Booked / Gate_Out are left alone by the recompute.
	from container_depot.container_depot.container_status import recompute_availability
	from container_depot.container_depot.doctype.order_bongkar.order_bongkar import sync_completion

	recompute_availability(doc.container)
	sync_completion(doc)  # a reverted EIR-In reopens its bon

	# Append an inverse activity for the audit trail (the on_submit one stays — the log
	# is append-only). Never let a logging failure block the revert.
	try:
		from container_depot.container_depot.container_activity import log_container_activity
		log_container_activity(
			doc.container, "Inspection (EIR)",
			reference_doctype=doc.doctype, reference_name=doc.name,
			summary=_("{0} dikembalikan ke draft").format(doc.name),
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "revert_to_draft activity log")

	return {"name": doc.name, "docstatus": 0, "status": "Draft"}


def unwind_submitted_eir(doc, drop_followups: bool = False) -> None:
	"""Undo what submitting this EIR did to the world around it.

	The single unwind for BOTH ways back out of a submitted EIR — :func:`revert_to_draft`
	(reopen it for correction) and ``Inspection.on_cancel`` (void it). They differ in what
	they leave behind on the EIR itself, not in what they owe the rest of the depot, and
	keeping that in one place is what stops the void half quietly rolling back less than the
	revert half — which is exactly what it used to do.

	Two things come off, in this order:

	1. the Container status / last cargo this EIR wrote, from the pre-submit snapshot
	   ``Inspection.on_submit`` captured — for an EIR-Out the cargo only: it never moved the
	   tank (the bon is the gate-out, ``gate.depart_bon``), so undoing it must not either;
	2. with ``drop_followups``, the Cleaning Order / M&R the submit filed off an EIR-In,
	   while they are still untouched (:func:`eir_followups.release_followups_for_eir`).
	   Only the VOID asks for that. A revert is on its way back to a re-submit, and the
	   order it filed the first time is deliberately kept and re-adopted
	   (``create_cleaning_order_from_eir``) rather than dropped and filed again — which
	   would re-ring the cleaning team for a wash they were already told about.

	The tank's ``in_date`` / ``out_date`` are not touched: they are the bons' days
	(``visit_dates``), and an EIR never wrote them. The departure is undone by the bon's own
	Kembalikan ke Draft / void (``gate.reverse_bon_departures``).
	"""
	_restore_container_on_revert(doc)

	if doc.inspection_type == "EIR-Out":
		# Off the departure's Gate Entry: the corrected EIR-Out links itself again on re-submit.
		frappe.db.set_value(
			"Gate Entry", {"eir_reference": doc.name}, "eir_reference", None, update_modified=False
		)
	elif doc.inspection_type == "EIR-In" and drop_followups:
		from container_depot.container_depot import eir_followups

		eir_followups.release_followups_for_eir(doc.name)


def _restore_container_on_revert(doc) -> None:
	"""Undo the Container status / last_cargo change this EIR applied on submit, using the
	snapshot captured in ``Inspection.on_submit``. Only writes when something differs."""
	container = frappe.get_doc("Container", doc.container)
	changed = False

	prev_status = doc.get("container_status_before_submit")
	if doc.inspection_type != "EIR-Out" and prev_status and container.status != prev_status:
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


# ---------------------------------------------------------------------------
# Revisi Data — correcting an EIR that later EIRs have already built on
# ---------------------------------------------------------------------------
# `revert_to_draft` undoes a submit from the EIR's own snapshot, which is only true while
# nothing has moved the tank since: revert an EIR-In after its EIR-Out and the tank that left
# reads In_Depot again. So Kembalikan ke Draft is only for the newest EIR; any EIR can instead
# be corrected in place through Revisi Data (container_depot/revision.py) — still Submitted,
# with no effect on the tank, the gate, the bon, the booking or the orders it filed (user,
# 2026-10-06). An old EIR is never turned back into a draft: a draft EIR is what the PWA, the
# provisioning dedup and the worklists all read as the live EIR of the tank's CURRENT visit.
#
# Both stop at the invoice: once the visit's storage is billed, the EIR is frozen until that
# invoice is cancelled or the visit is taken off it.

# What a revision may not change: what the EIR is (tank, direction, the paper it answers) and
# what the system wrote at submit. Everything else is the survey's own record.
REVISION_LOCKED = (
	"container", "inspection_type", "depot", "referred_voucher", "voucher_doctype",
	"container_booking", "survey_order", "survey_tank", "reference_eir_in", "order_doctype",
	"order_ref", "status", "inspection_id", "client_uuid", "out_outcome",
	"create_cleaning_order", "create_repair_order",
	"container_status_before_submit", "container_last_cargo_before_submit",
	"work_started_on", "work_started_by", "work_ended_on", "work_duration",
)


def newer_eir(doc) -> str | None:
	"""A submitted EIR on the same tank that came after this one (its code), or None.

	"After" is a later creation OR a later ``eir_date``. Calling an EIR old when it is not
	only steers it to Revisi Data, which changes nothing outside the record; calling it newest
	when it is not lets a revert put back a status a later EIR has moved on from.
	"""
	base = {
		"container": doc.container, "docstatus": 1, "name": ["!=", doc.name],
		"inspection_type": ["in", ("EIR-In", "EIR-Out")],
	}
	probes = [{"creation": [">", doc.creation]}]
	if doc.get("eir_date"):
		probes.append({"eir_date": [">", doc.eir_date]})
	for probe in probes:
		rows = frappe.get_all("Inspection", filters={**base, **probe}, fields=["name", "inspection_id"], limit=1)
		if rows:
			return rows[0].name
	return None


def eir_visit(doc):
	"""``(period, lo, hi)`` — the storage stay this EIR belongs to (``storage.visit_for``)."""
	from container_depot import storage

	is_out = doc.inspection_type == "EIR-Out"
	ref = frappe.db.get_value("Gate Entry", {"eir_reference": doc.name}, "name") if is_out else None
	return storage.visit_for(
		doc.container, doc.eir_date or doc.work_ended_on or doc.creation, doc.get("container_no"),
		ref=ref, earlier=is_out,
	)


def storage_invoice_lock(doc) -> str | None:
	"""What has billed this EIR's storage visit — the invoice, else the watermark — or None.

	A draft invoice counts: it is already carrying the visit's days.
	"""
	from container_depot import storage_charge

	period = eir_visit(doc)[0]
	row = storage_charge.billed_row(doc.container, period) if period else None
	if not row or not (row.sales_invoice or row.billed_until):
		return None
	return row.sales_invoice or _("tagihan storage s/d {0}").format(frappe.utils.formatdate(row.billed_until))


def locked_message(invoice) -> str:
	return _(
		"Storage kunjungan ini sudah diinvoice ({0}). Batalkan invoice-nya dulu, atau keluarkan "
		"kunjungan ini dari invoice."
	).format(invoice)


def revision_invoice(doc) -> str | None:
	"""``revision.py`` hook: an EIR is frozen by its visit's storage invoice."""
	return storage_invoice_lock(doc)


def revision_apply(doc, before) -> None:
	"""``revision.py`` hook: the derived bits ``validate`` would redo on a draft save — a
	submitted document's update skips validate."""
	doc.sync_has_damage()
	doc.drop_empty_photo_rows()
	# Truck / driver / parties corrected here are the booking line's: written there, they
	# come back to the bon and every other copy (order_generation.push_follower_to_line).
	from container_depot.container_depot.order_generation import push_follower_to_line

	push_follower_to_line(doc, before, doc.get("voucher_doctype"), doc.get("referred_voucher"))


def revision_state(doc) -> dict:
	"""What the Desk and the PWA may offer on a submitted EIR: ``revision.state`` plus
	``newer`` — Kembalikan ke Draft is only for the newest EIR on the tank."""
	from container_depot.container_depot import revision

	if doc.docstatus != 1:
		return {}
	return {**revision.state(doc), "newer": newer_eir(doc)}


def check_update_after_submit(doc) -> None:
	"""``Inspection.before_update_after_submit`` — the rules for editing a submitted EIR:
	a Revisi Data save (``revision.check``), and the date rule every edit answers to."""
	before = doc.get_doc_before_save()
	if not before:
		return
	if doc.flags.get("revision"):
		from container_depot.container_depot import revision

		revision.check(doc)
	if str(doc.get("eir_date") or "") != str(before.get("eir_date") or ""):
		_check_eir_date_change(before, doc)


def _check_eir_date_change(before, doc) -> None:
	"""A submitted EIR's date may move only inside its own visit, and only while unbilled.

	``eir_date`` has always been editable after submit; for an EIR-In it is where the visit's
	storage starts, so this is what keeps a correction from rewriting a bill already sent —
	or, by landing in another visit's window, a different visit's bill altogether.
	"""
	if not doc.get("eir_date"):
		frappe.throw(_("Tanggal EIR wajib diisi."))
	invoice = storage_invoice_lock(before)
	if invoice:
		frappe.throw(locked_message(invoice), title=_("Tanggal EIR Terkunci"))
	period, lo, hi = eir_visit(before)
	day = getdate(doc.eir_date)
	if period and (day < lo or (hi and day > hi)):
		frappe.throw(_(
			"Tanggal EIR harus di dalam kunjungan tank ini: {0} s/d {1}."
		).format(frappe.utils.formatdate(lo), frappe.utils.formatdate(hi) if hi else _("sekarang")))


def after_update_after_submit(doc) -> None:
	"""``Inspection.on_update_after_submit`` — bring the storage ledger along at once, and
	close out a Revisi Data.

	The ledger would heal on the next status change or the nightly sweep, but a bill run in
	between would read the old date while the report already shows the new one.
	"""
	if doc.inspection_type == "EIR-In" and doc.has_value_changed("eir_date"):
		from container_depot import storage_charge

		storage_charge.sync(doc.container, doc.get("container_no"))
	if doc.flags.get("revision"):
		from container_depot.container_depot import revision

		revision.after(doc)
