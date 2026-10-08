"""The "Wajibkan Semua Order" switch (Depot Operation Settings): which orders must be finished
before a tank may leave.

ON (default) is the full sequence. OFF keeps only the backbone mandatory — Container Booking,
bon, gate, EIR-In and payment — and lets the rest wait (user, 2026-10-02: the first
trial week, field teams skipped orders and the tanks after them stuck behind the system).

Every place the switch decides something reads it from here:

* :func:`blocking_orders` — the open work that holds a tank: the bon muat
  (``OrderMuat._validate_no_open_work``), the gate-out (``gate.mark_gate_out``), the Gate PWA
  panel and the "menahan gate-out" count on the booking. OFF = only a draft EIR-In holds.
* ``Inspection.before_submit`` — an EIR-Out waits for its tank's survey, only when ON.

The EIR-Out and the Leak Check never hold the gate, whatever the switch says (2026-10-08):
the bon muat is the gate-out and they only record the tank's condition.

What OFF never does: change the status of an order. A skipped survey, Leak Check, cleaning or
M&R stays exactly as it was, open, finishable later, and listed under its own booking.
"""

from __future__ import annotations

import frappe

SETTINGS = "Depot Operation Settings"
_CACHE_KEY = "depot_enforce_all_orders"


def enforce_all() -> bool:
	"""True unless the switch was deliberately saved off — a site that never opened the
	settings keeps every order mandatory, exactly as before the switch existed."""
	cached = getattr(frappe.local, _CACHE_KEY, None)
	if cached is None:
		try:
			cached = not frappe.db.sql(
				"SELECT 1 FROM `tabSingles` WHERE doctype = %s AND field = 'enforce_all_orders' AND value = '0'",
				SETTINGS,
			)
		except Exception:
			cached = True  # doctype not synced yet (mid-migrate): behave as before it existed
		setattr(frappe.local, _CACHE_KEY, cached)
	return cached


def ensure_defaults():
	"""Store the shipped default (ON) once. Never on a later migrate: that would switch a site
	that deliberately turned it off back on."""
	if frappe.db.sql(
		"SELECT 1 FROM `tabSingles` WHERE doctype = %s AND field = 'enforce_all_orders' LIMIT 1", SETTINGS
	):
		return
	frappe.db.set_single_value(SETTINGS, "enforce_all_orders", 1)
	clear_cache()


def clear_cache():
	if hasattr(frappe.local, _CACHE_KEY):
		delattr(frappe.local, _CACHE_KEY)


def blocking_orders(container: str) -> list[dict]:
	""":func:`container_status.container_open_orders` minus what the switch lets wait.

	OFF keeps only the draft EIR-In: it is one of the mandatory orders, so it still holds."""
	from container_depot.container_depot.container_status import container_open_orders

	orders = container_open_orders(container)
	if enforce_all():
		return orders
	return [o for o in orders if o["doctype"] == "Inspection"]
