"""Close every Tank In bon whose tanks were all inspected in.

An Order Bongkar never left ``Issued`` before 2026-10-02 — it now closes on its last EIR-In
(``order_bongkar.sync_completion``). This applies that rule to the bons already sitting there.
"""

import frappe

from container_depot.container_depot.doctype.order_bongkar.order_bongkar import sync_completion


def execute():
	for name in frappe.get_all(
		"Order Bongkar", filters={"docstatus": 1, "order_status": "Issued"}, pluck="name"
	):
		sync_completion(frappe._dict(
			inspection_type="EIR-In", voucher_doctype="Order Bongkar", referred_voucher=name
		))
