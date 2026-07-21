"""Repair draft EIRs left pointing at a bon that was cancelled (or deleted).

Cancelling an Order Bongkar / Order Muat used to release its Booking Codes but ignore
the EIR drafts it had provisioned. Those drafts kept referencing the voided bon, and
every auto-save then threw "… is not submitted yet" — the EIR became unsavable, and
the replacement bon never adopted it (provisioning dedups on "container already has a
draft"), so the tank's inspection was stuck for good.

``release_eirs_for_cancelled_order`` now runs on cancel; this replays it over the
drafts already stranded. It prefers re-pointing at a live bon, deletes only drafts
that provably hold no work (never started), and otherwise keeps the work and drops
just the dangling link.
"""

import frappe

from container_depot.operations.eir import release_eirs_for_cancelled_order

# (inspection_type, the bon doctype its referred_voucher points at)
_PAIRS = (("EIR-In", "Order Bongkar"), ("EIR-Out", "Order Muat"))


def execute():
	for inspection_type, voucher_doctype in _PAIRS:
		if not frappe.db.exists("DocType", voucher_doctype):
			continue
		vouchers = frappe.get_all(
			"Inspection",
			filters={
				"docstatus": 0,
				"inspection_type": inspection_type,
				"referred_voucher": ("is", "set"),
			},
			pluck="referred_voucher",
			distinct=True,
		)
		for voucher in vouchers:
			# Only stranded ones: a submitted bon is a perfectly good reference.
			if frappe.db.get_value(voucher_doctype, voucher, "docstatus") == 1:
				continue
			res = release_eirs_for_cancelled_order(voucher, inspection_type)
			moved = {k: v for k, v in res.items() if v}
			if moved:
				print(f"{voucher_doctype} {voucher}: {moved}")
