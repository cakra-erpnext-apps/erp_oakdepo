"""The security layer for the PWA.

Menu filtering in Home.vue and the router guard are tidiness — a Cashier who never sees
the M&R tile can still POST to ``container_depot.ess.repairs.mr_start`` with curl. This
module is what actually says no, and every ESS endpoint calls it first.

It reads the same ``_MENU`` table as ``ess.context.allowed_menu``, so there is one
definition of "may this user work the cleaning queue" and the UI cannot drift out of step
with what the server enforces.

WHY THE FIELD-ROLE CHECK IS NOT HERE
------------------------------------
The handoff's sketch also required ``_has_field_role()``. That would break the Desk:
``container_depot/doctype/repair_order/repair_order.js`` and ``inspection/inspection.js`` call
eight of these very endpoints (mr_decision, mr_publish_to_owner, set_repair_status,
eir_prefill, …), and the office roles that use them — Admin Ops above all — hold no field
role by definition. The owner-approval workflow runs from both surfaces.

Nothing is lost by dropping it. The field-role flag decides what the PWA *shows*
(``get_menu`` still requires it, so an office user's /depot is empty); DocPerm decides
what anyone *may do*, on either surface. Cashier is still refused ``gate_out`` because
Cashier has Gate Entry read, not write — the DocPerm is the teeth, not the flag.
"""

from __future__ import annotations

import frappe
from frappe import _

from container_depot.api import _require_authenticated_user
from container_depot.ess.context import _MENU


def require_menu(menu_key: str) -> None:
	"""Reject a caller with no right to this menu. Raises ``frappe.PermissionError``.

	An unknown ``menu_key`` is a coding error and is refused rather than waved through:
	failing closed is the only safe default for an authorisation check.
	"""
	_require_authenticated_user()
	entry = next((m for m in _MENU if m[0] == menu_key), None)
	if entry is None:
		frappe.throw(_("Menu tidak dikenal: {0}").format(menu_key), frappe.PermissionError)
	_key, _route, doctype, ptype = entry
	if not frappe.has_permission(doctype, ptype):
		frappe.throw(_("Anda tidak punya akses menu ini."), frappe.PermissionError)
