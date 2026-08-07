"""ESS PWA Periodic Test menu — the M&R-style execution console for a container's periodic
pressure test (2,5Y / 5Y).

Thin whitelist wrappers over ``container_depot.periodic`` — the PWA execution worklist (start ->
done) + history. Like the M&R menu, this is an EXECUTION console: it only surfaces work the
owner (or an Admin-Ops bypass in Desk) has already approved. Estimate-building and the owner
decision live in Desk. All resolution/build logic lives in ``container_depot/periodic.py``; the
endpoint layer only adds auth + whitelisting.
"""

from __future__ import annotations

import frappe

from container_depot.ess.guard import require_menu
from container_depot.container_depot import periodic


@frappe.whitelist(methods=["GET"])
def pt_orders(start=0, page_length=20, search=None):
	"""GET — the full in-flight Periodic Test worklist (Draft … In Progress), depot-scoped."""
	require_menu("periodicTest")
	return periodic.list_open_pt_orders(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def pt_execution(start=0, page_length=20, search=None):
	"""GET — the PWA execution worklist: Approved / In Progress only, depot-scoped."""
	require_menu("periodicTest")
	return periodic.list_pt_execution(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def pt_history(start=0, page_length=10, search=None):
	"""GET — finished (Completed / Rejected / Cancelled) Periodic Test Orders."""
	require_menu("periodicTest")
	return periodic.list_pt_history(start=start, page_length=page_length, search=search)


@frappe.whitelist(methods=["GET"])
def pt_order_detail(periodic_test_order=None):
	"""GET — one Periodic Test Order's test info + used items + tank spec."""
	require_menu("periodicTest")
	return periodic.get_pt_order_detail(periodic_test_order)


@frappe.whitelist(methods=["POST"])
def pt_start(periodic_test_order=None):
	"""POST — start the Approved Periodic Test (In Progress)."""
	require_menu("periodicTest")
	return periodic.start_test(periodic_test_order)


@frappe.whitelist(methods=["POST"])
def pt_order_save(periodic_test_order=None, periodic_date=None, technician=None, reff_doc=None, remarks=None, submit=False):
	"""POST — save the test outcome fields; ``submit=1`` completes it (issues approved parts +
	pushes the next due-date onto the Container)."""
	require_menu("periodicTest")
	return periodic.save_pt_order(
		periodic_test_order=periodic_test_order, periodic_date=periodic_date,
		technician=technician, reff_doc=reff_doc, remarks=remarks, submit=submit,
	)
