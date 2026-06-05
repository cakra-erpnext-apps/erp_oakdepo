"""Seed the 'OAK PPN 11%' Sales Taxes and Charges Template.

So monthly invoices apply PPN natively (GL-correct) instead of hard-coding it.
Picks the company's output-VAT account (PPN Keluaran) when available. Idempotent
and defensive: if no tax account exists the patch logs and skips rather than
failing the migrate.
"""

from __future__ import annotations

import frappe

TITLE = "OAK PPN 11%"


def execute():
	company = frappe.defaults.get_global_default("company") or frappe.db.get_value(
		"Company", {}, "name"
	)
	if not company:
		print("[container_depot] seed_ppn_template: no company; skipped.")
		return

	if frappe.db.exists("Sales Taxes and Charges Template", {"title": TITLE, "company": company}):
		return

	# Prefer an output VAT account (PPN Keluaran), else any liability tax account.
	account = (
		frappe.db.get_value(
			"Account",
			{"company": company, "account_type": "Tax", "name": ["like", "%Keluaran%"]},
			"name",
		)
		or frappe.db.get_value(
			"Account",
			{"company": company, "account_type": "Tax", "root_type": "Liability"},
			"name",
		)
		or frappe.db.get_value("Account", {"company": company, "account_type": "Tax"}, "name")
	)
	if not account:
		print("[container_depot] seed_ppn_template: no tax account; skipped.")
		return

	frappe.get_doc({
		"doctype": "Sales Taxes and Charges Template",
		"title": TITLE,
		"company": company,
		"taxes": [{
			"charge_type": "On Net Total",
			"account_head": account,
			"rate": 11,
			"description": "PPN 11%",
		}],
	}).insert(ignore_permissions=True)
	frappe.db.commit()
	print(f"[container_depot] seed_ppn_template: created '{TITLE}' on {account}.")
