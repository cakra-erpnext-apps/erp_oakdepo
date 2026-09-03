"""The finance master switch: run the depot with or without invoicing.

The depot's operational side — gate, EIR, cleaning, M&R, bon — has no
business dependency on accounting. Invoicing grew alongside it, and every place the two
meet is listed here so it can be turned off in one move:

* **nothing is created.** Every Sales Invoice in this app is born in
  :func:`invoicing.create_draft_sales_invoice` (there is no other ``new_doc("Sales
  Invoice")`` anywhere), so refusing there covers per-transaction invoices, consolidated
  billing and the monthly scheduler alike.
* **no SUBMIT is blocked.** A Cash booking's submit no longer waits on an invoice that will
  never exist, so a booking can be confirmed and its gate codes issued with nobody billed.

What deliberately does NOT step aside any more (changed 2026-09-03): **the payment gate on a
bon, a gate-in and a gate-out**. It used to, on the reasoning that with no Sales Invoice the
``payment_status`` field is derived from nothing and means nothing. That stopped being true
when :func:`container_booking.set_payment_status` gave an admin a manual Paid / Unpaid switch
for exactly this mode — the field became somebody's deliberate statement that the money did or
did not arrive, and a depot running without invoicing has no other answer to read. See
``order_generation.payment_block_reason``.

What deliberately does NOT change when finance is off:

* **Prices are still calculated and recorded.** Charge lines, ``total_cost`` and
  ``billing_status = Unbilled`` all keep working, which is what makes "operations now,
  invoices later" possible: switch finance on and the consolidated run can bill the work
  that already happened. Stop recording prices and there is nothing left to bill.
* **Existing invoices are untouched.** The switch gates *creation*, never the sync and
  rollback paths — a Sales Invoice raised while finance was on keeps its booking in step,
  and cancelling it still unlinks cleanly. Turning finance off is not a way to void
  receivables; it only stops new ones.

``finance_start_date`` guards the other end. A sweep with no window reaches back to
2000-01-01, so switching finance on after months of operating would otherwise let one
click raise a single enormous invoice for the entire backlog. The date is the lower bound
for consolidated billing.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, getdate

SETTINGS = "Depot Finance Settings"


_CACHE_KEY = "depot_finance_enabled"


def is_enabled() -> bool:
	"""True when the site raises invoices at all.

	Defaults to **enabled** whenever the setting has never been stored: an app update must
	never silently switch a running site's invoicing off. Turning it off is a deliberate act,
	and only an actually-saved 0 counts as one — Frappe casts an unsaved Check to 0, which
	otherwise reads exactly like a deliberate "off".

	Called from validate on nearly every operational save, so the answer is cached for the
	request (``frappe.local`` is per request — no stale value can outlive it).
	"""
	cached = getattr(frappe.local, _CACHE_KEY, None)
	if cached is not None:
		return cached
	enabled = _read_enabled()
	setattr(frappe.local, _CACHE_KEY, enabled)
	return enabled


def _read_enabled() -> bool:
	try:
		if cint(frappe.db.get_single_value(SETTINGS, "enable_finance")):
			return True
		# Falsy: either stored as 0, or never stored at all. Only the former is a decision.
		return not frappe.db.sql(
			"SELECT 1 FROM `tabSingles` WHERE doctype = %s AND field = %s LIMIT 1",
			(SETTINGS, "enable_finance"),
		)
	except Exception:
		# The doctype isn't synced yet (first install / mid-migrate). Behave as before it
		# existed: invoicing on.
		return True


def ensure_defaults():
	"""Store the shipped default once, so the setting is readable rather than inferred.

	Seeded only when absent — writing it on every migrate would switch finance back on
	under a site that had deliberately turned it off.
	"""
	if frappe.db.sql(
		"SELECT 1 FROM `tabSingles` WHERE doctype = %s AND field = %s LIMIT 1",
		(SETTINGS, "enable_finance"),
	):
		return
	frappe.db.set_single_value(SETTINGS, "enable_finance", 1)
	clear_cache()


def clear_cache():
	"""Drop the per-request cache after the setting is saved."""
	if hasattr(frappe.local, _CACHE_KEY):
		delattr(frappe.local, _CACHE_KEY)
	cache = getattr(frappe.db, "value_cache", None)
	if isinstance(cache, dict):
		cache.pop(SETTINGS, None)


def start_date():
	"""Earliest date the depot bills for, or None to bill the whole history."""
	if not is_enabled():
		return None
	value = frappe.db.get_single_value(SETTINGS, "finance_start_date")
	return getdate(value) if value else None


def require_enabled(action: str = None):
	"""Refuse an explicitly financial action while finance is off.

	Used by the buttons a user presses *to bill something* — those must say why nothing
	happened rather than fail quietly. The automatic paths just no-op instead.
	"""
	if is_enabled():
		return
	frappe.throw(
		_("Finance sedang dimatikan — {0} tidak tersedia. Aktifkan di <b>Depot Finance Settings</b>.").format(
			action or _("invoicing")
		)
	)
