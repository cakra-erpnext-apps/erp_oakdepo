"""Where does a notification take you, and may this user go there?

A notification that cannot be acted on is barely a notification. Until now the bell told an
operator that TANK0000123 was ready to leave and then left them to find it themselves; the
Desk bell did route, but straight into Frappe's "Insufficient Permission" page whenever the
recipient could not read the document.

One table answers it for all three surfaces — the PWA bell, the Desk bell, and the Web Push
banner — because three tables would drift and the drift would be invisible until an operator
landed on the wrong screen.

WHY THE EVENT, NOT JUST THE DOCTYPE
-----------------------------------
The doctype alone is not enough to say where to go. ``Order Muat`` is the subject of four
different events that belong on three different screens: a bon was generated (Gate), an EIR-Out
came due (EIR worklist), or a tank is held after its EIR-Out (EIR history).
Routing on doctype would send two notifications out of three to the wrong menu.

So ``notify()`` stamps the event key onto the Notification Log (``depot_event``, a custom
field) and this module keys off that. Rows written before that field existed fall back to the
doctype map, which is right often enough to be useful and never claims more than it knows.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
No route is invented for a document the PWA has no screen for — a Sales Invoice, a Depot
Contract, a Container Booking. Those return no PWA route at all rather than dumping the
operator on the home screen, which would look like the tap failed. They still route on the
Desk, where those documents live.
"""

from __future__ import annotations

import frappe
from frappe import _

from container_depot.ess.context import _MENU, has_field_role

# Longest-prefix wins, so `/survey-position/history` resolves to surveyPos and never collides
# with `/position-fix`. Built from _MENU so a new menu needs no second registration here.
_MENU_BY_ROUTE = sorted(
	((route, key, dt, ptype) for key, route, dt, ptype in _MENU),
	key=lambda r: -len(r[0]),
)


def menu_for_route(route: str):
	"""The _MENU entry that owns ``route``, or None for a route outside the PWA menus."""
	path = (route or "").split("?")[0].rstrip("/")
	for prefix, key, dt, ptype in _MENU_BY_ROUTE:
		if path == prefix or path.startswith(prefix + "/"):
			return key, dt, ptype
	return None


def _state(doctype, name, fields):
	"""Minimal read of the fields a route decision needs. None when the doc is gone."""
	try:
		return frappe.db.get_value(doctype, name, fields, as_dict=True)
	except Exception:
		# An unknown field (doctype changed under us) must not take the whole bell down.
		return None


# --- per-document routing ----------------------------------------------------
#
# Each returns a PWA path, or None when this document has no PWA screen.
#
# The finished/unfinished split matters: a worklist only lists open work, so sending someone
# to `/cleaning?o=X` for an order that was completed yesterday lands them on a form that
# refuses to save. Finished work belongs in Riwayat, which takes an `?open=` deep link.


def _eir(doctype, name):
	st = _state("Inspection", name, ["docstatus", "status", "inspection_type"])
	if not st:
		return None
	if st.docstatus == 1 or st.status == "Pending Review":
		return f"/eir/history?open={name}"
	return f"/eir?e={name}&t={'out' if st.inspection_type == 'EIR-Out' else 'in'}"


def _eir_worklist(doctype, name):
	"""The EIR screen, for events whose document is NOT an Inspection.

	`eir_out_hold` fires on the **Order Muat** (or the Container) behind a held tank, so there
	is no Inspection name to deep-link to — same shape as `_eir_pending`.
	"""
	return "/eir/history"


def _cleaning(doctype, name):
	st = _state("Cleaning Order", name, ["docstatus", "status"])
	if not st:
		return None
	# "Pending Review" is field-done: the worklist no longer carries it and the form refuses
	# a save, so the reviewer is sent to the read-only detail — same rule as the EIR route.
	if st.docstatus == 1 or st.status in ("Completed", "Cancelled", "Pending Review"):
		return f"/cleaning/history?open={name}"
	return f"/cleaning?o={name}"


def _repair(doctype, name):
	st = _state("Repair Order", name, ["status"])
	if not st:
		return None
	if st.status in ("Completed", "Cancelled", "Rejected"):
		return f"/mr/history?open={name}"
	return f"/mr?o={name}"


def _survey(doctype, name):
	"""Only valid when the notified document IS a Container Position Survey."""
	st = _state("Container Position Survey", name, ["status"])
	if not st:
		return None
	# The two halves of this workflow are two different menus held by two different teams.
	# Deep-linked (`?s=`) the way cleaning and M&R are: the worklist can be long, and a bell
	# that only opens the list still leaves the operator hunting for the tank it just named.
	if st.status == "Pending Survey":
		return f"/survey-position?s={name}"
	if st.status == "Surveyed":
		return f"/position-fix?s={name}"
	return f"/survey-position/history?open={name}"


def _eir_pending(doctype, name):
	"""The EIR worklist (open drafts), for events whose document is NOT an Inspection.

	`order_muat_survey` fires on an **Order Muat**: EIR-Out drafts have just been provisioned
	for its tanks and there is no single Inspection to deep-link to. It used to resolve to
	`/survey-position` — the Container Position Survey menu, a different feature worked by a
	different team — so the one event that says "EIR-Out wajib sebelum tank boleh dimuat"
	pointed away from the EIR screen. `/eir` is where those drafts are.
	"""
	return "/eir"


def _gate_history(doctype, name):
	return f"/gate/history?open={name}"


def _gate(doctype, name):
	# No deep link: the gate screen is driven by scanning a code, not by opening a record.
	return "/gate"


def _monitor(doctype, name):
	return "/monitor"


def _none(doctype, name):
	"""Documents the PWA has no screen for. Desk-only, and honest about it."""
	return None


# Event key → route. This is the authoritative map; see the module docstring for why the
# event and not the doctype decides.
_BY_EVENT = {
	"eir_submitted": _eir,
	"eir_pending_review": _eir,
	"cleaning_pending_review": _cleaning,
	"cleaning_order_created": _cleaning,
	"repair_order_created": _repair,
	"repair_order_service_setup": _repair,
	"repair_order_forwarded": _repair,
	"repair_order_pending_approval": _repair,
	"repair_order_decided": _repair,
	"repair_revision_requested": _repair,
	"eir_revision_requested": _eir,
	"cleaning_revision_requested": _cleaning,
	"order_gate_in": _gate,
	"order_gate_out": _gate,
	"order_muat_survey": _eir_pending,
	"position_survey_pending": _survey,
	"position_surveyed": _survey,
	"position_confirmed": _survey,
	"eir_out_hold": _eir_worklist,
	"gate_out": _gate_history,
	"booking_created": _none,
	"booking_submitted": _none,
	"contract_created": _none,
	"contract_activated": _none,
	"invoice_submitted": _none,
}

# Fallback for logs written before `depot_event` existed. Order Muat and Container are
# deliberately absent: without the event they are genuinely ambiguous, and guessing would
# send an operator to the wrong menu with no way to tell.
_BY_DOCTYPE = {
	"Inspection": _eir,
	"Cleaning Order": _cleaning,
	"Repair Order": _repair,
	"Container Position Survey": _survey,
	"Gate Entry": _gate_history,
	"Order Bongkar": _gate,
	"Container": _monitor,
}


def route_for(doctype: str, name: str, event: str | None = None):
	"""The PWA path for this notification, or None when the PWA has no screen for it.

	Pure routing — says nothing about whether the caller may go there. ``resolve`` adds that.
	"""
	if not doctype or not name:
		return None
	# A known event always wins, including when it maps to `_none` (Desk-only). Only an
	# unknown or absent event falls through to the doctype guess.
	resolver = _BY_EVENT[event] if event in _BY_EVENT else _BY_DOCTYPE.get(doctype)
	if resolver is None:
		return None
	try:
		return resolver(doctype, name)
	except Exception:
		frappe.log_error(title="Notification route failed", message=frappe.get_traceback())
		return None


def desk_route_for(doctype: str, name: str):
	"""The Desk form URL. Every notified doctype has one — the Desk shows everything."""
	if not doctype or not name:
		return None
	return f"/app/{frappe.scrub(doctype).replace('_', '-')}/{frappe.utils.quoted(name)}"


# --- permission --------------------------------------------------------------


def can_open_menu(route: str, user: str = None) -> bool:
	"""May this user open the PWA menu that owns ``route``?

	Same table and the same test as the tile filter and the router guard
	(``ess.context.allowed_menu``), so a notification can never be a way into a menu the
	operator does not otherwise have.
	"""
	entry = menu_for_route(route)
	if not entry:
		return False
	_key, doctype, ptype = entry
	return has_field_role(user) and frappe.has_permission(doctype, ptype, user=user)


def can_read_doc(doctype: str, name: str, user: str = None) -> bool:
	"""Document-level read check — the one that catches per-doc rules, not just roles."""
	try:
		return bool(frappe.has_permission(doctype, "read", doc=name, user=user))
	except frappe.DoesNotExistError:
		return False
	except Exception:
		# Fail CLOSED. An unreadable permission answer is not a licence to navigate.
		frappe.log_error(title="Notification permission check failed", message=frappe.get_traceback())
		return False


def resolve(doctype: str, name: str, event: str | None = None, user: str = None) -> dict:
	"""Where this notification goes, on BOTH surfaces, and why not when it does not.

	The two surfaces are answered separately, and keeping them apart is the whole point of
	this function. The PWA needs the menu gate — a notification must never be a side door
	into a menu the operator does not otherwise have. The Desk does not: an Admin Ops user
	with no field role has every right to open the document on the Desk, and running them
	through the PWA menu check would block a link that has always worked.

	So there are two verdicts:

		allowed       — PWA: has the menu, and may read the document
		desk_allowed  — Desk: may read the document

	Refusals carry a reason and a message rather than raising. A notification you cannot act
	on is a normal thing to receive; being told why is the useful part.
	"""
	# Not every Notification Log points at a document — Frappe raises plain "Alert" and
	# "Share" rows with neither. Those are text, and text is where they stop.
	if not doctype or not name:
		return _refusal("no_document", _("Notifikasi ini tidak menunjuk ke dokumen."))
	if not frappe.db.exists(doctype, name):
		return _refusal("missing", _("Dokumennya sudah tidak ada."))

	readable = can_read_doc(doctype, name, user)
	desk_route = desk_route_for(doctype, name)
	out = {
		"doctype": doctype,
		"name": name,
		"desk_route": desk_route if readable else None,
		"desk_allowed": readable,
		"desk_message": None if readable else _("Anda tidak punya izin membuka dokumen ini."),
	}

	route = route_for(doctype, name, event)
	if not route:
		out.update(allowed=False, reason="no_screen", message=_("Data ini hanya bisa dibuka di ERPNext (Desk)."))
	elif not can_open_menu(route, user):
		out.update(allowed=False, reason="no_menu", message=_("Anda tidak punya akses ke menu ini."))
	elif not readable:
		out.update(allowed=False, reason="no_permission", message=out["desk_message"])
	else:
		out.update(allowed=True, reason=None, message=None, route=route)
	return out


def _refusal(reason: str, message: str) -> dict:
	"""A notification that leads nowhere on either surface."""
	return {
		"allowed": False,
		"reason": reason,
		"message": message,
		"desk_allowed": False,
		"desk_route": None,
		"desk_message": message,
	}


def looks_openable(doctype: str, name: str, event: str | None = None, user: str = None) -> bool:
	"""Cheap "is this row worth showing as tappable?" for the notification list.

	Role-level only — no document is loaded, because the list refreshes every minute and
	twenty document reads per poll is a real cost for a cosmetic affordance. The expensive,
	authoritative check runs once, on the tap, in ``resolve``.
	"""
	route = route_for(doctype, name, event)
	return bool(route) and can_open_menu(route, user)
