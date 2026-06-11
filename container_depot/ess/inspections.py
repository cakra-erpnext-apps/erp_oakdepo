"""ESS PWA EIR endpoints — thin ``@frappe.whitelist`` wrappers over operations.eir.

Per the integration rule: endpoints here only add authentication + whitelisting +
GET/POST gating; every bit of EIR resolution/build logic lives in
``container_depot.operations.eir`` so the same code backs the PWA and any Desk /
automation caller. Mirrors the shape of ``ess/inventory.py``.
"""

from __future__ import annotations

import frappe

from container_depot.api import _require_authenticated_user
from container_depot.operations import eir


@frappe.whitelist(methods=["GET"])
def eir_masters():
	"""GET /api/v1/ess/eir-masters — checklist + damage/repair code lists."""
	_require_authenticated_user()
	return eir.get_eir_masters()


@frappe.whitelist(methods=["GET"])
def eir_prefill(container=None, container_no=None, booking_code=None, order_bongkar=None):
	"""GET /api/v1/ess/eir-prefill?container_no=… (booking_code / order_bongkar optional)."""
	_require_authenticated_user()
	return eir.prefill(
		container=container,
		container_no=container_no,
		booking_code=booking_code,
		order_bongkar=order_bongkar,
	)


@frappe.whitelist(methods=["GET"])
def eir_voucher(voucher=None, inspection_type="EIR-In"):
	"""GET /api/v1/ess/eir-voucher — read-only shipment snapshot from a referred voucher.

	EIR-In resolves an Order Bongkar (shipper), EIR-Out an Order Muat (truck / driver /
	driver phone / shipper). See ``operations.eir.fetch_voucher``.
	"""
	_require_authenticated_user()
	return eir.fetch_voucher(voucher=voucher, inspection_type=inspection_type)


@frappe.whitelist(methods=["POST"])
def eir_open_draft(container=None, container_no=None, inspection_type="EIR-In"):
	"""POST /api/v1/ess/eir-open-draft — get-or-create the container's draft EIR.

	Mutating (creates the draft on first fetch), hence POST.
	"""
	_require_authenticated_user()
	return eir.open_draft(container=container, container_no=container_no, inspection_type=inspection_type)


@frappe.whitelist(methods=["POST"])
def eir_save_draft(
	inspection=None,
	inspection_type=None,
	tank_status=None,
	vessel=None,
	truck_no=None,
	emkl=None,
	remarks=None,
	signature=None,
	referred_voucher=None,
	cargo=None,
	eir_date=None,
	lines=None,
	photos=None,
	submit=False,
):
	"""POST /api/v1/ess/eir-save-draft — auto-save (submit=1 finalizes) a draft EIR."""
	_require_authenticated_user()
	return eir.save_draft(
		inspection=inspection,
		inspection_type=inspection_type,
		tank_status=tank_status,
		vessel=vessel,
		truck_no=truck_no,
		emkl=emkl,
		remarks=remarks,
		signature=signature,
		referred_voucher=referred_voucher,
		cargo=cargo,
		eir_date=eir_date,
		lines=lines,
		photos=photos,
		submit=submit,
	)


@frappe.whitelist(methods=["POST"])
def eir_create(
	inspection_type=None,
	container=None,
	tank_status=None,
	booking_code=None,
	order_ref=None,
	order_doctype=None,
	vessel=None,
	truck_no=None,
	emkl=None,
	remarks=None,
	depot=None,
	signature=None,
	referred_voucher=None,
	cargo=None,
	eir_date=None,
	lines=None,
	photos=None,
	submit=False,
):
	"""POST /api/v1/ess/eir-create — build (and optionally submit) an EIR Inspection."""
	_require_authenticated_user()
	return eir.create_eir(
		inspection_type=inspection_type,
		container=container,
		tank_status=tank_status,
		booking_code=booking_code,
		order_ref=order_ref,
		order_doctype=order_doctype,
		vessel=vessel,
		truck_no=truck_no,
		emkl=emkl,
		remarks=remarks,
		depot=depot,
		signature=signature,
		referred_voucher=referred_voucher,
		cargo=cargo,
		eir_date=eir_date,
		lines=lines,
		photos=photos,
		submit=submit,
	)
