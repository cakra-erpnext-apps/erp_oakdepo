"""Revisi Bon — correct an issued bon from the Gate PWA or the Desk form (user, 2026-10-07).

A bon is a read-only COPY of its booking lines (``order_generation.mirror_booking_lines``), so
a correction to a tank's truck, driver, parties, condition or cargo is written to the booking
line and copied back by the sync that already exists (``sync_lines_to_bons``: the bon, its
draft EIRs, the gate log of a visit still open, the master's EMKL/Shipper). The bon's own
fields — its date and the ex-vessel / destination — are written on the bon. Both surfaces use
the Generate Bon form itself (public/js/bon_revision.js, GateEntry.vue step 2): same fields,
same required ones, shared fields onto every tank of the bon.

User decisions: every field, by anyone who holds the Gate menu (or may write a booking on
the Desk), and **for as long as the bon exists** — a Completed bon too, which the ordinary
line edit refuses (``assert_lines_editable``). Two things are still refused:

* a voided bon (it is no longer the record of anything);
* moving Tanggal Bongkar / Tanggal Muat once the visit's storage is on an invoice — the day
  in/out is what that invoice counted (``visit_dates``).

Not here: which tank is on the bon (void it and issue a new one), and "Pakai EIR" (locked
once the tank is on a bon, ``no_eir.assert_switch_locked``).
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import getdate

LINE_FIELDS = ("truck_plate", "driver", "driver_phone", "ro", "remarks", "emkl", "shipper", "condition", "cargo")
HEADER_FIELDS = {
	"Order Bongkar": ("tanggal_bongkar", "ex_vessel"),
	"Order Muat": ("tanggal_muat", "destination"),
}
DATE_FIELD = {"Order Bongkar": "tanggal_bongkar", "Order Muat": "tanggal_muat"}


def _guard() -> None:
	"""The Gate menu (Security on the PWA), or write on Container Booking (Admin Ops and up)."""
	from container_depot.ess.guard import require_menu

	try:
		require_menu("gate")
		return
	except frappe.PermissionError:
		frappe.clear_last_message()
	if not frappe.has_permission("Container Booking", "write"):
		frappe.throw(_("Anda tidak punya akses merevisi bon."), frappe.PermissionError)


def _bon(doctype: str, name: str):
	if doctype not in HEADER_FIELDS:
		frappe.throw(_("Bukan bon: {0}").format(doctype))
	doc = frappe.get_doc(doctype, name)
	if doc.docstatus != 1:
		frappe.throw(
			_("Bon {0} belum terbit atau sudah di-void — yang direvisi di sini hanya bon terbit.").format(name)
		)
	from container_depot.container_depot.user_branch import assert_in_user_branch

	assert_in_user_branch(branch=doc.get("branch"))
	return doc


def _lines(doc) -> list:
	codes = [r.booking_code for r in doc.containers or [] if r.booking_code]
	if not codes or not doc.booking:
		return []
	return frappe.get_all(
		"Container Booking Item",
		filters={"parenttype": "Container Booking", "parent": doc.booking, "booking_code": ["in", codes]},
		fields=["name", "container", "container_no", "booking_code", *LINE_FIELDS],
		order_by="idx asc",
	)


def _blank(v):
	return None if v in (None, "") else v


@frappe.whitelist(methods=["GET"])
def get_bon_revision(doctype: str, name: str) -> dict:
	"""The bon's revisable values: its own fields and one row per tank (its booking line)."""
	_guard()
	doc = _bon(doctype, name)
	return {
		"doctype": doctype,
		"name": doc.name,
		"booking": doc.booking,
		"order_status": doc.order_status,
		"header": {f: doc.get(f) for f in HEADER_FIELDS[doctype]},
		"lines": _lines(doc),
	}


@frappe.whitelist(methods=["POST"])
def save_bon_revision(doctype: str, name: str, header=None, lines=None) -> dict:
	"""Apply a revision. ``header`` = {field: value}; ``lines`` = [{name, field: value…}]."""
	_guard()
	doc = _bon(doctype, name)
	header = json.loads(header) if isinstance(header, str) else (header or {})
	lines = json.loads(lines) if isinstance(lines, str) else (lines or [])
	changes = []

	# Tank lines → the booking; the existing sync copies them back onto the bon.
	mine = {r.name: r for r in _lines(doc)}
	booking = frappe.get_doc("Container Booking", doc.booking) if doc.booking else None
	moved = False
	for row in lines:
		if row.get("name") not in mine:
			frappe.throw(_("Baris {0} bukan milik bon {1}.").format(row.get("name"), doc.name))
		line = next(l for l in booking.items if l.name == row["name"])
		for f in LINE_FIELDS:
			if f in row and _blank(row[f]) != _blank(line.get(f)):
				changes.append(f"{line.container_no} · {f}: {line.get(f) or '-'} → {row[f] or '-'}")
				line.set(f, row[f])
				moved = True
	if moved:
		booking.flags.bon_revision = True  # a Completed bon too (assert_lines_editable)
		booking.flags.ignore_permissions = True
		booking.save()

	# The bon's own fields.
	own = {f: header[f] for f in HEADER_FIELDS[doctype] if f in header and _blank(header[f]) != _blank(doc.get(f))}
	date_field = DATE_FIELD[doctype]
	if date_field in own:
		if not own[date_field]:
			frappe.throw(_("Tanggal bon tidak boleh kosong."))
		own[date_field] = getdate(own[date_field])
		if own[date_field] == getdate(doc.get(date_field)):
			own.pop(date_field)
		else:
			_assert_storage_not_invoiced(doc)
	if own:
		for f, v in own.items():
			changes.append(f"{f}: {doc.get(f) or '-'} → {v or '-'}")
		# Written straight to the row and the followers run by hand: a full save would re-run
		# the bon's validate, which judges where the tank stands NOW (a Completed Tank Out bon's
		# tank has left) — not what a correction to its paperwork is about.
		frappe.db.set_value(doctype, doc.name, own)
		doc.reload()
		doc.run_method("on_update_after_submit")
		if "ex_vessel" in own:
			from container_depot.container_depot import last_orders

			last_orders.refresh_for_doc(doc)

	if changes:
		frappe.get_doc({
			"doctype": "Comment", "comment_type": "Info",
			"reference_doctype": doctype, "reference_name": doc.name,
			"content": _("Revisi Bon oleh {0}:<br>{1}").format(
				frappe.utils.get_fullname(frappe.session.user), "<br>".join(frappe.utils.escape_html(c) for c in changes)
			),
		}).insert(ignore_permissions=True)
	out = get_bon_revision(doctype, doc.name)
	out["changed"] = len(changes)
	return out


def _assert_storage_not_invoiced(doc) -> None:
	"""The bon's date is the day in / out its visit's storage was counted from (visit_dates)."""
	filters = (
		{"order_doctype": "Order Bongkar", "order_ref": doc.name}
		if doc.doctype == "Order Bongkar" else {"order_muat": doc.name}
	)
	gates = frappe.get_all("Gate Entry", filters={**filters, "status": ["!=", "Cancelled"]}, pluck="name")
	billed = gates and frappe.db.get_value(
		"Storage Charge",
		{"gate_entry": ["in", gates], "sales_invoice": ["is", "set"]},
		["sales_invoice", "container"], as_dict=True,
	)
	if billed:
		frappe.throw(
			_("Storage tank {0} kunjungan ini sudah masuk invoice {1} — tanggal bon tidak bisa diubah. "
			  "Batalkan invoice-nya dulu.").format(billed.container, billed.sales_invoice),
			title=_("Sudah Diinvoice"),
		)
