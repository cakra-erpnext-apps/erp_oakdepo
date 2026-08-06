"""ESS PWA Gate Entry endpoints — thin ``@frappe.whitelist`` wrappers over operations.gate.

Per the integration rule (mirrors ``ess/inspections.py``): endpoints here only add auth +
whitelisting; all listing/detail logic lives in ``container_depot.operations.gate``.
"""

from __future__ import annotations

import frappe

from container_depot.api import _require_authenticated_user
from container_depot.operations import gate


@frappe.whitelist(methods=["GET"])
def gate_history(start=0, page_length=10, search=None):
	"""GET /api/v1/ess/gate-history — Gate Entry (in/out voucher) history, depot-scoped."""
	_require_authenticated_user()
	return gate.list_gate_history(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def gate_detail(name=None):
	"""GET /api/v1/ess/gate-detail — one Gate Entry's full vehicle/order/EIR detail."""
	_require_authenticated_user()
	return gate.get_gate_detail(name)


@frappe.whitelist(methods=["GET"])
def gate_ready(search=None, start=0, page_length=20):
	"""GET /api/v1/ess/gate-ready — "Siap Keluar" worklist: tanks with a clean submitted
	EIR-Out that are still in the depot, waiting for the ACC that releases them.

	Derived from the EIRs themselves (no stored queue), branch-scoped in
	``gate.list_ready_to_load``."""
	_require_authenticated_user()
	return gate.list_ready_to_load(search=search, start=start, page_length=page_length)


@frappe.whitelist(methods=["POST"])
def gate_out(container=None, gate_entry=None):
	"""POST /api/v1/ess/gate-out — complete gate-out / load-complete for a tank.

	The depot-branch guard (a container outside the caller's branch is rejected) lives in
	``gate.mark_gate_out`` via ``assert_in_user_branch`` — same scope used across ess.*."""
	_require_authenticated_user()
	return gate.mark_gate_out(container=container, gate_entry=gate_entry)
