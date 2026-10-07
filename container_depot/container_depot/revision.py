"""Revisi Data — correcting a finished order in place (user, 2026-10-06).

Kembalikan ke Draft is the way to UNDO a submit; this is the way to CORRECT one. It is a
single save with no "sedang direvisi" state in between: whoever holds the right edits the
finished order and saves, the status stays exactly where it was, and nothing outside the
record moves — the tank, the gate, the bon, the booking, the other orders. The one thing
that follows the record is its own parts: a changed part line is issued again, as long as the
gudang holds it. Everything is refused once the order is invoiced.

The request side is the same on every menu too, so it lives here: the team's Ajukan Revisi,
Admin Ops' Tolak Revisi, and the answer back to whoever asked.

A menu joins by an entry in ``_SPECS`` and a module that provides:

* ``REVISION_LOCKED`` — fields a revision may never change (what the order IS, and what the
  system wrote when it finished);
* ``revision_invoice(doc)`` — what has invoiced it, or None;
* optionally ``revision_apply(doc, before)`` — what has to happen inside the save (re-issue
  parts, re-price, move a ledger) beyond the field edit itself;
* optionally ``revision_blocker(doc)`` — why Revisi Data is not the way to correct this one
  yet (the booking: no bon yet, so Kembali ke Draft is), or None.

The record is marked by ``doc.flags.revision``, set only here and by a menu's own PWA save
when it was called with ``revise``. Flags never travel in a request payload (Frappe keeps
``flags`` out of ``Document.update``), so a client cannot mark its own save as a revision.
"""

from __future__ import annotations

import importlib

import frappe
from frappe import _, _lt
from frappe.utils import cint

from container_depot.container_depot.container_activity import log_doc_note
from container_depot.container_depot.user_branch import assert_in_user_branch

# right: a DocPerm ptype on the doctype, or "admin_ops" for the non-submittable Repair Order
# (no cancel right to ask about — the M&R desk actions already gate on the role, see
# ess/repairs.py BYPASS_ROLES).
_SPECS = {
	"Inspection": {
		"module": "container_depot.container_depot.eir",
		"right": "cancel",
		"label": _lt("EIR"),
		"answered": "eir_revision_answered",
	},
	"Cleaning Order": {
		"module": "container_depot.container_depot.cleaning",
		"right": "cancel",
		"label": _lt("Cleaning"),
		"answered": "cleaning_revision_answered",
	},
	"Repair Order": {
		"module": "container_depot.container_depot.mr",
		"right": "admin_ops",
		"label": _lt("M&R"),
		"answered": "repair_revision_answered",
	},
	# Revisi Data only once a bon exists (before that Kembali ke Draft is the one way back), and
	# the invoice locks single fields instead of the whole booking: a Cash booking is invoiced
	# before its bon. Desk only.
	"Container Booking": {
		"module": "container_depot.container_depot.doctype.container_booking.container_booking",
		"right": "cancel",
		"label": _lt("Booking"),
		"answered": "booking_revision_answered",
	},
	# Revisi Data on every finished order (user, 2026-10-07). Nothing here is priced, so no
	# invoice lock; the right is the Admin Ops role, like M&R. The bons have their own Revisi
	# Bon (bon_revision.py).
	"Survey Order": {
		"module": "container_depot.container_depot.doctype.survey_order.survey_order",
		"right": "admin_ops",
		"label": _lt("Survey"),
		"requested": "survey_revision_requested",
		"answered": "survey_revision_answered",
	},
	"Leak Check": {
		"module": "container_depot.container_depot.doctype.leak_check.leak_check",
		"right": "admin_ops",
		"label": _lt("Leak Check"),
		"requested": "leak_revision_requested",
		"answered": "leak_revision_answered",
	},
	"Gate Entry": {
		"module": "container_depot.container_depot.doctype.gate_entry.gate_entry",
		"right": "admin_ops",
		"label": _lt("Gate"),
		"requested": "gate_revision_requested",
		"answered": "gate_revision_answered",
	},
}
ADMIN_OPS_ROLES = {"Admin Ops", "System Manager"}


def _spec(doctype: str) -> dict:
	spec = _SPECS.get(doctype)
	if not spec:
		frappe.throw(_("{0} tidak mendukung Revisi Data.").format(doctype))
	return spec


def _hooks(doctype: str):
	return importlib.import_module(_spec(doctype)["module"])


def is_finished(doc) -> bool:
	"""Submitted, or for the non-submittable Repair Order: Completed."""
	if doc.doctype == "Repair Order":
		return doc.get("status") == "Completed"
	if doc.doctype == "Container Booking":
		return doc.docstatus == 1 and doc.get("booking_status") != "Cancelled"
	return doc.docstatus == 1


def has_right(doctype: str, user: str | None = None) -> bool:
	right = _spec(doctype)["right"]
	if right == "admin_ops":
		return not set(frappe.get_roles(user or frappe.session.user)).isdisjoint(ADMIN_OPS_ROLES)
	return bool(frappe.has_permission(doctype, right, user=user))


def invoice_of(doc) -> str | None:
	return _hooks(doc.doctype).revision_invoice(doc)


def blocker_of(doc) -> str | None:
	hooks = _hooks(doc.doctype)
	return hooks.revision_blocker(doc) if hasattr(hooks, "revision_blocker") else None


def locked_message(invoice) -> str:
	return _(
		"Order ini sudah diinvoice ({0}). Batalkan invoice-nya dulu, atau keluarkan order ini "
		"dari invoice."
	).format(invoice)


def state(doc) -> dict:
	"""What the Desk and the PWA may offer on a finished order.

	``{can_revise, can_answer, locked, requested, note}`` — ``locked`` is the invoice that
	froze it; ``can_answer`` (Tolak Revisi) is the right alone, ``can_revise`` also needs no
	``revision_blocker``. Empty for an order that is not finished yet: there is nothing to revise.
	"""
	if not is_finished(doc):
		return {}
	right = has_right(doc.doctype)
	return {
		"can_revise": 1 if right and not blocker_of(doc) else 0,
		"can_answer": 1 if right else 0,
		"locked": invoice_of(doc),
		"requested": cint(doc.get("revision_requested")),
		"note": doc.get("revision_note"),
	}


def _guard_branch(doc) -> None:
	if doc.doctype in ("Container Booking", "Survey Order"):
		return assert_in_user_branch(branch=doc.get("branch"), depot=doc.get("depot"))
	depot = frappe.db.get_value("Container", doc.get("container"), "depot") if doc.get("container") else None
	assert_in_user_branch(depot=depot or doc.get("depot"))


def assert_can_revise(doc) -> None:
	"""Finished, not invoiced, in the user's branch, and the user holds the right."""
	if not is_finished(doc):
		frappe.throw(_("Hanya order yang sudah selesai yang bisa direvisi."))
	if not has_right(doc.doctype):
		frappe.throw(_("Anda tidak berwenang melakukan Revisi Data."), frappe.PermissionError)
	_guard_branch(doc)
	blocker = blocker_of(doc)
	if blocker:
		frappe.throw(blocker)
	invoice = invoice_of(doc)
	if invoice:
		frappe.throw(locked_message(invoice), title=_("Order Terkunci"))


def check(doc) -> None:
	"""The controller's before-save hook for a revision (``doc.flags.revision``).

	Run against the record as it stands in the database, so the edit itself cannot unlock it.
	"""
	before = doc.get_doc_before_save()
	if not before:
		return
	assert_can_revise(before)
	if not is_finished(doc):
		frappe.throw(_("Revisi Data tidak mengubah status order."))
	hooks = _hooks(doc.doctype)
	changed = [f for f in hooks.REVISION_LOCKED if _value(doc, f) != _value(before, f)]
	if changed:
		frappe.throw(_("Revisi Data tidak boleh mengubah: {0}.").format(
			", ".join(_(doc.meta.get_label(f)) for f in changed)
		))
	# The field rules are ours for this save — REVISION_LOCKED above. Only meaningful on a
	# submitted document; the Repair Order lets the flag through its own final-status lock.
	doc.flags.ignore_validate_update_after_submit = True
	if hasattr(hooks, "revision_apply"):
		hooks.revision_apply(doc, before)


def _value(doc, fieldname):
	"""A field's value as the database means it — the Desk form sends dates as strings."""
	df = doc.meta.get_field(fieldname)
	value = doc.get(fieldname)
	return (doc.cast(value, df) if df and value not in (None, "") else value) or None


def after(doc) -> None:
	"""The controller's after-save hook for a revision: say so on the timeline, and answer
	whoever asked for it — the revision IS the answer."""
	log_doc_note(doc.doctype, doc.name, _("Revisi Data oleh {0}.").format(frappe.session.user))
	if cint(frappe.db.get_value(doc.doctype, doc.name, "revision_requested")):
		close_request(doc, done=True)


@frappe.whitelist(methods=["POST"])
def save_revision(doc) -> dict:
	"""Desk "Revisi Data" → Simpan: save the edited form of a finished order in place.

	The Desk form's own Update would hit Frappe's submitted-document rules; this is the same
	save with the revision mark on it. ``doc`` is the whole form, as Frappe's savedocs takes it.
	"""
	data = frappe.parse_json(doc)
	current = frappe.get_doc(data.get("doctype"), data.get("name"))
	assert_can_revise(current)
	edited = frappe.get_doc(data)
	if cint(edited.docstatus) != cint(current.docstatus) or edited.get("status") != current.get("status"):
		frappe.throw(_("Revisi Data tidak mengubah status order."))
	edited.flags.revision = True
	edited.save()
	return {"name": edited.name, "modified": str(edited.modified)}


# --- Ajukan Revisi / Tolak Revisi ----------------------------------------------------
def request(doc, reason: str | None, notify) -> dict:
	"""The team's "Ajukan Revisi" on a finished order: a request, not an edit.

	Refused on an invoiced order — neither way back is open there, so an accepted request
	would only sit as "Revisi Diminta" with nothing anybody could do about it.
	``notify(name, reason=...)`` rings the desk that acts on it.
	"""
	if not is_finished(doc):
		frappe.throw(_("Hanya order yang sudah selesai yang bisa diajukan revisi."))
	_guard_branch(doc)
	invoice = invoice_of(doc)
	if invoice:
		frappe.throw(_(
			"Order ini sudah diinvoice ({0}). Revisi baru bisa diajukan setelah invoice dibatalkan "
			"— hubungi Admin Ops."
		).format(invoice), title=_("Order Terkunci"))
	reason = (reason or "").strip()
	user = frappe.session.user
	note = _("Permintaan revisi oleh {0}").format(user) + (": " + reason if reason else "")
	log_doc_note(doc.doctype, doc.name, note)
	# Raw set_value: the order is finished (submitted, or a locked Completed M&R).
	frappe.db.set_value(
		doc.doctype, doc.name,
		{"revision_requested": 1, "revision_note": note, "revision_requested_by": user},
		update_modified=False,
	)
	return {"success": True, "notified": notify(doc.name, reason=reason), "name": doc.name}


def request_generic(doctype: str, name: str, reason: str | None = None) -> dict:
	"""Ajukan Revisi for a menu whose spec names its own ``requested`` event (Survey Order,
	Leak Check, Gate Entry) — one bell shape for all of them."""
	from container_depot.container_depot.notify import notify_revision_requested

	spec = _spec(doctype)
	if not spec.get("requested"):
		frappe.throw(_("{0} punya tombol Ajukan Revisi sendiri.").format(doctype))
	doc = frappe.get_doc(doctype, name)
	return request(doc, reason, lambda _name, reason=None: notify_revision_requested(doc, spec, reason))


def save_fields(doctype: str, name: str, values, row: str | None = None) -> dict:
	"""The PWA's Revisi Data for menus without an editable form of their own: a few fields,
	saved in place. Only ``REVISION_PWA_FIELDS`` (or ``REVISION_PWA_ROW_FIELDS`` on the child
	row ``row`` of ``REVISION_ROW_TABLE``) are taken from ``values``; the save is the same
	revision save as the Desk's, so ``check`` and the module's ``revision_apply`` still rule."""
	doc = frappe.get_doc(doctype, name)
	assert_can_revise(doc)
	hooks = _hooks(doctype)
	values = frappe.parse_json(values) if isinstance(values, str) else (values or {})
	target, allowed = doc, getattr(hooks, "REVISION_PWA_FIELDS", ())
	if row:
		target = next((r for r in doc.get(hooks.REVISION_ROW_TABLE) or [] if r.name == row), None)
		if not target:
			frappe.throw(_("Baris {0} bukan milik {1}.").format(row, name))
		allowed = hooks.REVISION_PWA_ROW_FIELDS
	for f in allowed:
		if f in values:
			target.set(f, values[f])
	doc.flags.revision = True
	# The right was checked above (assert_can_revise); the field team's own DocPerm is not
	# what a revision answers to.
	doc.flags.ignore_permissions = True
	doc.save()
	return {"name": doc.name, "revision": state(doc)}


@frappe.whitelist(methods=["POST"])
def reject(doctype: str, name: str, reason: str | None = None) -> dict:
	""""Tolak Revisi": answer a request with a no, and say why — to the one who asked."""
	doc = frappe.get_doc(doctype, name)
	if not has_right(doctype):
		frappe.throw(_("Anda tidak berwenang menolak revisi."), frappe.PermissionError)
	_guard_branch(doc)
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Alasan penolakan wajib diisi."))
	if not cint(doc.get("revision_requested")):
		frappe.throw(_("Tidak ada permintaan revisi pada order ini."))
	log_doc_note(doctype, name, _("Revisi ditolak oleh {0}: {1}").format(frappe.session.user, reason))
	close_request(doc, done=False, reason=reason)
	return {"name": name, "revision_requested": 0}


# "Tolak Review": who opened the work (pressed Mulai) — the one it goes back to.
_REVIEW_OPENER = {"Cleaning Order": "assigned_to", "Repair Order": "started_by", "Inspection": "work_started_by"}


@frappe.whitelist(methods=["POST"])
def reject_review(doctype: str, name: str, reason: str | None = None) -> dict:
	""""Tolak Review": Admin Ops turns down work the field sent for review, and says why.

	The order goes back to work exactly as the team's own pull-back does (each module's
	``withdraw_review``: Cleaning / M&R to Dikerjakan, EIR to Draf) — the reviewer's right
	instead of the operator's — and whoever opened the work hears the reason."""
	if doctype not in _REVIEW_OPENER:
		frappe.throw(_("{0} tidak punya tahap review.").format(doctype))
	doc = frappe.get_doc(doctype, name)
	if not has_right(doctype):
		frappe.throw(_("Anda tidak berwenang menolak review."), frappe.PermissionError)
	_guard_branch(doc)
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Alasan penolakan wajib diisi."))
	if doc.docstatus != 0 or doc.get("status") != "Pending Review":
		frappe.throw(_("Hanya order yang menunggu review yang bisa ditolak."))
	_hooks(doctype).withdraw_review(name)
	log_doc_note(doctype, name, _("Review ditolak oleh {0}: {1}").format(frappe.session.user, reason))
	opener = doc.get(_REVIEW_OPENER[doctype])
	if opener:
		from container_depot.container_depot.notify import notify_review_rejected

		notify_review_rejected(doc, opener, _spec(doctype), reason)
	return {"name": name, "status": frappe.db.get_value(doctype, name, "status")}


def close_request(doc, done: bool, reason: str | None = None) -> None:
	user = frappe.db.get_value(doc.doctype, doc.name, "revision_requested_by")
	frappe.db.set_value(
		doc.doctype, doc.name,
		{"revision_requested": 0, "revision_note": None, "revision_requested_by": None},
		update_modified=False,
	)
	if user:
		from container_depot.container_depot.notify import notify_revision_answered

		notify_revision_answered(doc, user, _spec(doc.doctype), done=done, reason=reason)
