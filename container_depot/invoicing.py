"""Sales Invoice generation helpers (native ERPNext receivables).

Auto-invoicing is intentionally best-effort: a missing accounting setup must
never block an operational submit (order / booking). Callers wrap these in
try/except and log; in a configured site the invoice is created as a Draft and
linked back.
"""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, today

from container_depot import finance, pricing

SERVICE_ITEM = "OAK Depot Service"
# Descriptions of the charge rows this module owns. Rebuilt from the header boxes on every
# save (build_charges), so they are never edited by hand.
MANHOUR_CHARGE = "Manhour"
PPN_CHARGE = "PPN"
PPH_CHARGE = "PPh 23"
MATERAI_CHARGE = "Materai"
_MANAGED_CHARGES = (MANHOUR_CHARGE, PPN_CHARGE, PPH_CHARGE, MATERAI_CHARGE)

# Invoice number: INV-{branch code}-OAK-{yy}-0001 — the counter runs per branch per year,
# because Frappe keys a series on everything before the ####.
INVOICE_PREFIX = "INV"
INVOICE_COMPANY_CODE = "OAK"


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


def company_currency(company=None) -> str:
	company = company or get_default_company()
	return (company and frappe.get_cached_value("Company", company, "default_currency")) or "IDR"


def locked_currency(customer, company=None) -> str | None:
	"""The only currency ``customer`` can still be invoiced in, or None when any will do.

	ERPNext (``validate_currency``) refuses an invoice in any other currency once the
	customer's receivable is foreign, and it turns foreign with their first foreign invoice
	posted (``get_party_account`` follows the existing GL): Bertschi, billed in USD once, can
	no longer take an IDR invoice at all."""
	from erpnext.accounts.party import get_party_account_currency

	company = company or get_default_company()
	if not customer or not company:
		return None
	ccy = get_party_account_currency("Customer", customer, company)
	return ccy if ccy and ccy != company_currency(company) else None


@frappe.whitelist()
def kurs_idr(currency, date=None) -> float:
	"""How many IDR (the ledger's currency) one unit of ``currency`` is worth; 0 = unknown.

	Read from ERPNext's Currency Exchange master, so the rate a user maintains there is the
	one every invoice starts from. It is only a default: the invoice keeps its own copy and
	finance may change it per invoice."""
	base = company_currency()
	if not currency or currency == base:
		return 1.0
	from erpnext.setup.utils import get_exchange_rate

	return flt(get_exchange_rate(currency, base, date or today()))


def create_draft_sales_invoice(
	customer, lines, due_days=30, posting_date=None, remarks=None, tax_input=None,
	currency=None, branch=None, kurs=None, manhour=True, invoice_type=None, address=None,
	payment_term=None,
):
	"""Create (and return the name of) a Draft Sales Invoice.

	``lines`` is a list of {item_code, description, qty, rate, currency?, source?, manhour?}
	(``manhour`` = the line's labour tariff per hour, in its own currency);
	``item_code`` falls back to the generic depot service item when absent or unknown. A line
	keeps its OWN currency and price (``depot_currency`` / ``depot_price``); the invoice rate
	is derived from it in :func:`build_charges`, so one invoice can carry USD and IDR work
	converted into ``currency``. ``source`` ("Cleaning Order|CO-1") marks the line as billed
	from that order and locks it. ``tax_input`` is what goes into the PPN box ("11%"); None
	means no PPN.

	``kurs`` is ``{currency: IDR per unit}`` for this run (the Ambil Tagihan dialog lets the
	user set them); a currency missing from it is read from Currency Exchange. IDR is the
	reference because it is what the ledger books.

	Every depot invoice is raised through here, so this is also where labour starts: a line
	that brings no ``manhour`` of its own is stamped with the tariff its contract row states
	for that service (never priced into the line), which :func:`apply_manhour_charge` totals
	and charges once in the header. Pass ``manhour=False`` for an invoice that must not
	carry it.

	``invoice_type`` is the header's Invoice Type (Booking, Cleaning, …, Gabungan);
	``address`` its Customer Address (else ERPNext's default for the customer).

	``payment_term`` is the invoice's Payment Term label (Cash, NET 30, …); without it the
	customer's contract's (:func:`contract_payment_term`). It sets nothing else: the Due Date is
	``due_days`` after the invoice date.

	``branch`` is stamped on the app's Sales Invoice custom field. Returns None if the site is
	not invoice-ready (no company / no customer) — or if finance is switched off.
	"""
	# The one door every invoice in this app comes through, so this is where "run the depot
	# without invoicing" is enforced (see container_depot.finance). None is the answer
	# callers already handle for a site that cannot invoice.
	if not finance.is_enabled():
		return None
	company = get_default_company()
	if not company or not customer:
		return None

	posting = posting_date or today()

	si = frappe.new_doc("Sales Invoice")
	si.customer = customer
	si.company = company
	si.posting_date = posting
	si.set_posting_time = 1
	si.due_date = add_days(posting, due_days)
	si.depot_payment_term = payment_term or contract_payment_term(customer)
	if remarks:
		si.remarks = remarks
	if branch and frappe.db.exists("Branch", branch):
		si.branch = branch
	si.depot_invoice_type = invoice_type
	if address and frappe.db.exists("Address", address):
		from frappe.contacts.doctype.address.address import get_address_display

		si.customer_address = address
		si.address_display = get_address_display(address)
	si.tax_input = tax_input or ""
	currency = currency or company_currency(company)
	kurs = {k: flt(v) for k, v in (kurs or {}).items() if flt(v)}
	si.currency = currency
	# The invoice's own rate to IDR is what the ledger books. Unknown (no Currency Exchange
	# row yet) is left at 1 on the draft: build_charges refuses to convert other currencies
	# against it, and before_submit refuses to post it — finance fills it in on the draft.
	si.conversion_rate = kurs.get(currency) or kurs_idr(currency, posting) or 1
	append_lines(si, lines, kurs, manhour)

	si.flags.ignore_permissions = True
	# A foreign invoice whose rate is not known yet is saved at 1, which trips ERPNext's
	# *non-blocking* "Conversion rate is 1.00, but document currency is different…" msgprint
	# (accounts_controller.check_conversion_rate). Mute it for this programmatic insert so an
	# auto-created draft raises no popup; before_submit is where the rate is enforced.
	prev_mute = frappe.flags.mute_messages
	frappe.flags.mute_messages = True
	try:
		si.insert(ignore_permissions=True)
	finally:
		frappe.flags.mute_messages = prev_mute
	return si.name


def append_lines(si, lines, kurs, manhour=True):
	"""Append billed ``lines`` (see :func:`create_draft_sales_invoice`) to ``si``.

	Each line keeps its own currency and price; its kurs is the invoice's when it shares the
	invoice currency, else ``kurs`` (``{currency: IDR per unit}``, filled in from Currency
	Exchange for a currency it lacks). A line that brings no ``manhour`` of its own is stamped
	with the labour tariff its contract row states for that service (never priced into the
	line) — unless ``manhour`` is False."""
	# Labour tariff the contract states per service — stamped on the line, never priced into
	# it. The header totals them (see :func:`apply_manhour_charge`).
	from container_depot import pricing_model

	contract = pricing_model.active_contract(si.customer) if manhour else None
	service_item = ensure_service_item()
	posting = si.posting_date or today()
	for ln in lines:
		item_code = ln.get("item_code")
		if not item_code or not frappe.db.exists("Item", item_code):
			item_code = service_item
		line_ccy = ln.get("currency") or si.currency
		if line_ccy != si.currency and line_ccy not in kurs:
			kurs[line_ccy] = kurs_idr(line_ccy, posting)
		si.append("items", {
			"item_code": item_code,
			"description": ln.get("description") or item_code,
			"qty": ln.get("qty") or 1,
			"depot_currency": line_ccy,
			"depot_price": ln.get("rate") or 0,
			"depot_kurs": si.conversion_rate if line_ccy == si.currency else kurs.get(line_ccy),
			"depot_source": ln.get("source"),
			"manhour": ln["manhour"] if ln.get("manhour") is not None
			else _contract_tariff(ln.get("item_code"), contract, line_ccy, kurs, posting),
			# No income_account: ERPNext fills it from the Item's defaults (then its group,
			# then the company's), the same as a line picked by hand.
		})


# --------------------------------------------------------------------------- #
# Labour (manhour)
#
# A service's tariff and its labour are two different things, and the invoice keeps them
# apart to the very end (user, 2026-09-29 — the same sum the Cleaning Order shows):
#
#     Total = Total Price + (Biaya Manhour × Total Jam)   — the product is "Total Manhour"
#
# Every line shows its labour TARIFF per hour (``Sales Invoice Item.manhour``, in the line's
# own currency: off the order, else the contract row). It never touches that line's own
# amount and is not multiplied by qty. The tariffs are summed into the header's Biaya Manhour
# (``total_manhour``, in the invoice currency) and — only when ``depot_bill_manhour`` (Tagih Manhour, off by
# default) is ticked — met by the hours worked (``manhour_hour``, "Total Jam", 4 by default)
# and charged ONCE as an *Actual* Sales Taxes and Charges row — the native way to
# fold a flat amount into ERPNext's grand total while keeping it out of the items' Sub Total.
# --------------------------------------------------------------------------- #
def _contract_tariff(item_code, contract, line_ccy, kurs, date) -> float:
	"""The contract's labour tariff for a service, in the LINE's currency (0 when none).

	The rate card states it in its own row's currency, which a line priced in another currency
	(a booking charged in IDR on a USD contract) does not share: convert through IDR, like
	every line. ``kurs`` is the run's ``{currency: IDR per unit}``."""
	from container_depot import pricing_model

	rate = pricing.manhour_for(item_code, contract) if (contract and item_code) else 0.0
	if not rate:
		return 0.0
	ccy = pricing_model.item_currency(item_code, contract) or line_ccy
	if ccy == line_ccy:
		return rate
	to_idr = lambda c: flt(kurs.get(c)) or kurs_idr(c, date)  # noqa: E731
	return rate * to_idr(ccy) / (to_idr(line_ccy) or 1)


def apply_manhour_charge(doc, method=None):
	"""Total the lines' labour tariffs and charge them once: ``manhour_amount``.

	Runs after :func:`_apply_line_currency`, so every line's ``depot_kurs`` is set (a line in
	the invoice currency carries the invoice kurs, i.e. a factor of 1). The charge row itself
	is written by :func:`build_charges`, which calls this first.
	"""
	conv = flt(doc.conversion_rate) or 1
	total = sum(flt(row.get("manhour")) * (flt(row.get("depot_kurs")) or conv) / conv for row in (doc.items or []))
	doc.total_manhour = total
	if total and doc.get("depot_bill_manhour") and flt(doc.get("manhour_hour")) and _deleted_charge_row_idx(doc):
		# The user took the labour row out by hand. The row is derived, so it would simply
		# come back on this very save; reading the deletion as "no labour on this invoice"
		# is what makes Delete do something. Ticking Tagih Manhour again undoes it.
		doc.depot_bill_manhour = 0
		frappe.msgprint(
			_("Manhour dihapus — Tagih Manhour dimatikan. Centang lagi untuk menagihkannya kembali."),
			indicator="orange",
			alert=True,
		)
	doc.manhour_amount = flt(total) * flt(doc.get("manhour_hour")) if doc.get("depot_bill_manhour") else 0


def _deleted_charge_row_idx(doc) -> int:
	"""The idx the labour row held when this save drops one the invoice already had (else 0)."""
	if doc.is_new():
		return 0
	if any((t.description or "").strip() == MANHOUR_CHARGE for t in (doc.taxes or [])):
		return 0
	return cint(frappe.db.get_value("Sales Taxes and Charges", {
		"parent": doc.name,
		"parenttype": "Sales Invoice",
		"description": MANHOUR_CHARGE,
	}, "idx"))


def _item_posting(doc) -> dict:
	"""Where the invoice's item lines post: their income account and cost center.

	The labour charge rides along with them — it is the same revenue, just charged once as
	a flat amount instead of per unit. Falls back to the company defaults for a line that
	has not been through ERPNext's item fetch yet (a server-built or API invoice).
	"""
	for item in doc.items or []:
		if item.get("income_account"):
			return {
				"account": item.income_account,
				"cost_center": item.get("cost_center") or _company_cost_center(doc),
			}
	account = frappe.get_cached_value("Company", doc.company, "default_income_account") if doc.company else None
	return {"account": account, "cost_center": _company_cost_center(doc)} if account else {}


def _company_cost_center(doc):
	return frappe.get_cached_value("Company", doc.company, "cost_center") if doc.company else None


# --------------------------------------------------------------------------- #
# Pajak, potongan, kurs — the Sales Invoice's before_validate
#
# Modelled on erp_cakra: the header carries one box per charge, typed as a percentage
# ("11%") or an amount ("50000"), and every save rebuilds the native rows from them —
# discount into ERPNext's additional discount, the rest into Sales Taxes and Charges — so
# grand total, GL and AR stay ERPNext's own arithmetic. Row order is what makes labour
# taxed like the services it accompanies:
#
#     Net Total -> Manhour (Actual) -> PPN / PPh on (Net Total + Manhour) -> Materai
# --------------------------------------------------------------------------- #
def build_charges(doc, method=None):
	"""before_validate: derive line rates, the receivable, labour, discount and tax rows."""
	_apply_line_currency(doc)
	_apply_receivable(doc)
	apply_manhour_charge(doc)
	_apply_discount(doc)
	_rebuild_tax_rows(doc)


def _apply_line_currency(doc):
	"""Each line's rate, in the invoice currency, from its own price and currency.

	    rate = Harga × Kurs IDR baris / Kurs IDR invoice

	IDR is the pivot because it is the ledger's currency: every kurs on the invoice is "IDR
	per unit", so a USD invoice can carry an IDR line (and vice versa) without a cross rate
	anyone has to maintain. A line in the invoice's own currency takes the invoice kurs and
	its price unchanged — no rounding through IDR.
	"""
	header = doc.currency or company_currency(doc.company)
	base = company_currency(doc.company)
	conv = flt(doc.conversion_rate) or 1
	for i, row in enumerate(doc.items or [], start=1):
		row.depot_currency = row.get("depot_currency") or header
		if not flt(row.get("depot_price")) and flt(row.rate) and row.depot_currency == header:
			# A line written before per-line currency existed (or by ERPNext's own item fetch)
			# carries only ``rate``: that IS its price in the invoice currency.
			row.depot_price = flt(row.rate)
		if row.depot_currency == header:
			row.depot_kurs = conv
			row.rate = flt(row.depot_price)
		else:
			if not flt(row.get("depot_kurs")):
				row.depot_kurs = kurs_idr(row.depot_currency, doc.get("posting_date"))
			if not flt(row.depot_kurs):
				frappe.throw(
					_("Baris {0}: isi <b>Kurs ke IDR</b> untuk {1} (belum ada di Currency Exchange).").format(
						i, row.depot_currency
					)
				)
			if header != base and conv == 1:
				frappe.throw(
					_("Isi dulu kurs invoice {0} ke IDR — baris {1} ({2}) dikonversi lewat kurs itu.").format(
						header, i, row.depot_currency
					)
				)
			row.rate = flt(row.depot_price) * flt(row.depot_kurs) / conv
		# rate is fully decided above. Keep ERPNext's price-list / margin machinery from
		# re-deriving it: a stale margin left by the client would otherwise be added back
		# on top (erp_cakra hit this as "rate nearly doubles when the kurs goes up").
		row.price_list_rate = row.rate
		row.margin_type = ""
		row.margin_rate_or_amount = 0
		row.rate_with_margin = 0
		row.discount_percentage = 0
		row.discount_amount = 0


def _apply_receivable(doc):
	"""A foreign invoice books to a receivable in its own currency, an IDR one to the party's.

	ERPNext takes a Payment Entry's currency from the invoice's ``debit_to``, not from the
	document, so this is what makes Create > Payment come out in USD for a USD invoice.
	Drafts only: a posted invoice's receivable is history."""
	if doc.docstatus != 0 or not (doc.company and doc.customer):
		return
	base = company_currency(doc.company)
	acc_ccy = frappe.get_cached_value("Account", doc.debit_to, "account_currency") if doc.debit_to else None
	if doc.currency and doc.currency != base:
		if acc_ccy != doc.currency:
			doc.debit_to = ensure_receivable_account(doc.company, doc.currency) or doc.debit_to
	elif acc_ccy and acc_ccy != base:
		from erpnext.accounts.party import get_party_account

		doc.debit_to = get_party_account("Customer", doc.customer, doc.company)


def _apply_discount(doc):
	"""Diskon box -> ERPNext's own additional discount on Net Total (before labour and tax)."""
	mode, num = parse_smart(doc.get("discount_input"))
	doc.apply_discount_on = "Net Total"
	doc.additional_discount_percentage = num if mode == "pct" else 0
	doc.discount_amount = num if mode == "amt" else 0


def _tax_accounts(company) -> dict:
	s = frappe.get_cached_doc("Depot Finance Settings")
	from container_depot.install import _output_vat_account

	return {
		"ppn": s.get("ppn_account") or _output_vat_account(company),
		"pph": s.get("pph23_account"),
		"materai": s.get("materai_account"),
	}


@frappe.whitelist()
def tax_accounts(company=None) -> dict:
	"""The PPN / PPh 23 / Materai accounts, for the form's live recalculation."""
	return _tax_accounts(company or get_default_company())


def _need(account, label):
	if not account:
		frappe.throw(_("Isi akun <b>{0}</b> di Depot Finance Settings dulu.").format(label))
	return account


def _rebuild_tax_rows(doc):
	"""Rewrite the managed charge rows from the header boxes; keep any other row as typed.

	A row on one of the managed accounts is treated as managed too: that is where a Sales
	Taxes and Charges Template (or a hand-added "PPN" row) lands, and leaving it would charge
	PPN twice. Any other row the user added is kept, after the managed ones, with its
	references re-pointed at the row it referred to (``row_id`` is an index, so it moves).
	"""
	accounts = _tax_accounts(doc.company)
	managed_accounts = {a for a in accounts.values() if a}
	old = list(doc.taxes or [])
	by_idx = {cint(t.idx): t for t in old}
	kept = [
		t for t in old
		if (t.description or "").strip() not in _MANAGED_CHARGES and t.account_head not in managed_accounts
	]

	rows = []
	posting = _item_posting(doc)
	cost_center = posting.get("cost_center") or _company_cost_center(doc)
	if flt(doc.get("manhour_amount")) and posting.get("account"):
		rows.append({
			"charge_type": "Actual", "description": MANHOUR_CHARGE, "account_head": posting["account"],
			"tax_amount": flt(doc.manhour_amount), "cost_center": posting.get("cost_center"),
		})
	# Percentages are charged on Net Total + labour when there is labour, which in ERPNext
	# terms is "the running total after row 1".
	basis = {"charge_type": "On Previous Row Total", "row_id": "1"} if rows else {"charge_type": "On Net Total"}

	def add(desc, account, mode, num, sign=1):
		if not num:
			return
		row = {"description": desc, "account_head": account, "cost_center": cost_center}
		if mode == "pct":
			row.update(basis, rate=sign * num)
		else:
			row.update(charge_type="Actual", tax_amount=sign * num)
		rows.append(row)

	if not doc.get("ignore_tax"):
		mode, num = parse_smart(doc.get("tax_input"))
		add(PPN_CHARGE, num and _need(accounts["ppn"], "PPN Keluaran"), mode, num)
	mode, num = parse_smart(doc.get("pph_input"))
	add(PPH_CHARGE, num and _need(accounts["pph"], "PPh 23"), mode, num, sign=-1)
	materai = flt(doc.get("materai"))
	add(MATERAI_CHARGE, materai and _need(accounts["materai"], "Materai"), "amt", materai)

	managed_count = len(rows)
	for t in kept:
		row = t.as_dict(no_default_fields=True)
		for f in ("parent", "parentfield", "parenttype", "idx", "doctype"):
			row.pop(f, None)
		chained = row.get("charge_type") in ("On Previous Row Total", "On Previous Row Amount")
		ref = by_idx.get(cint(t.row_id)) if chained else None
		if row.get("charge_type") == "On Net Total" or (chained and not any(ref is k for k in kept)):
			# It stood on the net total, or on a managed row that has just been rebuilt:
			# it now stands where the managed percentages do.
			row.update(charge_type=basis["charge_type"], row_id=basis.get("row_id"))
		elif chained:
			row["row_id"] = str(managed_count + next(i for i, k in enumerate(kept) if k is ref) + 1)
		rows.append(row)

	doc.set("taxes", rows)
	doc.taxes_and_charges = None


def check_kurs(doc, method=None):
	"""before_submit: a foreign invoice may not post at kurs 1 — the ledger books IDR."""
	if doc.currency != company_currency(doc.company) and flt(doc.conversion_rate) in (0, 1):
		frappe.throw(
			_("Kurs {0} ke IDR belum diisi (Exchange Rate masih 1). Isi dulu sebelum submit.").format(doc.currency)
		)


# --- "10%" or "50000" ------------------------------------------------------------ #
def _to_number(s) -> float:
	"""A number typed in either locale ("1.234,56" / "1,234.56" / "2.000.000" / "11,5").

	When both separators appear, the LAST one is the decimal point. With one kind only, a
	strict thousands pattern ("2,000,000") is grouping; anything else is a decimal ("11,5").
	Ported from erp_cakra, where "2,000,000" was once read as 2.
	"""
	s = re.sub(r"[^\d.,-]", "", s or "")
	if not s:
		return 0.0
	last_dot, last_comma = s.rfind("."), s.rfind(",")
	dec = None
	if last_dot != -1 and last_comma != -1:
		dec = "." if last_dot > last_comma else ","
	elif last_comma != -1:
		dec = None if re.match(r"^-?\d{1,3}(,\d{3})+$", s) else ","
	elif last_dot != -1:
		dec = None if re.match(r"^-?\d{1,3}(\.\d{3})+$", s) else "."
	intp, frac = (s[: s.rfind(dec)], s[s.rfind(dec) + 1 :]) if dec else (s, "")
	intp, frac = re.sub(r"[.,]", "", intp), re.sub(r"[.,]", "", frac)
	try:
		return float(intp + ("." + frac if frac else ""))
	except ValueError:
		return 0.0


def parse_smart(raw):
	"""'11%' -> ('pct', 11.0); '50.000' -> ('amt', 50000.0); blank -> (None, 0.0)."""
	if raw is None or (isinstance(raw, str) and not raw.strip()):
		return (None, 0.0)
	if not isinstance(raw, str):
		return ("amt", flt(raw))
	return ("pct", _to_number(raw)) if "%" in raw else ("amt", _to_number(raw))


def refuse_depot_amend(doc, method=None):
	"""before_insert: an invoice billed from depot orders is never Amended.

	Its cancel gave every order back (``consolidated_billing.rollback_billed_sources``) and
	cleared the manifest, so the amended copy carried the old lines with nothing tying the
	orders to it — the next Ambil Tagihan billed them a second time (2026-10-09 audit). Bill
	the orders again from Ambil Tagihan instead."""
	# A booking's own (Cash) invoice the same: its cancel dropped the booking's link, so the
	# amended copy was paid while the booking stayed Unpaid and the gate stayed shut. That
	# booking raises its next invoice itself (Regenerate Invoice).
	if doc.get("amended_from") and (
		frappe.db.exists("Sales Invoice Item", {"parent": doc.amended_from, "depot_source": ["is", "set"]})
		or frappe.db.get_value("Sales Invoice", doc.amended_from, "depot_invoice_type") == "Booking"
	):
		frappe.throw(
			_("Invoice {0} adalah tagihan order depo — jangan di-Amend. Tagih ulang lewat Ambil Tagihan / Regenerate Invoice di booking.").format(
				doc.amended_from
			),
			title=_("Tidak Bisa Amend"),
		)


# --------------------------------------------------------------------------- #
# Invoice number: INV-{branch}-OAK-{yy}-0001
# --------------------------------------------------------------------------- #
def default_branch(doc, method=None):
	"""before_insert: an invoice raised by someone who works one branch belongs to it; one
	billed from depot orders (Ambil Tagihan, monthly) belongs to the branch of their depot.

	Runs before naming, which is what reads the branch."""
	if doc.get("branch"):
		return
	from container_depot.container_depot.user_branch import get_user_branches

	branches = get_user_branches() or []
	doc.branch = branches[0] if len(branches) == 1 else _branch_of_lines(doc)


def _branch_of_lines(doc):
	"""The branch of the first billed order that has one: its own, or its depot's."""
	for row in doc.get("items") or []:  # a Payment Entry has none (it shares default_branch)
		dt, _sep, name = (row.get("depot_source") or "").partition("|")
		if not (name and frappe.db.exists("DocType", dt)):
			continue  # a hand-typed line, or the pre-ledger "Storage|TANK" source
		meta = frappe.get_meta(dt)
		if meta.has_field("branch"):
			branch = frappe.db.get_value(dt, name, "branch")
		elif meta.has_field("depot"):
			branch = frappe.db.get_value("Depot", frappe.db.get_value(dt, name, "depot"), "branch")
		else:
			branch = None
		if branch:
			return branch
	return None


def header_rules(doc, method=None):
	"""before_validate: the header the erp_cakra way.

	Invoice Date is ``posting_date`` and always the user's to set: without set_posting_time
	ERPNext resets it to today on every save. The header Cost Center, when given, is the one
	every line posts to — the lines no longer show their own.

	The Payment Term is a label (depot_payment_term); ERPNext's own template is kept off drafts
	(DepotSalesInvoice.set_payment_schedule). The Due Date is optional on the form: left empty
	it is 30 days after the Invoice Date, like every invoice the system raises. The (hidden)
	schedule is rebuilt from it on every draft save — one row at the Due Date."""
	if doc.docstatus == 0:
		doc.set_posting_time = 1
	if doc.docstatus == 0 and not doc.get("is_return"):
		if not doc.get("due_date") and doc.get("posting_date"):
			doc.due_date = add_days(doc.posting_date, 30)
		doc.set("payment_schedule", [])
	if doc.get("cost_center"):
		for row in doc.items or []:
			row.cost_center = doc.cost_center


@frappe.whitelist()
def contract_payment_term(customer):
	"""The customer's Payment Term as its Active contract states it: Cash, or its NET n."""
	from container_depot.container_depot.doctype.depot_contract.depot_contract import get_active_contract

	c = get_active_contract(customer) if customer else None
	if not c:
		return None
	return "Cash" if c.payment_type == "Cash" else c.payment_terms


def check_branch(doc, method=None):
	"""before_submit: Branch is required. Drafts the system raises may still lack it (an order
	with no depot); the form asks for it, and nothing leaves draft without one."""
	if not doc.get("branch"):
		frappe.throw(_("Isi <b>Branch</b> dulu sebelum submit."))


def check_no_payments(doc, method=None):
	"""before_cancel: cancel the receipt first, then the invoice (as in erp_cakra).

	Frappe would refuse anyway (the receipt's Dokumen row still links the invoice), but with a
	raw link error. Cancelling the receipt reverses the money in the books; the invoice can then
	be cancelled and its orders go back to unbilled."""
	pes = sorted(
		set(frappe.get_all("Payment Entry Reference", filters={"reference_doctype": doc.doctype, "reference_name": doc.name, "docstatus": 1}, pluck="parent"))
		| set(frappe.get_all("Payment Entry Line", filters={"document_type": doc.doctype, "document_no": doc.name, "docstatus": 1}, pluck="parent"))
	)
	if pes:
		frappe.throw(
			_("Invoice ini sudah dibayar. Cancel dulu pembayarannya: {0}").format(", ".join(pes)),
			title=_("Sudah dibayar"),
		)


def branch_code(branch, company=None) -> str:
	"""The branch's code in invoice numbers; the company abbr for an invoice with no branch."""
	if branch:
		code = frappe.db.get_value("Branch", branch, "branch_code")
		if code and code.strip():
			return code.strip().upper()
		word = re.sub(r"^oak\s+", "", branch, flags=re.I)
		return re.sub(r"[^A-Za-z0-9]", "", word)[:3].upper() or "X"
	return (company and frappe.get_cached_value("Company", company, "abbr")) or "OD"


def autoname(doc, method=None):
	"""INV-{branch}-OAK-{yy}-####, counting per branch per year of the posting date.

	Credit notes keep ERPNext's own return series. Amendments never get here: Frappe names
	them after the invoice they amend (INV-...-0001-1) before calling autoname."""
	if doc.get("is_return"):
		return
	from frappe.model.naming import getseries

	yy = getdate(doc.get("posting_date") or today()).strftime("%y")
	prefix = f"{INVOICE_PREFIX}-{branch_code(doc.get('branch'), doc.get('company'))}-{INVOICE_COMPANY_CODE}-{yy}-"
	doc.name = prefix + getseries(prefix, 4)


# --------------------------------------------------------------------------- #
# Manual invoice: what a picked item starts at
# --------------------------------------------------------------------------- #
@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def invoice_item_query(doctype, txt, searchfield, start, page_len, filters):
	"""The invoice line's item picker: the whole catalogue, most-used first, like the M&R's.

	Unlike the order pickers a part is never hidden for being out of stock — the invoice
	bills it, it does not issue it.
	"""
	from container_depot.container_depot import item_catalog

	rows = item_catalog.search_items(txt=txt, start=start, page_length=page_len)
	return [[r["item_code"], r.get("item_name")] for r in rows]


@frappe.whitelist()
def invoice_attachments(sales_invoice):
	"""The invoice's files per attachment box (``attached_to_field``): Attachment, Paid Attachment.

	Read through the invoice's own permission — File's list rules would hide a colleague's
	upload from a user who can read the invoice."""
	frappe.get_doc("Sales Invoice", sales_invoice).check_permission("read")
	out = {}
	for f in frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Sales Invoice", "attached_to_name": sales_invoice},
		fields=["name", "file_name", "file_url", "attached_to_field"],
		order_by="creation asc",
	):
		out.setdefault(f.attached_to_field or "", []).append(f)
	return out


@frappe.whitelist()
def item_defaults(customer, item_code, currency=None, posting_date=None):
	"""Starting price, currency, kurs and labour tariff for an item typed onto an invoice by hand.

	The contract is only the STARTING price — the same rule the orders follow: it fills a
	fresh line and never touches it again. An item the contract does not price starts at 0
	in the customer's own currency."""
	from container_depot import pricing_model

	contract = pricing_model.active_contract(customer) if customer else None
	row = pricing_model.tariff_row(item_code, contract) if contract else None
	line_ccy = (
		(row and row.get("currency"))
		or pricing_model.currency_for_customer(customer, contract)
		or currency
		or company_currency()
	)
	return {
		"depot_currency": line_ccy,
		"depot_price": flt(row.rate) if row else 0,
		"depot_kurs": kurs_idr(line_ccy, posting_date),
		"manhour": pricing.manhour_for(item_code, contract) if contract else 0,
	}
