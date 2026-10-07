"""Tutup Order — Administrator finishes an order whose work was done outside the app.

The field moved on without the app: a survey row still "Waiting Lowering" on a tank that was
surveyed and loaded weeks ago, a cleaning nobody pressed Submit on. Closing is not a status of
its own (user, 2026-10-06): it FINISHES the order through the same road its own Submit takes,
so a closed order is an ordinary finished one — billed when its charges are filled, listed in
the history, correctable later through Revisi Data, and back to draft only the way any finished
order is (Kembalikan ke Draft, newest only, never once invoiced). What it adds is the
``closed_by_admin`` mark (the blue "Ditutup" pill) and the reason on the timeline.

Two things differ from a hand press:

* **The dates are the order's own** (``plan_date`` / ``survey_date`` / ``eir_date``), not
  today — the work happened then.
* **An order from an earlier visit of its tank finishes on paper only.** Its tank has moved on
  (a later gate-out, or a newer submitted EIR), so a gate-out, an arrival, a status recompute
  or an EIR-Out raised for it would rewrite a visit that is over. The newest order behaves
  exactly like its own Submit, gate-out on the EIR date included.

Parts still leave the gudang like a Submit, and a shortfall refuses the close the same way.
Notifications are muted while closing (a backlog of dozens would otherwise ring every bell) and
the order's own pending prompts are revoked.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, getdate

from container_depot.container_depot.container_activity import log_doc_note

ADMIN = "Administrator"
SURVEY = "Survey Order"
SURVEY_ROW = "Survey Order Tank"


# --------------------------------------------------------------------------- rules
def _require_admin():
	if frappe.session.user != ADMIN:
		frappe.throw(_("Hanya akun Administrator yang bisa menutup order."), frappe.PermissionError)


def is_open(doc) -> bool:
	"""Still unfinished — the only orders Tutup Order is offered on."""
	dt = doc.doctype
	if dt == "Cleaning Order":
		return doc.docstatus == 0 and doc.status != "Cancelled"
	if dt == "Repair Order":
		return doc.status not in ("Completed", "Cancelled", "Rejected")
	if dt in ("Inspection", "Leak Check"):
		return doc.docstatus == 0 and doc.status != "Cancelled"
	if dt in ("Order Bongkar", "Order Muat"):
		# A draft bon has not been issued: there is no trip behind it to close.
		return doc.docstatus == 1 and doc.order_status != "Completed"
	if dt == SURVEY:
		return doc.docstatus < 2 and bool(open_survey_rows(doc.name))
	return False


def open_survey_rows(survey_order: str) -> list:
	return frappe.get_all(
		SURVEY_ROW,
		filters={"parent": survey_order, "parenttype": SURVEY,
			 "status": ["not in", ("Survey Done", "Cancelled")]},
		fields=["name", "container", "container_no", "status"],
		order_by="idx asc",
	)


def _left_after(container: str, created) -> bool:
	"""True when the tank gated out after ``created`` — the order's visit is over."""
	if not (container and created):
		return False
	no = frappe.db.get_value("Container", container, "container_no") or container
	left = frappe.db.get_value(
		"Gate Entry",
		{"container_no": no, "docstatus": ["<", 2], "status": ["!=", "Cancelled"],
		 "gate_out_timestamp": ["is", "set"]},
		"gate_out_timestamp",
		order_by="gate_out_timestamp desc",
	)
	return bool(left and get_datetime(left) > get_datetime(created))


def is_older_visit(doc, container=None) -> bool:
	"""The order belongs to an earlier visit of its tank (see module docstring)."""
	container = container or doc.get("container")
	if _left_after(container, doc.creation):
		return True
	if doc.doctype == "Inspection":
		from container_depot.container_depot.eir import newer_eir

		return bool(newer_eir(doc))
	return False


def _own_datetime(*dates):
	"""The first date given, as a datetime at the start of that day."""
	for d in dates:
		if d:
			return get_datetime(getdate(d))
	return None


# --------------------------------------------------------------------------- per doctype
def _close_cleaning(doc, older):
	when = _own_datetime(doc.plan_date, doc.order_created, doc.creation)
	doc.cleaning_start = doc.cleaning_start or when
	doc.cleaning_end = doc.cleaning_end or max(when, get_datetime(doc.cleaning_start))
	doc.date_of_issue = doc.date_of_issue or doc.plan_date or getdate(doc.cleaning_end)
	doc.status = "Completed"  # a re-clean keeps its own status in before_submit
	doc.closed_by_admin = 1
	doc.submit()


def _close_repair(doc, older):
	from container_depot.container_depot import mr

	when = _own_datetime(doc.plan_date, doc.order_created, doc.creation)
	# finalize_repair keeps a completion it finds; the team tail keeps a start it finds.
	frappe.db.set_value("Repair Order", doc.name, {
		"completion_date": doc.completion_date or when,
		"start_date": doc.start_date or when,
	}, update_modified=False)
	mr.submit_direct(doc.name, note=_("Ditutup oleh Administrator"))
	frappe.db.set_value("Repair Order", doc.name, "closed_by_admin", 1, update_modified=False)


def _close_eir(doc, older):
	if older:
		# Paper only: on_submit would move the tank, the gate and the storage of a visit
		# that is over. It still goes on the tank's history.
		from container_depot.container_depot.container_activity import log_container_activity

		doc.db_set({"docstatus": 1, "status": "Submitted", "closed_by_admin": 1})
		log_container_activity(
			doc.container, "Inspection (EIR)", reference_doctype=doc.doctype,
			reference_name=doc.name, performed_by=doc.get("inspector"),
			summary=_("{0} ditutup Administrator (kunjungan lama)").format(doc.inspection_type),
		)
		return
	doc.closed_by_admin = 1
	doc.submit()


def _close_leak_check(doc, older):
	stamp = doc.recorded_on or doc.creation
	if not older:
		# The gate-out only counts a check recorded since the tank arrived
		# (has_leak_check_this_visit) — and the bon provisions it before the arrival.
		arrived = frappe.db.get_value("Container", doc.container, "in_date")
		if arrived and get_datetime(arrived) > get_datetime(stamp):
			stamp = arrived
	doc.recorded_on = stamp
	doc.closed_by_admin = 1
	doc.flags.closing = True  # no photo: the check was done outside the app
	doc.submit()


def _bon_children(doc) -> list:
	"""The bon's own open orders, in the order they have to finish: the Leak Checks before
	the EIRs (an EIR-Out's gate-out asks for this visit's Leak Check)."""
	out = []
	if doc.doctype == "Order Bongkar":
		out += [("Leak Check", n) for n in frappe.get_all(
			"Leak Check", filters={"order_bongkar": doc.name, "docstatus": 0}, pluck="name")]
	out += [("Inspection", n) for n in frappe.get_all(
		"Inspection",
		filters={"voucher_doctype": doc.doctype, "referred_voucher": doc.name, "docstatus": 0},
		pluck="name", order_by="creation asc")]
	return out


def _close_bon(doc, older):
	# Its EIRs (and the Bon Bongkar's Leak Checks) first, each through its own close — a bon
	# marked Completed over open EIRs would leave the tanks' work behind. Any refusal there
	# refuses the bon too.
	for dt, name in _bon_children(doc):
		if not is_open(frappe.get_doc(dt, name)):
			continue
		doc.flags.closed_children = (doc.flags.closed_children or []) + [
			_close_one(dt, name, doc.flags.close_reason)
		]
	frappe.db.set_value(doc.doctype, doc.name, {"order_status": "Completed", "closed_by_admin": 1},
			    update_modified=False)
	from container_depot.container_depot.doctype.container_booking.container_booking import (
		refresh_bon_status,
	)

	refresh_bon_status(doc.get("booking"))


_CLOSERS = {
	"Cleaning Order": _close_cleaning,
	"Repair Order": _close_repair,
	"Inspection": _close_eir,
	"Leak Check": _close_leak_check,
	"Order Bongkar": _close_bon,
	"Order Muat": _close_bon,
}


def _close_survey_rows(doc, rows):
	from container_depot.container_depot.doctype.survey_order.survey_order import refresh_progress

	when = _own_datetime(doc.get("survey_date"), doc.creation)
	open_rows = {r.name: r for r in open_survey_rows(doc.name)}
	picked = [open_rows[r] for r in rows if r in open_rows]
	if not picked:
		frappe.throw(_("Pilih minimal satu tank yang belum Survey Done."))
	for row in picked:
		frappe.db.set_value(SURVEY_ROW, row.name, {
			"status": "Survey Done",
			"lowered_on": frappe.db.get_value(SURVEY_ROW, row.name, "lowered_on") or when,
			"lowered_by": frappe.db.get_value(SURVEY_ROW, row.name, "lowered_by") or ADMIN,
			"surveyed_on": when,
			"surveyed_by": ADMIN,
			"closed_by_admin": 1,
		}, update_modified=False)
		if not _left_after(row.container, doc.creation):
			# The newest visit: tie its EIR-Out to the row, as Selesai Survey does.
			try:
				from container_depot.container_depot.eir import provision_eir_out_for_survey

				eir_out = provision_eir_out_for_survey(row.name)
				if eir_out:
					frappe.db.set_value(SURVEY_ROW, row.name, "eir_out", eir_out, update_modified=False)
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"provision EIR-Out for closed survey tank {row.name}")
	refresh_progress(doc.name)
	return picked


def _followups(doc, before) -> list:
	"""Orders the close itself raised — a submitted dirty / damaged EIR-In files a Cleaning
	Order or a draft M&R, exactly as its own Submit would. They are new work, so they stay
	open; they are reported instead of being left for somebody to stumble on."""
	if doc.doctype != "Inspection" or doc.get("inspection_type") != "EIR-In":
		return []
	return [
		f"{dt} {n}" for dt in ("Cleaning Order", "Repair Order")
		for n in frappe.get_all(dt, filters={"container": doc.container, "creation": [">=", before]},
					pluck="name")
	]


# --------------------------------------------------------------------------- entry points
@frappe.whitelist()
def close_order(doctype: str, name: str, reason: str, rows=None) -> dict:
	"""Finish one order (Survey Order: the picked tank ``rows``) as described above."""
	_require_admin()
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Alasan wajib diisi."))
	if doctype != SURVEY and doctype not in _CLOSERS:
		frappe.throw(_("{0} tidak bisa ditutup lewat Tutup Order.").format(doctype))
	muted = frappe.flags.depot_mute_notify
	frappe.flags.depot_mute_notify = True
	try:
		return _close_one(doctype, name, reason, rows)
	finally:
		frappe.flags.depot_mute_notify = muted


def _close_one(doctype, name, reason, rows=None) -> dict:
	doc = frappe.get_doc(doctype, name)
	if not is_open(doc):
		frappe.throw(_("{0} {1} sudah selesai atau dibatalkan.").format(_(doctype), name))
	started = frappe.utils.now_datetime()
	if doctype == SURVEY:
		rows = frappe.parse_json(rows) if isinstance(rows, str) else (rows or [])
		picked = _close_survey_rows(doc, rows)
		containers = [r.container for r in picked]
		what = ", ".join(r.container_no or r.container for r in picked)
	else:
		doc.flags.close_reason = reason
		_CLOSERS[doctype](doc, is_older_visit(doc))
		containers = [doc.get("container")] if doc.get("container") else []
		what = None

	from container_depot.container_depot.container_status import recompute_availability
	from container_depot.container_depot.notify import revoke

	revoke(doctype, name)
	for c in containers:
		# Visit-scoped (container_open_orders): an older order's close changes nothing here.
		recompute_availability(c)
	msg = _("Ditutup oleh Administrator: {0}").format(reason)
	if what:
		msg = _("Tank {0} ditutup oleh Administrator: {1}").format(what, reason)
	log_doc_note(doctype, name, msg)
	return {
		"doctype": doctype, "name": name, "closed": True,
		"children": doc.flags.closed_children or [],
		"created": _followups(doc, started),
	}


# The order a backlog has to be finished in. Each step waits on the ones before it: an EIR-In
# raises the tank's cleaning / M&R; an EIR-Out's gate-out wants the survey, this visit's Leak
# Check and no open cleaning / M&R; a bon completes itself once its EIRs are in.
_STEPS = (
	("Inspection", {"inspection_type": "EIR-In"}),
	(SURVEY, {}),
	("Leak Check", {}),
	("Cleaning Order", {}),
	("Repair Order", {}),
	("Inspection", {"inspection_type": "EIR-Out"}),
	("Order Bongkar", {}),
	("Order Muat", {}),
)


def stale_orders(before: str, confirm=0, reason: str | None = None) -> dict:
	"""Close every still-open order created before ``before`` — a backlog clean-up.

	``bench execute container_depot.container_depot.closing.stale_orders --kwargs
	'{"before": "2026-09-23"}'`` is a REHEARSAL: every close really runs, in the order above,
	and the whole lot is rolled back at the end — so "would close" means its submit went
	through, and every refusal (short stock, an EIR-Out with no bon) is listed with its reason.
	``"confirm": 1, "reason": "..."`` runs the same thing and keeps each close that succeeded.
	"""
	frappe.set_user(ADMIN)
	confirm = cint(confirm)
	reason = reason or _("Penutupan order lama")
	out = []
	frappe.flags.depot_mute_notify = True
	try:
		for dt, extra in _STEPS:
			for name in frappe.get_all(
				dt, filters={"creation": ["<", before], "docstatus": ["<", 2], **extra},
				pluck="name", order_by="creation asc",
			):
				doc = frappe.get_doc(dt, name)
				if not is_open(doc):
					continue  # closed by an earlier step (a bon's EIRs, a bon by its last EIR)
				row = {"doctype": dt, "name": name, "container": doc.get("container"),
				       "status": doc.get("status") or doc.get("order_status")}
				rows = [r.name for r in open_survey_rows(name)] if dt == SURVEY else None
				frappe.db.savepoint("close_one")
				try:
					res = _close_one(dt, name, reason, rows)
					row["result"] = "closed" if confirm else "would close"
					for k in ("children", "created"):
						if res.get(k):
							row[k] = [f"{c['doctype']} {c['name']}" if isinstance(c, dict) else c
								  for c in res[k]]
					if confirm:
						frappe.db.commit()
				except Exception as e:
					frappe.db.rollback(save_point="close_one")
					row["result"] = f"refused: {frappe.utils.strip_html(str(e))}"
				out.append(row)
				print(row)
	finally:
		frappe.flags.depot_mute_notify = False
		if not confirm:
			frappe.db.rollback()
	summary = {}
	for r in out:
		key = f"{r['doctype']}: {r['result'].split(':')[0]}"
		summary[key] = summary.get(key, 0) + 1
	return summary
