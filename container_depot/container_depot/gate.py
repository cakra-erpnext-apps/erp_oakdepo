"""Gate Entry history for the PWA "Riwayat Gate" feed + the TANK OUT gate-out action.

Mirrors ``container_depot.eir``: deliberately free of ``@frappe.whitelist`` so the ``ess.gate``
endpoints add only auth + whitelisting. Lists Gate Entries (the gate-in / gate-out voucher
records), returns one record's detail, and — the final SOP step PRO-OPS-009 §5.2 (5) —
completes gate-out / load-complete for a tank (:func:`mark_gate_out`).
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


def _resolve_or_create_gate_entry(container_no, order_muat, depot, performed_by):
	"""The Gate Entry to stamp on gate-out. A Gate Entry spans a tank's whole depot visit
	(it carries BOTH ``gate_in_timestamp`` and ``gate_out_timestamp``), so reuse the latest
	one not yet gated out; if none exists (no recorded gate-in), build a fresh one. Returns
	an unsaved ``new_doc`` (``.name`` is falsy) when created, else the loaded existing doc."""
	found = frappe.get_all(
		"Gate Entry",
		filters={"container_no": container_no, "status": ["not in", ["Gate_Out_Completed", "Cancelled"]]},
		fields=["name"], order_by="creation desc", limit=1,
	)
	if found:
		return frappe.get_doc("Gate Entry", found[0].name)
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
	return doc


def mark_gate_out(container=None, gate_entry=None, *, performed_by=None) -> dict:
	"""Complete gate-out / load-complete for a tank — the final OUT step.

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

	# EIR-Out gate (Fase G): a tank may only leave once a surveyor's EIR-Out is submitted
	# clean (out_outcome = Ready To Load). Unfinished work is already refused above
	# (order_muat._validate_no_open_work applies the same rule when the bon is made).
	if not frappe.db.exists(
		"Inspection",
		{"container": doc.name, "inspection_type": "EIR-Out", "docstatus": 1, "out_outcome": "Ready To Load"},
	):
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
			if not ge_doc.gate_in_timestamp:
				ge_doc.gate_in_timestamp = ts
			ge_doc.insert(ignore_permissions=True)
		else:
			frappe.db.set_value(
				"Gate Entry", ge_doc.name,
				{"gate_out_timestamp": ts, "status": "Gate_Out_Completed"}, update_modified=True,
			)
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


# ---------------------------------------------------------------------------
# SIAP KELUAR — the post-EIR-Out reminder worklist (ACC → gate-out).
# ---------------------------------------------------------------------------
def _last_gate_out_at(containers) -> dict:
	"""``{container: datetime}`` of each tank's most recent "Gate Out" activity."""
	out = {}
	if not containers:
		return out
	for row in frappe.get_all(
		"Container Activity",
		filters={"container": ["in", containers], "activity_type": "Gate Out"},
		fields=["container", "activity_time"],
		order_by="activity_time asc",
	):
		if row.activity_time:
			out[row.container] = row.activity_time  # ascending → last write wins
	return out


def list_ready_to_load(search=None, start=0, page_length=20) -> dict:
	"""Tanks whose EIR-Out is submitted clean but that are still standing in the depot.

	This is the reminder queue between the surveyor's EIR-Out and the physical exit: the
	list is *derived*, never stored, so it cannot drift out of sync — a tank appears the
	moment its EIR-Out is submitted ``Ready To Load`` and disappears the moment
	:func:`mark_gate_out` moves it to ``Gate_Out``. Oldest wait first (it is a reminder,
	not a feed). Branch-scoped like the rest of ess.*.

	Two traps this filters out: a tank that already left (status ``Gate_Out``), and a
	*stale* clean EIR-Out from an earlier visit — a tank that went out and came back in
	would otherwise resurface here, so any EIR-Out older than the tank's last recorded
	gate-out is dropped.
	"""
	depots = get_user_depots()
	filters = {"inspection_type": "EIR-Out", "docstatus": 1, "out_outcome": "Ready To Load"}
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]
	rows = frappe.get_all(
		"Inspection",
		filters=filters,
		fields=[
			"name", "inspection_id", "container", "container_no", "depot", "eir_date",
			"referred_voucher", "truck_no", "driver", "shipper", "modified",
		],
		order_by="modified desc",
		limit_page_length=0,
	)
	# One row per tank — the newest EIR-Out wins (a revised bon can leave two).
	latest = {}
	for r in rows:
		if r.container and r.container not in latest:
			latest[r.container] = r

	present = {
		c.name: c
		for c in frappe.get_all(
			"Container",
			filters={"name": ["in", list(latest)] or [""], "status": ["in", list(PRESENT)]},
			fields=["name", "container_no", "principal", "depot", "status"],
		)
	} if latest else {}
	gated_out_at = _last_gate_out_at(list(present))

	items = []
	for container, r in latest.items():
		c = present.get(container)
		if not c:
			continue
		last_out = gated_out_at.get(container)
		if last_out and r.modified and last_out > r.modified:
			continue  # stale: the tank already left after this EIR-Out, and came back
		bon = (
			frappe.db.get_value(
				"Order Muat",
				r.referred_voucher,
				["name", "order_status", "truck_plate", "driver_name", "driver_phone",
				 "destination", "tanggal_muat", "shipper"],
				as_dict=True,
			)
			if r.referred_voucher
			else None
		)
		items.append({
			"inspection": r.name,
			"inspection_id": r.inspection_id,
			"container": container,
			"container_no": r.container_no or c.container_no,
			"principal": c.principal,
			"depot": r.depot or c.depot,
			"eir_date": str(r.eir_date) if r.eir_date else None,
			"ready_since": str(r.modified) if r.modified else None,
			"order_muat": bon.name if bon else None,
			"order_status": bon.order_status if bon else None,
			"destination": bon.destination if bon else None,
			"tanggal_muat": str(bon.tanggal_muat) if bon and bon.tanggal_muat else None,
			"truck_no": (bon.truck_plate if bon else None) or r.truck_no,
			"driver": (bon.driver_name if bon else None) or r.driver,
			"driver_phone": bon.driver_phone if bon else None,
			"shipper": r.shipper or (bon.shipper if bon else None),
		})

	search = (search or "").strip()
	if search and search.lower() != "undefined":
		needle = search.lower()
		items = [
			i for i in items
			if needle in " ".join(
				str(i.get(k) or "") for k in ("container_no", "order_muat", "truck_no", "driver", "inspection_id")
			).lower()
		]
	items.sort(key=lambda i: i.get("ready_since") or "")  # longest wait first
	total = len(items)
	start = cint(start)
	page_length = cint(page_length) or 20
	return {"items": items[start : start + page_length], "total": total}
