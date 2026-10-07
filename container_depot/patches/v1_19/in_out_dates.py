"""Tanggal Masuk / Tanggal Keluar from the bons (user, 2026-10-07).

``Container.eir_in_date`` / ``eir_out_date`` meant "arrival" for some readers and "the EIR's
date" for others, and the gate log carried submit times. Both are replaced by the bons' own
dates (``visit_dates``):

* Gate Entry ``in_date`` = its Order Bongkar's Tanggal Bongkar (else the gate-in day);
  ``out_date`` = the Order Muat's Tanggal Muat (else the gate-out day), with ``order_muat``
  filled from the EIR-Out that released the tank.
* Container ``in_date`` / ``out_date`` = the latest bons' dates, falling back to the old
  columns (tanks injected by import have no bon); ``out_date`` only for a tank that has left.

Then the Storage Charge ledger is re-derived from the new dates. The old columns are left in
the table untouched, so nothing is lost.
"""

import frappe

from container_depot import storage_charge


def execute():
	_gate_entries()
	_containers()
	storage_charge.sync_all()


def _gate_entries():
	frappe.db.sql(
		"""UPDATE `tabGate Entry` ge
		LEFT JOIN `tabOrder Bongkar` ob
			ON ge.order_doctype = 'Order Bongkar' AND ob.name = ge.order_ref AND ob.docstatus = 1
		SET ge.in_date = COALESCE(ob.tanggal_bongkar, DATE(ge.gate_in_timestamp))
		WHERE ge.in_date IS NULL"""
	)
	frappe.db.sql(
		"""UPDATE `tabGate Entry` ge
		LEFT JOIN `tabInspection` eo
			ON eo.name = ge.eir_reference AND eo.voucher_doctype = 'Order Muat'
		SET ge.order_muat = COALESCE(
			eo.referred_voucher,
			IF(ge.order_doctype = 'Order Muat', ge.order_ref, NULL)
		)
		WHERE ge.gate_out_timestamp IS NOT NULL AND ge.order_muat IS NULL"""
	)
	frappe.db.sql(
		"""UPDATE `tabGate Entry` ge
		LEFT JOIN `tabOrder Muat` om ON om.name = ge.order_muat AND om.docstatus = 1
		SET ge.out_date = COALESCE(om.tanggal_muat, DATE(ge.gate_out_timestamp))
		WHERE ge.gate_out_timestamp IS NOT NULL AND ge.out_date IS NULL"""
	)


def _containers():
	old = frappe.db.has_column("Container", "eir_in_date")
	frappe.db.sql(
		f"""UPDATE `tabContainer` c
		LEFT JOIN `tabOrder Bongkar` ob ON ob.name = c.last_order_bongkar AND ob.docstatus = 1
		SET c.in_date = COALESCE(ob.tanggal_bongkar{", DATE(c.eir_in_date)" if old else ""})
		WHERE c.in_date IS NULL"""
	)
	frappe.db.sql(
		f"""UPDATE `tabContainer` c
		LEFT JOIN `tabOrder Muat` om ON om.name = c.last_order_muat AND om.docstatus = 1
		SET c.out_date = IF(
			c.status = 'Gate_Out',
			COALESCE(om.tanggal_muat{", DATE(c.eir_out_date)" if old else ""}),
			NULL
		)"""
	)
