"""Sales Invoice generation helpers (native ERPNext receivables).

Auto-invoicing is intentionally best-effort: a missing accounting setup must
never block an operational submit (order / booking). Callers wrap these in
try/except and log; in a configured site the invoice is created as a Draft and
linked back.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, flt, today

from container_depot import pricing

SERVICE_ITEM = "OAK Depot Service"
PPN_TEMPLATE = "OAK PPN 11%"
# Label of the charge row that carries the invoice's labour cost.
MANHOUR_CHARGE = "Manhour"


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


def ensure_receivable_account(company, currency):
	"""Return a Receivable account (for ``company``) denominated in ``currency``,
	creating it once under the default receivable's parent if absent.

	Returns None when no currency is given or it matches the company currency —
	the caller then falls back to ERPNext's default receivable (company currency).

	Rationale: ERPNext derives a Payment Entry's currency from the invoice's
	party (``debit_to``) account currency, NOT from the invoice's document
	currency. So a USD invoice booked to the IDR default receivable yields an IDR
	payment. Pointing a foreign-currency invoice at a same-currency receivable is
	what makes ``Create > Payment`` come out in the invoice currency.
	"""
	if not company or not currency:
		return None
	company_currency = frappe.db.get_value("Company", company, "default_currency")
	if currency == company_currency:
		return None

	existing = frappe.db.get_value(
		"Account",
		{"company": company, "account_currency": currency,
		 "account_type": "Receivable", "is_group": 0, "disabled": 0},
		"name",
	)
	if existing:
		return existing

	default_recv = frappe.db.get_value("Company", company, "default_receivable_account")
	parent = frappe.db.get_value("Account", default_recv, "parent_account") if default_recv else None
	if not parent:
		return None  # unusual CoA — leave the default receivable in place

	acc = frappe.get_doc({
		"doctype": "Account",
		"account_name": f"Piutang {currency}",
		"parent_account": parent,
		"company": company,
		"account_currency": currency,
		"account_type": "Receivable",
		"is_group": 0,
	})
	acc.insert(ignore_permissions=True)
	return acc.name


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
	customer, lines, due_days=30, posting_date=None, remarks=None, taxes_and_charges=None,
	currency=None, selling_price_list=None, branch=None, conversion_rate=None, manhour=True,
):
	"""Create (and return the name of) a Draft Sales Invoice.

	``lines`` is a list of {item_code, description, qty, rate}; ``item_code`` falls back
	to the generic depot service item when absent or unknown. ``taxes_and_charges`` is an
	optional Sales Taxes and Charges Template name (e.g. PPN).

	Every depot invoice is raised through here, so this is also where labour starts: each
	line is stamped with the manhour its contract books for that service (never priced into
	the line), which :func:`apply_manhour_charge` totals and charges once in the header.
	Pass ``manhour=False`` for an invoice that must not carry it.

	``currency`` / ``selling_price_list`` make the invoice follow the booking's chosen
	rate card — the price-list currency (USD / IDR) is used as-is with conversion_rate 1
	(no exchange-rate conversion), so a USD price list yields a USD invoice. ``branch``
	is stamped on the app's Sales Invoice custom field. Returns None if the site is not
	invoice-ready (no company / no customer).
	"""
	company = get_default_company()
	if not company or not customer:
		return None

	income_account = frappe.db.get_value("Company", company, "default_income_account")
	service_item = ensure_service_item()
	posting = posting_date or today()

	si = frappe.new_doc("Sales Invoice")
	si.customer = customer
	si.company = company
	si.posting_date = posting
	si.set_posting_time = 1
	si.due_date = add_days(posting, due_days)
	if remarks:
		si.remarks = remarks
	if branch and frappe.db.exists("Branch", branch):
		si.branch = branch
	if selling_price_list:
		si.selling_price_list = selling_price_list
	if currency:
		# Bill in the price-list currency. Exchange rate is optional: default 1
		# (value-as-is, no FX) but a caller may pass a real rate. Point a foreign
		# invoice at a same-currency receivable so Create > Payment comes out in
		# the invoice currency (ERPNext takes payment currency from debit_to, not
		# the document currency).
		rate = conversion_rate or 1
		si.currency = currency
		si.conversion_rate = rate
		si.plc_conversion_rate = rate
		recv = ensure_receivable_account(company, currency)
		if recv:
			si.debit_to = recv

	# Manhour the contract books per line — stamped on the line, never priced into it.
	# The header totals them (see :func:`apply_manhour_charge`).
	hours = pricing.invoice_manhours(customer, lines) if manhour else {}

	for i, ln in enumerate(lines):
		item_code = ln.get("item_code")
		if not item_code or not frappe.db.exists("Item", item_code):
			item_code = service_item
		si.append("items", {
			"item_code": item_code,
			"description": ln.get("description") or item_code,
			"qty": ln.get("qty") or 1,
			"rate": ln.get("rate") or 0,
			"manhour": ln.get("manhour") if ln.get("manhour") is not None else hours.get(i, 0),
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
	# A foreign-currency invoice (e.g. a USD price list under an IDR-base company) carries
	# conversion_rate 1 by design here — we bill the price-list value as-is, no FX. That
	# trips ERPNext's *non-blocking* "Conversion rate is 1.00, but document currency is
	# different…" msgprint (accounts_controller.check_conversion_rate). Mute it for this
	# programmatic insert so an auto-created draft invoice raises no popup.
	prev_mute = frappe.flags.mute_messages
	frappe.flags.mute_messages = True
	try:
		si.insert(ignore_permissions=True)
	finally:
		frappe.flags.mute_messages = prev_mute
	return si.name


# --------------------------------------------------------------------------- #
# Labour (manhour)
#
# A service's tariff and the labour it takes are two different things, and the invoice
# keeps them apart to the very end:
#
#     Total = Total Price + (Total Manhour × Hour)
#
# Every line shows the manhour its contract books (``Sales Invoice Item.manhour``); the
# hours never touch that line's own amount. Here they are totalled into the header and
# charged ONCE, as an *Actual* Sales Taxes and Charges row — the native way to fold a flat
# amount into ERPNext's grand total while keeping it out of the items' Sub Total.
#
# ``Hour`` (the multiplier) seeds from the contract default and stays editable: change it
# and everything below recomputes on save.
# --------------------------------------------------------------------------- #
def apply_manhour_charge(doc, method=None):
	"""validate hook: total the lines' manhours and charge them as one amount.

	Manhour does NOT scale with qty — that is what makes it different from the rate. A rate
	is per unit and is multiplied by the line's qty; a manhour is the labour the line books,
	full stop. The lines' manhours are summed as they stand and the sum is multiplied by
	``Hour`` — once, at the end.

	No-op on an invoice whose lines book no labour, so ordinary ERPNext invoices — and any
	depot invoice raised with ``manhour=False`` — are left exactly as they were.
	"""
	hours = sum(flt(row.get("manhour")) for row in (doc.items or []))
	doc.total_manhour = hours
	if hours and not flt(doc.get("manhour_hour")):
		# Existing invoices predate the field's default, so seed it rather than bill 0.
		doc.manhour_hour = pricing.DEFAULT_MANHOUR_HOUR
	amount = flt(hours) * flt(doc.get("manhour_hour"))
	doc.manhour_amount = amount
	if _sync_manhour_charge_row(doc, amount):
		# This hook runs AFTER the controller has already totalled the document, so a charge
		# row added here would otherwise only reach the grand total on the NEXT save (the
		# invoice would bill last save's labour). Re-run the totals so it lands now.
		doc.calculate_taxes_and_totals()


def _sync_manhour_charge_row(doc, amount) -> bool:
	"""Keep exactly one ``Manhour`` charge row in step with ``amount`` (drop it at 0).

	The row is forced FIRST in the tax table, and any percentage tax that was charging
	"On Net Total" is repointed at it ("On Previous Row Total"). That is what makes tax
	land on the labour as well, so the invoice runs:

	    Total Price + Biaya Manhour  ->  PPN on that sum  ->  Grand Total

	Leaving the percentage on Net Total would tax the services but not the labour, and the
	customer would be charged tax on part of the bill only.

	Returns True when the tax table was touched, i.e. the totals need recomputing.
	"""
	existing = [t for t in (doc.taxes or []) if (t.description or "").strip() == MANHOUR_CHARGE]
	if not amount:
		if not existing:
			return False
		doc.set("taxes", [t for t in doc.taxes if t not in existing])
		_renumber(doc)
		return True
	account = _manhour_charge_account(doc.company)
	if not account:
		# Nothing to post the charge to — leave the totals visible in the header rather
		# than raise on an invoice the user is trying to save.
		return False

	row = existing[0] if existing else doc.append("taxes", {})
	before = (flt(row.tax_amount), row.account_head, row.idx)
	row.charge_type = "Actual"
	row.description = MANHOUR_CHARGE
	row.account_head = account
	row.tax_amount = amount
	# A charge, not a tax: it must not be included in the printed item rates.
	row.included_in_print_rate = 0

	others = [t for t in doc.taxes if t is not row and t not in existing[1:]]
	doc.set("taxes", [row] + others)
	_renumber(doc)
	for other in others:
		if other.charge_type == "On Net Total":
			other.charge_type = "On Previous Row Total"
			other.row_id = row.idx
	return before != (flt(row.tax_amount), row.account_head, row.idx) or bool(existing[1:])


def _renumber(doc):
	for i, tax in enumerate(doc.taxes or [], start=1):
		tax.idx = i


@frappe.whitelist()
def manhour_charge_account(company=None):
	"""The account the labour charge posts to (whitelisted for the Sales Invoice form).

	The form needs it to create the charge row itself, so the Grand Total moves the moment
	Hour or a line's manhour is edited instead of only catching up on save.
	"""
	return _manhour_charge_account(company or get_default_company())


def _manhour_charge_account(company):
	"""Account the labour charge posts to — the company's income account."""
	if not company:
		return None
	return frappe.db.get_value("Company", company, "default_income_account") or frappe.db.get_value(
		"Account", {"company": company, "root_type": "Income", "is_group": 0}, "name"
	)
