"""Pricing spec §3.6 — seed the depot standard Contract Template.

Standard ERPNext Contract Template holding the legal terms & conditions only.
Rates deliberately live in Price List / Item Price (seed_price_lists,
seed_service_items, seed_product_bundles), never in the contract — the spec (§2)
treats rate-in-contract as an anti-pattern (the legacy Depot Contract.tariff_lines
is exactly that and should be flagged for migration).

Idempotent: skipped if the template already exists. Defensive: if the Contract
Template doctype is unavailable (erpnext not installed) it logs and skips.
"""

from __future__ import annotations

import frappe

TITLE = "Depot Services Standard Terms"

CONTRACT_TERMS = """<p><strong>OAK Depot — Standard Terms &amp; Conditions</strong></p>
<ol>
<li>All rates are quoted <strong>exclusive of VAT (PPN) 11%</strong>, which is added on invoicing.</li>
<li>Rates are <strong>per tank, 20ft standard ISO tank</strong> basis, unless otherwise agreed.</li>
<li><strong>Overtime</strong> work on Sundays and public holidays is charged at <strong>2× (200%)</strong> the standard rate.</li>
<li><strong>Residue disposal up to 20 litres</strong> is inclusive; any surplus above 20L is charged as a separate disposal surcharge.</li>
<li>The depot is <strong>not liable</strong> for the container or its fittings after the container has been released and has left the depot.</li>
<li>Pricing for services follows the principal's current Price List; package pricing follows the applicable Product Bundle.</li>
</ol>"""


def execute():
	if not frappe.db.exists("DocType", "Contract Template"):
		print("[container_depot] seed_contract_template: Contract Template doctype missing; skipped.")
		return
	if frappe.db.exists("Contract Template", TITLE):
		return

	frappe.get_doc({
		"doctype": "Contract Template",
		"title": TITLE,
		"contract_terms": CONTRACT_TERMS,
		"requires_fulfilment": 0,
	}).insert(ignore_permissions=True)
	frappe.db.commit()
	print(f"[container_depot] seed_contract_template: created '{TITLE}'.")
