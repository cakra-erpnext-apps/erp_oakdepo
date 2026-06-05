"""Sales Invoice generation helpers (native ERPNext receivables).

Auto-invoicing is intentionally best-effort: a missing accounting setup must
never block an operational submit (order / booking). Callers wrap these in
try/except and log; in a configured site the invoice is created as a Draft and
linked back.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, today

SERVICE_ITEM = "OAK Depot Service"
PPN_TEMPLATE = "OAK PPN 11%"


def get_default_company():
	return frappe.defaults.get_global_default("company") or frappe.db.get_value(
		"Company", {}, "name"
	)


def ensure_service_item():
	"""Idempotently ensure a non-stock service Item exists for depot charges."""
	if frappe.db.exists("Item", SERVICE_ITEM):
		return SERVICE_ITEM
	group = "Services" if frappe.db.exists("Item Group", "Services") else "All Item Groups"
	frappe.get_doc({
		"doctype": "Item",
		"item_code": SERVICE_ITEM,
		"item_name": SERVICE_ITEM,
		"item_group": group,
		"stock_uom": "Nos",
		"is_stock_item": 0,
		"is_sales_item": 1,
	}).insert(ignore_permissions=True)
	return SERVICE_ITEM


def _resolve_tax_template(title_or_name, company):
	"""Resolve a Sales Taxes and Charges Template by exact name, or by title +
	company (template names get a ' - <abbr>' suffix on creation)."""
	if not title_or_name:
		return None
	if frappe.db.exists("Sales Taxes and Charges Template", title_or_name):
		return title_or_name
	return frappe.db.get_value(
		"Sales Taxes and Charges Template",
		{"title": title_or_name, "company": company},
		"name",
	)


def create_draft_sales_invoice(
	customer, lines, due_days=30, posting_date=None, remarks=None, taxes_and_charges=None
):
	"""Create (and return the name of) a Draft Sales Invoice.

	``lines`` is a list of {description, qty, rate}. ``taxes_and_charges`` is an
	optional Sales Taxes and Charges Template name (e.g. PPN). Returns None if the
	site is not invoice-ready (no company / no customer).
	"""
	company = get_default_company()
	if not company or not customer:
		return None

	income_account = frappe.db.get_value("Company", company, "default_income_account")
	item = ensure_service_item()
	posting = posting_date or today()

	si = frappe.new_doc("Sales Invoice")
	si.customer = customer
	si.company = company
	si.posting_date = posting
	si.set_posting_time = 1
	si.due_date = add_days(posting, due_days)
	if remarks:
		si.remarks = remarks

	for ln in lines:
		si.append("items", {
			"item_code": item,
			"description": ln.get("description") or item,
			"qty": ln.get("qty") or 1,
			"rate": ln.get("rate") or 0,
			"income_account": income_account,
		})

	tmpl = _resolve_tax_template(taxes_and_charges, company)
	if tmpl:
		si.taxes_and_charges = tmpl
		# Pull the template rows in so PPN is computed natively by ERPNext.
		from erpnext.controllers.accounts_controller import get_taxes_and_charges
		for tax in get_taxes_and_charges("Sales Taxes and Charges Template", tmpl):
			si.append("taxes", tax)

	si.flags.ignore_permissions = True
	si.insert(ignore_permissions=True)
	return si.name
