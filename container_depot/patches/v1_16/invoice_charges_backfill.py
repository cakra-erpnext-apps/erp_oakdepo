"""Carry existing invoices and storage visits over to the per-line / per-visit billing model.

1. **Invoice lines** get their own currency, price and kurs (``depot_currency`` /
   ``depot_price`` / ``depot_kurs``). Every line written before is in its invoice's currency,
   so it takes that currency, its current rate as price and the invoice's kurs — the invoice
   reads exactly as before. All invoices, so the print format has one shape to read.
2. **Draft invoices** get their PPN box (``tax_input``) from the PPN row they carry. The rows
   are rebuilt from the box on the next save; left empty, that save would drop the tax.
3. **Storage visits** get the rate their owner's contract prices them at, and the billing
   watermark the container used to hold. Storage was billed against
   ``Container.storage_billed_until`` until now; the ledger never saw it, so without this
   every day already billed would be billed again.
4. **Paid invoices** get their Customer Paid date: the last Payment Entry that settled them
   (kept up to date from then on by ``payment_entry.sync_payment_links``).
"""

import frappe
from frappe.utils import getdate


def execute():
	from container_depot.install import setup_custom_fields

	# after_migrate creates the columns, but patches run before it.
	setup_custom_fields()
	frappe.reload_doc("container_depot", "doctype", "storage_charge")
	frappe.reload_doc("container_depot", "doctype", "depot_finance_settings")
	_invoice_lines()
	_draft_tax_inputs()
	_storage_visits()
	_paid_dates()


def _invoice_lines():
	frappe.db.sql(
		"""
		UPDATE `tabSales Invoice Item` sii
		JOIN `tabSales Invoice` si ON si.name = sii.parent
		SET sii.depot_currency = si.currency,
			sii.depot_price = sii.rate,
			sii.depot_kurs = si.conversion_rate
		WHERE sii.parenttype = 'Sales Invoice' AND IFNULL(sii.depot_currency, '') = ''
		"""
	)


def _draft_tax_inputs():
	from container_depot.install import _output_vat_account

	for si in frappe.get_all("Sales Invoice", filters={"docstatus": 0}, fields=["name", "company", "tax_input"]):
		if si.tax_input:
			continue
		ppn = _output_vat_account(si.company)
		row = frappe.db.get_value(
			"Sales Taxes and Charges",
			{"parent": si.name, "parenttype": "Sales Invoice", "account_head": ppn},
			["charge_type", "rate", "tax_amount"],
			as_dict=True,
		)
		if not row:
			continue
		value = f"{row.rate:g}%" if row.charge_type != "Actual" else f"{row.tax_amount:g}"
		frappe.db.set_value("Sales Invoice", si.name, "tax_input", value, update_modified=False)


def _storage_visits():
	from container_depot import storage_charge

	touched = set()
	for v in frappe.get_all(
		"Storage Charge", filters={"rate": ["in", [0, None]]}, fields=["name", "container"]
	):
		c = frappe.db.get_value("Container", v.container, ["principal", "size"], as_dict=True)
		if c:
			frappe.db.set_value("Storage Charge", v.name, storage_charge._price(c), update_modified=False)

	for c in frappe.get_all(
		"Container", filters={"storage_billed_until": ["is", "set"]}, fields=["name", "storage_billed_until"]
	):
		if frappe.db.exists("Storage Charge", {"container": c.name, "billed_until": ["is", "set"]}):
			continue  # the ledger already keeps its own watermark for this tank
		watermark = getdate(c.storage_billed_until)
		for v in frappe.get_all("Storage Charge", filters={"container": c.name}, fields=["name", "date_in"]):
			if getdate(v.date_in) <= watermark:
				frappe.db.set_value("Storage Charge", v.name, "billed_until", watermark, update_modified=False)
				touched.add(c.name)
	for name in touched:
		storage_charge.sync(name)


def _paid_dates():
	frappe.db.sql(
		"""
		UPDATE `tabSales Invoice` si
		JOIN (
			SELECT r.reference_name, MAX(pe.posting_date) AS paid
			FROM `tabPayment Entry Reference` r
			JOIN `tabPayment Entry` pe ON pe.name = r.parent
			WHERE r.parenttype = 'Payment Entry' AND r.reference_doctype = 'Sales Invoice' AND pe.docstatus = 1
			GROUP BY r.reference_name
		) p ON p.reference_name = si.name
		SET si.depot_paid_date = p.paid
		WHERE si.docstatus = 1 AND si.outstanding_amount <= 0
		"""
	)
