"""ESS — the PWA half of Revisi Data's request side (``container_depot/revision.py``).

Ajukan Revisi stays on each menu's own endpoint (it carries the menu's own notification);
Tolak Revisi is the same act on every menu, so it is one endpoint here, gated by the menu that
owns the order.
"""

from __future__ import annotations

import frappe

from container_depot.container_depot import revision
from container_depot.ess.guard import require_menu
from container_depot.ess.idempotency import guarded


def _require(doctype, name) -> None:
	if doctype == "Inspection":
		require_menu("eir")
	elif doctype == "Cleaning Order":
		require_menu("cleaning")
	elif doctype == "Repair Order":
		from container_depot.ess.repairs import _require_mr

		_require_mr(name)
	else:
		frappe.throw(frappe._("{0} tidak mendukung Revisi Data.").format(doctype))


@frappe.whitelist(methods=["POST"])
def revision_reject(doctype=None, name=None, reason=None, request_id=None):
	"""POST — Tolak Revisi: close a pending request with a reason, told to whoever asked.

	``request_id`` stops a replay sending the requester the same answer twice."""
	_require(doctype, name)
	return guarded(request_id, lambda: revision.reject(doctype, name, reason))
