"""Gate Entry history for the PWA "Riwayat Gate" feed + the TANK OUT gate-out write.

Mirrors ``container_depot.eir``: deliberately free of ``@frappe.whitelist`` so the ``ess.gate``
endpoints add only auth + whitelisting. Lists Gate Entries (the gate-in / gate-out voucher
records), returns one record's detail, and completes gate-out / load-complete for a tank
(:func:`mark_gate_out`).

There is no operator-pressed "ACC Keluar" any more: a tank is out the moment its EIR-Out is
reviewed and submitted clean, so ``Inspection.on_submit`` is the ONLY caller of
:func:`mark_gate_out` — the approval on the EIR *is* the departure. Undoing a departure is
therefore undoing that EIR (``eir.revert_to_draft``, which calls
:func:`reopen_gate_entry_for_eir`).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from container_depot.container_depot.container_status import PRESENT, container_open_orders
from container_depot.container_depot.user_branch import assert_in_user_branch, get_user_depots

_LIST_FIELDS = [
	"name", "gate_entry_id", "container_no", "status", "booking_code", "depot",
	"truck_plate", "driver_name", "gate_in_timestamp", "gate_out_timestamp",
	"eir_reference", "inspection_status", "creation",
]


def list_gate_history(start=0, page_length=10, search=None) -> dict:
	"""Gate Entry records (gate-in/out vouchers), newest first, paginated + searchable,
	depot-scoped to the caller's branch."""
	filters = {}
	depots = get_user_depots()
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]
	or_filters = None
	search = (search or "").strip()
	if search and search.lower() != "undefined":
		or_filters = {
			"container_no": ["like", f"%{search}%"],
			"gate_entry_id": ["like", f"%{search}%"],
			"booking_code": ["like", f"%{search}%"],
			"truck_plate": ["like", f"%{search}%"],
		}
	items = frappe.get_all(
		"Gate Entry", filters=filters, or_filters=or_filters,
		fields=_LIST_FIELDS, order_by="creation desc",
		limit_start=cint(start), limit_page_length=cint(page_length),
	)
	return {"items": items, "total": frappe.db.count("Gate Entry", filters)}


def get_gate_detail(name) -> dict:
	"""One Gate Entry's full detail (vehicle, order ref, EIR ref), branch-guarded."""
	if not name:
		frappe.throw(_("name is required."))
	doc = frappe.get_doc("Gate Entry", name)
	assert_in_user_branch(depot=doc.depot)
	return {
		"name": doc.name,
		"gate_entry_id": doc.gate_entry_id,
		"status": doc.status,
		"booking_code": doc.booking_code,
		"depot": doc.depot,
		"order_doctype": doc.order_doctype,
		"order_ref": doc.order_ref,
		"container_no": doc.container_no,
		"security_guard": doc.security_guard,
		"truck_plate": doc.truck_plate,
		"driver_name": doc.driver_name,
		"gate_in_timestamp": str(doc.gate_in_timestamp) if doc.gate_in_timestamp else None,
		"gate_out_timestamp": str(doc.gate_out_timestamp) if doc.gate_out_timestamp else None,
		"eir_reference": doc.eir_reference,
		"inspection_status": doc.inspection_status,
		"docstatus": doc.docstatus,
	}


# Gate Entry statuses that mean the visit a record covers is finished. Anything else is an
# OPEN visit, and there is at most one of those per tank — that invariant is what lets the
# arrival (``Order Bongkar._record_gate_in``) and the departure (:func:`mark_gate_out`)
# write to the same row instead of each filing its own.
GATE_ENTRY_CLOSED = ["Gate_Out_Completed", "Cancelled"]


def open_gate_entry_for(container_no):
	"""Name of the Gate Entry covering this tank's current visit, or None.

	Cancelled bons leave their record on status ``Cancelled`` rather than deleting it, so the
	status filter — not the absence of a row — is what marks a visit as over.
	"""
	if not container_no:
		return None
	found = frappe.get_all(
		"Gate Entry",
		filters={
			"container_no": container_no,
			"status": ["not in", GATE_ENTRY_CLOSED],
			"docstatus": ["<", 2],
		},
		fields=["name"], order_by="creation desc", limit=1,
	)
	return found[0].name if found else None


# ---------------------------------------------------------------------------
# TANK OUT — complete gate-out / load-complete (PRO-OPS-009 §5.2 step 5).
# ---------------------------------------------------------------------------
def _latest_order_muat(container, container_no):
	"""Name of the latest SUBMITTED Order Muat whose ``containers`` table holds this tank
	(best-effort context for the Gate Entry + notification; gate-out does not require it)."""
	parents = frappe.get_all(
		"Order Container Item",
		filters={"parenttype": "Order Muat"},
		or_filters={"container": container, "container_no": container_no},
		pluck="parent",
	)
	if not parents:
		return None
	rows = frappe.get_all(
		"Order Muat",
		filters={"name": ["in", list(set(parents))], "docstatus": 1},
		fields=["name"], order_by="creation desc", limit=1,
	)
	return rows[0].name if rows else None


def _muat_vehicle(order_muat) -> dict:
	"""Truck + driver behind a departure, as Gate Entry fieldnames.

	Tank Out carries the vehicle on the ``Order Muat`` HEADER (one truck per bon), unlike
	Tank In which carries it per container row — see ``eir._voucher_detail`` for the same
	split. Empty values are dropped so this never blanks a column that already has one.
	"""
	if not order_muat:
		return {}
	row = frappe.db.get_value(
		"Order Muat", order_muat, ["truck_plate", "driver_name"], as_dict=True
	) or {}
	return {k: v for k, v in row.items() if v}


def _resolve_or_create_gate_entry(container_no, order_muat, depot, performed_by):
	"""The Gate Entry to stamp on gate-out. A Gate Entry spans a tank's whole depot visit
	(it carries BOTH ``gate_in_timestamp`` and ``gate_out_timestamp``), so reuse the latest
	one not yet gated out; if none exists (no recorded gate-in), build a fresh one. Returns
	an unsaved ``new_doc`` (``.name`` is falsy) when created, else the loaded existing doc.

	The reuse branch is the normal path since ``Order Bongkar._record_gate_in`` started
	opening a record at arrival. The create branch remains for the tanks that predate it and
	for a gate-out on a tank whose arrival was never bonned.

	``order_doctype``/``order_ref`` on a reused record are deliberately LEFT ALONE: the
	doctype has one order link and the arrival voucher is the only thing that would be lost
	by overwriting it — the departure bon is already reachable from the container, from the
	"Gate Out" Container Activity, and from this function's own return value.
	"""
	found = open_gate_entry_for(container_no)
	if found:
		return frappe.get_doc("Gate Entry", found)
	doc = frappe.new_doc("Gate Entry")
	doc.container_no = container_no
	doc.depot = depot
	doc.security_guard = performed_by
	if order_muat:
		doc.order_doctype = "Order Muat"
		doc.order_ref = order_muat
		bc = frappe.db.get_value(
			"Order Container Item",
			{"parent": order_muat, "parenttype": "Order Muat", "container_no": container_no},
			"booking_code",
		)
		if bc:
			doc.booking_code = bc
	for field, value in _muat_vehicle(order_muat).items():
		setattr(doc, field, value)
	return doc


def mark_gate_out(container=None, gate_entry=None, *, eir_out=None, performed_by=None) -> dict:
	"""Complete gate-out / load-complete for a tank — the final OUT step.

	Called from ``Inspection.on_submit`` when a clean EIR-Out is submitted, which passes its
	own name as ``eir_out``. There is no other caller: the reviewed EIR-Out is what declares
	the tank gone.

	Moves the Container to ``Gate_Out`` (through the guarded state machine, so a Container
	Movement is auto-logged and ``inventory_stage`` becomes ``Departed``), stamps the Gate
	Entry (``gate_out_timestamp`` + ``status="Gate_Out_Completed"``), writes a "Gate Out"
	Container Activity, and notifies the gate/ops roles. Idempotent: a no-op if the tank is
	already gated out. Readiness-guarded: only ``Released_Pending_Pickup`` / ``Available``
	tanks may gate out (anything mid-process throws). Whole mutation runs in a savepoint.
	"""
	if not container:
		frappe.throw(_("container is required."))
	name = frappe.db.get_value("Container", {"name": container}) or frappe.db.get_value(
		"Container", {"container_no": container}
	)
	if not name:
		frappe.throw(_("Container {0} not found.").format(container))
	doc = frappe.get_doc("Container", name)
	assert_in_user_branch(depot=doc.depot)
	performed_by = performed_by or frappe.session.user

	# Idempotent — already gated out.
	if doc.status == "Gate_Out":
		ge = frappe.get_all(
			"Gate Entry",
			filters={"container_no": doc.container_no, "status": "Gate_Out_Completed"},
			fields=["name", "gate_out_timestamp"], order_by="creation desc", limit=1,
		)
		return {
			"container": doc.name,
			"status": "Gate_Out",
			"gate_entry": ge[0].name if ge else None,
			"gate_out_timestamp": str(ge[0].gate_out_timestamp) if ge and ge[0].gate_out_timestamp else None,
			"already": True,
		}

	# Readiness — digital equivalent of "Kalmar matches tank vs Bon Muat". Two distinct
	# refusals: the tank is not physically here, or work on it is still open. The second is
	# read from the orders themselves rather than the cached status, and names them — an
	# operator at the gate can then say what is missing instead of just "not ready".
	if doc.status not in PRESENT:
		frappe.throw(
			_("Container {0} tidak ada di depo (status {1}) — tidak bisa gate-out.").format(
				doc.name, doc.status
			)
		)
	open_orders = container_open_orders(doc.name)
	if open_orders:
		listed = ", ".join(f"{o['label']} {o['name']} ({o.get('status') or '-'})" for o in open_orders)
		frappe.throw(
			_("Container {0} masih punya order yang belum selesai — {1}.").format(doc.name, listed)
		)

	# EIR-Out gate (Fase G): a tank may only leave once a surveyor's EIR-Out is reviewed and
	# submitted clean (out_outcome = Ready To Load). Unfinished work is already refused above
	# (order_muat._validate_no_open_work applies the same rule when the bon is made).
	# The caller (``Inspection.on_submit``) hands in the EIR it just submitted; the lookup is
	# the fallback for a back-office/console call. Either way it stays the resolved name, not
	# a bare exists(): it is the EIR that released this tank, so it is also what belongs in
	# the Gate Entry's `eir_reference` below.
	eir_out = eir_out or frappe.db.get_value(
		"Inspection",
		{"container": doc.name, "inspection_type": "EIR-Out", "docstatus": 1, "out_outcome": "Ready To Load"},
		"name",
		order_by="modified desc",
	)
	if not eir_out:
		frappe.throw(
			_("Container {0} belum punya EIR-Out bersih (Ready To Load). Surveyor harus submit EIR-Out dulu.").format(
				doc.name
			)
		)

	prev = doc.status
	ts = now_datetime()
	order_muat = _latest_order_muat(doc.name, doc.container_no)

	frappe.db.savepoint("mark_gate_out")
	try:
		# Move the tank through the guarded transition (auto-logs the Container Movement).
		doc.status = "Gate_Out"
		frappe.flags.in_status_automation = True
		try:
			doc.save(ignore_permissions=True)
		finally:
			frappe.flags.in_status_automation = False

		# Stamp the Gate Entry. A NEW one is left a draft on purpose — submitting a Gate
		# Entry runs its on_submit which forces the container back to Gate_In.
		ge_doc = (
			frappe.get_doc("Gate Entry", gate_entry)
			if gate_entry and frappe.db.exists("Gate Entry", gate_entry)
			else _resolve_or_create_gate_entry(doc.container_no, order_muat, doc.depot, performed_by)
		)
		if not ge_doc.name:
			ge_doc.gate_out_timestamp = ts
			ge_doc.status = "Gate_Out_Completed"
			ge_doc.eir_reference = eir_out
			ge_doc.inspection_status = "Completed"
			if not ge_doc.gate_in_timestamp:
				ge_doc.gate_in_timestamp = ts
			ge_doc.insert(ignore_permissions=True)
		else:
			update = {
				"gate_out_timestamp": ts,
				"status": "Gate_Out_Completed",
				"eir_reference": eir_out,
				"inspection_status": "Completed",
			}
			# Vehicle on a REUSED record: fill only what the arrival left blank. Same
			# precedent as order_doctype/order_ref above — the doctype has one slot, the
			# visit it describes starts at the gate-in, and the departure truck is still
			# reachable from the Order Muat this gate-out returns.
			for field, value in _muat_vehicle(order_muat).items():
				if not ge_doc.get(field):
					update[field] = value
			frappe.db.set_value("Gate Entry", ge_doc.name, update, update_modified=True)
		gate_entry_name = ge_doc.name

		from container_depot.container_depot.container_activity import log_container_activity

		log_container_activity(
			doc.name, "Gate Out",
			reference_doctype="Gate Entry", reference_name=gate_entry_name,
			from_status=prev, to_status="Gate_Out",
			summary="Gate-out / load complete" + (f" — {order_muat}" if order_muat else ""),
			performed_by=performed_by,
		)

		# The bon is the reason the tank left — close it once its LAST tank is out, so a
		# finished load stops counting as work-in-progress (the daily operations report
		# filters `order_status NOT IN ('Completed', 'Hold')`).
		order_completed = _complete_order_muat_if_done(order_muat)

		# Same idea one level up: the customer's lift-on notice (Gate Out Plan) advances its
		# "% Keluar" and closes at 100%, releasing this tank's target_lift_on stamp so the
		# customer's NEXT notice can list it again.
		from container_depot.container_depot.doctype.gate_out_plan.gate_out_plan import (
			refresh_plans_for_container,
		)

		plans_fulfilled = refresh_plans_for_container(doc.name)

		# The tank has left, so the lift-on date its outbound booking stamped on it has been
		# met — drop it, or a departed tank keeps sitting at the top of every worklist and
		# the customer's next booking cannot claim it.
		from container_depot.container_depot import lift_on

		lift_on.release_on_gate_out(doc.name)

		from container_depot.container_depot.notify import notify_gate_out

		notify_gate_out(doc.container_no, gate_entry=gate_entry_name, depot=doc.depot, when=ts)
	except Exception:
		frappe.db.rollback(save_point="mark_gate_out")
		raise

	return {
		"container": doc.name,
		"status": "Gate_Out",
		"gate_entry": gate_entry_name,
		"gate_out_timestamp": str(ts),
		"order_muat": order_muat,
		"order_completed": order_completed,
		"plans_fulfilled": plans_fulfilled,
	}


def _complete_order_muat_if_done(order_muat) -> bool:
	"""Mark the bon ``Completed`` once every container on it has left the depot.

	Called from inside :func:`mark_gate_out`'s savepoint. A bon may carry several tanks and
	they leave one truck at a time, so completion is only correct when the LAST one is out —
	otherwise the still-waiting tanks would lose the bon that lists them. Returns whether the
	bon was closed by this call (False when it does not exist, is not submitted, was already
	Completed/Hold, or still has tanks in the depot).
	"""
	if not order_muat:
		return False
	row = frappe.db.get_value(
		"Order Muat", order_muat, ["docstatus", "order_status"], as_dict=True
	)
	if not row or row.docstatus != 1 or row.order_status in ("Completed", "Hold"):
		return False
	containers = frappe.get_all(
		"Order Container Item",
		filters={"parent": order_muat, "parenttype": "Order Muat"},
		pluck="container",
	)
	containers = [c for c in containers if c]
	if not containers:
		return False
	still_here = frappe.db.count(
		"Container", {"name": ["in", containers], "status": ["!=", "Gate_Out"]}
	)
	if still_here:
		return False
	frappe.db.set_value("Order Muat", order_muat, "order_status", "Completed", update_modified=False)
	return True


def reopen_gate_entry_for_eir(eir_out) -> str | None:
	"""Undo the gate-out stamp an EIR-Out left on its Gate Entry — the inverse of the
	stamping inside :func:`mark_gate_out`.

	Departure is now declared by submitting the EIR-Out, so *un*-submitting it
	(``eir.revert_to_draft``) has to put the visit back on the books: without this the
	record stays ``Gate_Out_Completed``, ``open_gate_entry_for`` stops finding it, and the
	corrected EIR-Out would file a SECOND Gate Entry for one visit. Returns the reopened
	record's name, or None when this EIR never stamped one.
	"""
	if not eir_out:
		return None
	found = frappe.get_all(
		"Gate Entry",
		filters={"eir_reference": eir_out, "status": "Gate_Out_Completed"},
		fields=["name", "gate_in_timestamp"], order_by="creation desc", limit=1,
	)
	if not found:
		return None
	row = found[0]
	frappe.db.set_value(
		"Gate Entry", row.name,
		{
			"gate_out_timestamp": None,
			"eir_reference": None,
			# Back to the state the arrival left it in: the tank is in the depot again.
			"status": "Gate_In_Completed" if row.gate_in_timestamp else "Active",
			"inspection_status": "In_Progress",
		},
		update_modified=True,
	)
	return row.name
