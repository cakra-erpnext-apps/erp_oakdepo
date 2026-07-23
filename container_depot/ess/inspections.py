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
def eir_history(search=None, start=0, page_length=10, docstatus=None):
	"""GET /api/v1/ess/eir-history — the caller's own EIRs (newest first, paginated).

	Searchable by container number / EIR id. Scoped to the logged-in user's own EIRs.
	Optional ``docstatus`` (0 = drafts, 1 = submitted) narrows the list — used by the
	checklist landing's "latest drafts / completed" quick lists.
	"""
	_require_authenticated_user()
	return eir.list_my_eirs(
		user=frappe.session.user,
		search=search,
		start=start,
		page_length=page_length,
		docstatus=docstatus,
	)


@frappe.whitelist(methods=["GET"])
def eir_pending(search=None, start=0, page_length=20):
	"""GET /api/v1/ess/eir-pending — open (draft) EIRs in the user's branch (worklist).

	EIRs are auto-created per container when an Order Bongkar is submitted; the PWA works
	from this list — the operator no longer types a container to create one. Branch-scoped,
	searchable (container no / EIR id / voucher), paginated. See ``eir.list_pending_eirs``.
	"""
	_require_authenticated_user()
	return eir.list_pending_eirs(search=search, start=start, page_length=page_length)


@frappe.whitelist(methods=["GET"])
def eir_open(inspection=None):
	"""GET /api/v1/ess/eir-open — open an existing draft EIR by name (read-only, no create).

	The worklist picks a pending EIR and this loads its header + saved checklist state.
	"""
	_require_authenticated_user()
	return eir.open_draft_by_name(inspection=inspection)


@frappe.whitelist(methods=["POST"])
def eir_start(inspection=None):
	"""POST /api/v1/ess/eir-start — begin work on a draft EIR (stamps work_started_on).

	The PWA locks the checklist until this is called so Mulai → Submit measures how long
	the inspection took. Mutating, hence POST. See ``eir.start_eir``."""
	_require_authenticated_user()
	return eir.start_eir(inspection=inspection)


@frappe.whitelist(methods=["GET"])
def eir_out_pending(search=None, start=0, page_length=20):
	"""GET /api/v1/ess/eir-out-pending — open (draft) EIR-Out worklist in the user's branch.

	EIR-Out drafts are auto-created per container when an Order Muat is submitted
	(``provision_eir_out_for_order_muat``); the surveyor works from this list. See
	``eir.list_pending_eir_out``."""
	_require_authenticated_user()
	return eir.list_pending_eir_out(search=search, start=start, page_length=page_length)


@frappe.whitelist(methods=["GET"])
def eir_out_open(inspection=None):
	"""GET /api/v1/ess/eir-out-open — open a draft EIR-Out (form) with its EIR-In comparison
	+ cleaning-certificate validity + saved verification fields. See ``eir.open_eir_out``."""
	_require_authenticated_user()
	return eir.open_eir_out(inspection=inspection)


@frappe.whitelist(methods=["GET"])
def eir_view(inspection=None):
	"""GET /api/v1/ess/eir-view — read-only view of any EIR (draft OR submitted), for the
	Riwayat detail. Returns a compact header + recorded damages (+ supports PDF print)."""
	_require_authenticated_user()
	return eir.view_eir(inspection=inspection)


@frappe.whitelist(methods=["POST"])
def eir_request_revision(inspection=None, reason=None):
	"""POST /api/v1/ess/eir-request-revision — ask Admin Ops to reopen a submitted EIR.

	Mutating (notifies + drops an audit comment), hence POST. Does not edit the EIR."""
	_require_authenticated_user()
	return eir.request_revision(inspection=inspection, reason=reason)


@frappe.whitelist(methods=["GET"])
def eir_voucher(voucher=None, inspection_type="EIR-In", container=None):
	"""GET /api/v1/ess/eir-voucher — read-only shipment snapshot from a referred voucher.

	EIR-In resolves an Order Bongkar (shipper), EIR-Out an Order Muat (truck / driver /
	driver phone / shipper). The voucher must be submitted and carry ``container``.
	See ``operations.eir.fetch_voucher``.
	"""
	_require_authenticated_user()
	return eir.fetch_voucher(voucher=voucher, inspection_type=inspection_type, container=container)


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
	reff_doc=None,
	create_cleaning_order=None,
	create_repair_order=None,
	lines=None,
	photos=None,
	exterior_condition=None,
	exterior_remark=None,
	seals_intact=None,
	seal_remark=None,
	submit=False,
):
	"""POST /api/v1/ess/eir-save-draft — auto-save (submit=1 finalizes) a draft EIR.

	The EIR-Out form sends the extra verification fields (exterior / seals); they are
	ignored for EIR-In."""
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
		reff_doc=reff_doc,
		create_cleaning_order=create_cleaning_order,
		create_repair_order=create_repair_order,
		lines=lines,
		photos=photos,
		exterior_condition=exterior_condition,
		exterior_remark=exterior_remark,
		seals_intact=seals_intact,
		seal_remark=seal_remark,
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
	reff_doc=None,
	create_cleaning_order=None,
	create_repair_order=None,
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
		reff_doc=reff_doc,
		create_cleaning_order=create_cleaning_order,
		create_repair_order=create_repair_order,
		lines=lines,
		photos=photos,
		submit=submit,
	)


@frappe.whitelist(methods=["GET"])
def eir_unsorted(search=None, start=0, page_length=20):
	"""GET /api/v1/ess/eir-unsorted — worklist of EIRs that still have bulk photos without a
	section (admin photo-sorting). Branch-scoped. See ``eir.list_unsorted_eirs``."""
	_require_authenticated_user()
	return eir.list_unsorted_eirs(search=search, start=start, page_length=page_length)


@frappe.whitelist(methods=["GET"])
def eir_unsorted_photos(inspection=None):
	"""GET /api/v1/ess/eir-unsorted-photos — foto cepat (bulk) yang belum diberi section
	pada sebuah EIR, untuk layar sortir admin. See ``eir.unsorted_photos``."""
	_require_authenticated_user()
	return eir.unsorted_photos(inspection=inspection)


@frappe.whitelist(methods=["POST"])
def eir_assign_photo_section(inspection=None, row=None, item_code=None):
	"""POST /api/v1/ess/eir-assign-photo-section — assign one bulk photo to a checklist
	section (the admin "sortir" action). Works on a submitted EIR (allow_on_submit).
	DocPerm-enforced (no bypass). See ``eir.assign_photo_section``."""
	_require_authenticated_user()
	return eir.assign_photo_section(inspection=inspection, row=row, item_code=item_code)
