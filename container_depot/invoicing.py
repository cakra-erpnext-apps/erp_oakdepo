"""Sales Invoice generation helpers (native ERPNext receivables).

Auto-invoicing is intentionally best-effort: a missing accounting setup must
never block an operational submit (order / booking). Callers wrap these in
try/except and log; in a configured site the invoice is created as a Draft and
linked back.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, today

from container_depot import finance, pricing

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
	manhour_hour=None,
):
	"""Create (and return the name of) a Draft Sales Invoice.

	``lines`` is a list of {item_code, description, qty, rate}; ``item_code`` falls back
	to the generic depot service item when absent or unknown. ``taxes_and_charges`` is an
	optional Sales Taxes and Charges Template name (e.g. PPN).

	Every depot invoice is raised through here, so this is also where labour starts: each
	line is stamped with the manhour its contract books for that service (never priced into
	the line), which :func:`apply_manhour_charge` totals and charges once in the header.
	Pass ``manhour=False`` for an invoice that must not carry it. ``manhour_hour`` overrides the
	hourly tariff the header would otherwise seed from the customer's rate card — used when the
	swept work orders all agreed on a negotiated rate of their own (see
	``consolidated_billing``); :func:`apply_manhour_charge` only seeds a BLANK one, so a value
	set here survives.

	``currency`` / ``selling_price_list`` make the invoice follow the booking's chosen
	rate card — the price-list currency (USD / IDR) is used as-is with conversion_rate 1
	(no exchange-rate conversion), so a USD price list yields a USD invoice. ``branch``
	is stamped on the app's Sales Invoice custom field. Returns None if the site is not
	invoice-ready (no company / no customer) — or if finance is switched off.
	"""
	# The one door every invoice in this app comes through, so this is where "run the depot
	# without invoicing" is enforced (see container_depot.finance). None is the answer
	# callers already handle for a site that cannot invoice.
	if not finance.is_enabled():
		return None
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

	# A negotiated hourly tariff off the orders being billed. Set before insert so
	# apply_manhour_charge (which seeds only when blank) leaves it alone.
	if manhour and manhour_hour:
		si.manhour_hour = flt(manhour_hour)

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
#     Total = Total Price + (Total Jam × Tarif per Jam)
#
# Every line shows the HOURS its service books (``Sales Invoice Item.manhour``, from
# ``Item.manhour``); the hours never touch that line's own amount. Here they are totalled
# into the header, met by the customer's labour TARIFF, and charged ONCE as an *Actual*
# Sales Taxes and Charges row — the native way to fold a flat amount into ERPNext's grand
# total while keeping it out of the items' Sub Total.
#
# ``Tarif per Jam`` seeds from the customer's own rate card (``Item Price.manhour_rate``,
# published by their contract) and stays editable: change it and everything below
# recomputes on save.
# --------------------------------------------------------------------------- #
def apply_manhour_charge(doc, method=None):
	"""validate hook: total the lines' hours and charge them as one amount.

	Labour does NOT scale with qty — that is what makes it different from the rate. A rate
	is per unit and is multiplied by the line's qty; the hours are the labour the line books,
	full stop. The lines' hours are summed as they stand and the sum is multiplied by the
	customer's ``Tarif per Jam`` — once, at the end.

	No-op on an invoice whose lines book no labour, so ordinary ERPNext invoices — and any
	depot invoice raised with ``manhour=False`` — are left exactly as they were.
	"""
	hours = sum(flt(row.get("manhour")) for row in (doc.items or []))
	doc.total_manhour = hours
	if hours and doc.is_new() and not flt(doc.get("manhour_hour")):
		# Seed the tariff ONCE, as the invoice is raised, from the customer's own rate card.
		# Doing it on every save would make ``Tarif per Jam = 0`` — the way to say "no labour
		# on this one" — impossible to keep: it would be overwritten back before the charge
		# is computed.
		doc.manhour_hour = pricing.manhour_rate_for(doc.customer) or pricing.DEFAULT_MANHOUR_HOUR
	repaired = False
	deleted_idx = _deleted_charge_row_idx(doc) if hours and flt(doc.get("manhour_hour")) else 0
	if deleted_idx:
		doc.manhour_hour = 0
		# The user took the row out by hand, so the rows below it are still numbered — and
		# still pointing — as if it were there. Close the gap ourselves rather than trust
		# the form to have done it: a percentage left referring to the vanished row bills 0.
		repaired = _close_row_gaps(doc, list(doc.taxes or []), [deleted_idx])
		frappe.msgprint(
			_("Biaya Manhour dihapus — Hour diset 0. Isi Hour lagi untuk menagihkannya kembali."),
			indicator="orange",
			alert=True,
		)
	amount = flt(hours) * flt(doc.get("manhour_hour"))
	doc.manhour_amount = amount
	if _sync_manhour_charge_row(doc, amount) or repaired:
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
		_drop_charge_rows(doc, existing)
		return True
	posting = _item_posting(doc)
	if not posting.get("account"):
		# Nothing to post the charge to — leave the totals visible in the header rather
		# than raise on an invoice the user is trying to save.
		return False

	row = existing[0] if existing else doc.append("taxes", {})
	before = (flt(row.tax_amount), row.account_head, row.idx)
	row.charge_type = "Actual"
	row.description = MANHOUR_CHARGE
	row.tax_amount = amount
	# Labour is revenue from the same services the lines bill, so it posts exactly where
	# they do — account AND cost center are taken from the item rows rather than resolved
	# separately. (The cost center matters: ERPNext refuses a GL entry against a
	# Profit-and-Loss account without one, which is why a charge row missing it saved fine
	# and only blew up at submit.)
	row.account_head = posting["account"]
	row.cost_center = posting.get("cost_center")
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


def _drop_charge_rows(doc, doomed) -> bool:
	"""Take the labour rows out, then close the gap they leave behind."""
	gaps = sorted(cint(t.idx) for t in doomed)
	return _close_row_gaps(doc, [t for t in doc.taxes if t not in doomed], gaps)


def _close_row_gaps(doc, rest, gaps) -> bool:
	"""Undo, on ``rest``, what inserting a charge row at each of ``gaps`` did.

	Inserting the labour charge repoints a percentage from "On Net Total" to "On Previous
	Row Total" so tax lands on the labour as well. Taking it away has to put that back, and
	shift any other reference past the gap: a ``row_id`` is an *index*, so dropping row 1
	leaves every reference below it pointing one row too far. ERPNext does not fail loudly
	on that — it bills the percentage as **0** — so leaving it alone silently drops the tax.

	Returns True when anything moved, i.e. the totals need recomputing.
	"""
	before = [(t.name, t.idx, t.charge_type, t.row_id) for t in rest]
	for tax in rest:
		if tax.charge_type not in ("On Previous Row Total", "On Previous Row Amount"):
			continue
		ref = cint(tax.row_id)
		if ref in gaps:
			# It was stacked on the labour charge; with that gone it charges on the net
			# total again — exactly what it did before the charge row was inserted.
			tax.charge_type = "On Net Total"
			tax.row_id = None
		elif ref:
			tax.row_id = ref - len([g for g in gaps if g < ref])
	doc.set("taxes", rest)
	_renumber(doc)
	return before != [(t.name, t.idx, t.charge_type, t.row_id) for t in rest]


def _deleted_charge_row_idx(doc) -> int:
	"""The idx the labour row held when this save drops one the invoice already had (else 0).

	The row is derived from the lines, so rebuilding it is the default — which means a user
	who deletes it in the grid would watch it come straight back. Reading the deletion as
	intent ("don't bill labour on this invoice") is what makes Delete do something; the
	caller answers it by zeroing Hour, which the user undoes by typing an Hour again.
	"""
	if doc.is_new():
		return 0
	if any((t.description or "").strip() == MANHOUR_CHARGE for t in (doc.taxes or [])):
		return 0
	return cint(frappe.db.get_value("Sales Taxes and Charges", {
		"parent": doc.name,
		"parenttype": "Sales Invoice",
		"description": MANHOUR_CHARGE,
	}, "idx"))


def _renumber(doc):
	for i, tax in enumerate(doc.taxes or [], start=1):
		tax.idx = i


def _item_posting(doc) -> dict:
	"""Where the invoice's item lines post: their income account and cost center.

	The labour charge rides along with them — it is the same revenue, just charged once as
	a flat amount instead of per unit, so giving it its own account resolution only risked
	the two drifting apart. Reads the first line that actually carries an account.
	"""
	for item in doc.items or []:
		if item.get("income_account"):
			return {"account": item.income_account, "cost_center": item.get("cost_center")}
	return {}
