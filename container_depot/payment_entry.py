"""Payment Entry, the erp_cakra way — on top of ERPNext's own controller.

What the depot's Payment Entry adds (ported from erp_cakra ``overrides/payment_entry.py``):

* **Number** ``{PE|RV}-{bank}-{abbr}-{YYYY}-{roman month}-0001`` (``STL`` for a settlement,
  no bank segment for Expense/Income).
* **Dokumen / Item** grid (``depot_lines``) — the one place a payment is filled:
  - with a party: the invoices it settles, picked from what is outstanding
    (:func:`get_payment_documents`), each with an optional Credit / Debit Note. The native
    ``references`` are DERIVED from these lines on every save;
  - **Expense / Income** mode (``depot_direct``, no party): each line is an account + amount,
    posted straight against the bank.
* **Potongan & Biaya** header boxes — PPN, PPh ("11%" or an amount), Materai, Biaya Admin —
  become native ``deductions`` rows, so ERPNext's own difference / unallocated arithmetic
  balances them.
* **Kasbon** (``depot_kasbon``): a paid Pending Cash can fund the payment. The credit then goes
  to the advance account the kasbon debited, not to the bank a second time.
* **Settlement** mode of payment: the bank side is replaced by a chosen account.
* **Bank**: the bank picked on the form fills the bank side through its company Bank Account.
* The **amount** is the user's (typed, or the Pay / Receive button); left empty it is worked
  out from the lines. Paying more leaves the rest unallocated — ERPNext's own advance. A tail
  under Rp 1 against the invoices goes to a "Pembulatan" deduction.
* **Dont Post To GL**: submitted without a journal.
* Cheque / reference number is not mandatory.

The form is erp_cakra's layout (install.PAYMENT_FORM, public/js/payment_entry.js).

Deliberately NOT ported: erp_cakra's foreign-currency Expense Note path (this app has no
Expense Note), Validate/Void workflow and the candidate cache (it was shared across users and
read with ignore_permissions — here every call is permission-checked and branch-scoped instead).
"""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.model.naming import getseries
from frappe.utils import flt, getdate, nowdate, today

try:
	# hrms overrides Payment Entry too (Expense Claim / Employee Advance references). Only one
	# override_doctype_class wins, so build on top of it rather than replace it.
	from hrms.overrides.employee_payment_entry import EmployeePaymentEntry as PaymentEntry
except ImportError:
	from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry

from container_depot.invoicing import parse_smart

_ROMAN = ("", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII")
SETTLEMENT = "Settlement"
ROUNDING = "Pembulatan"
# Only the sub-rupiah tail of a decimal price is absorbed; more than this is a typing mistake
# and ERPNext's "Difference Amount must be zero" should stop it.
ROUNDING_LIMIT = 1.0

# Header boxes -> deduction rows: (amount getter, description, account key, Pay direction).
# Pay: +1 = the account is debited and the bank pays more (PPN, Materai, Admin); -1 = it is
# credited and the bank pays less (PPh withheld from the supplier). Receive: every component
# is a cut from what comes in (PPh / PPN withheld by the customer, bank fee, materai), so all
# are debited.
_COMPONENTS = (
	("ppn", "PPN", 1),
	("materai", "Materai", 1),
	("admin", "Biaya Admin", 1),
	("pph", "PPh", -1),
)


def _is_settlement(doc) -> bool:
	return (doc.get("mode_of_payment") or "").strip().lower() == SETTLEMENT.lower()


def _company_currency(doc):
	return frappe.get_cached_value("Company", doc.company, "default_currency")


def _bank_field(doc):
	return "paid_from" if doc.payment_type == "Pay" else "paid_to"


def _party_field(doc):
	return "paid_to" if doc.payment_type == "Pay" else "paid_from"


def _bank_code(doc) -> str:
	"""First word of the bank account's name: "BCA 123-456" -> BCA, "Cash - OD" -> CASH."""
	acc = doc.get(_bank_field(doc))
	name = frappe.get_cached_value("Account", acc, "account_name") if acc else ""
	code = re.sub(r"[^A-Za-z0-9]", "", (name or "").split()[0] if name else "").upper()
	return code or "XXX"


class DepotPaymentEntry(PaymentEntry):
	def autoname(self):
		"""{PE|RV}-{bank}-{abbr}-{YYYY}-{roman}-####, counting per prefix (so per type, bank,
		company, year and month). Amendments never get here — Frappe names them NAME-1."""
		_prepare_sides(self)
		d = getdate(self.posting_date or today())
		kind = "RV" if self.payment_type == "Receive" else "PE"
		seg = "STL" if _is_settlement(self) else ("" if self.get("depot_direct") else _bank_code(self))
		abbr = frappe.get_cached_value("Company", self.company, "abbr")
		prefix = "-".join([kind] + ([seg] if seg else []) + [abbr, str(d.year), _ROMAN[d.month]]) + "-"
		self.name = prefix + getseries(prefix, 4)

	def make_gl_entries(self, *args, **kwargs):
		"""Dont Post To GL: a record only. No ledger, so the invoices it names stay outstanding."""
		if self.get("depot_dont_post_to_gl"):
			return
		return super().make_gl_entries(*args, **kwargs)

	def set_title(self):
		"""Expense / Income has no party: the title is who was paid (Pay To), not "None"."""
		if self.get("depot_direct"):
			self.title = self.get("depot_pay_to") or _("Expense / Income")
			return
		return super().set_title()

	def validate_transaction_reference(self):
		"""Cheque / reference no. is not required: most payments are recorded before the bank
		reference is known. The fields stay on the form."""
		return

	def set_missing_values(self):
		if self.get("depot_direct"):
			return  # no party: core would throw "Party is mandatory"
		super().set_missing_values()

	def set_missing_ref_details(self, *args, **kwargs):
		if self.get("depot_direct"):
			return
		return super().set_missing_ref_details(*args, **kwargs)

	def set_difference_amount(self):
		if not self.get("depot_direct"):
			return super().set_difference_amount()
		# The lines stand in for the party side: bank ± deductions must equal the lines.
		lines = sum(flt(r.amount) for r in _direct_lines(self))
		deductions = sum(flt(d.amount) for d in self.get("deductions") or [])
		if self.payment_type == "Pay":
			diff = flt(self.base_paid_amount) - lines - deductions
		else:
			diff = lines - flt(self.base_received_amount) - deductions
		self.difference_amount = flt(diff, self.precision("difference_amount"))

	# ---- GL --------------------------------------------------------------------
	def add_party_gl_entries(self, gl_entries):
		if not self.get("depot_direct"):
			start = len(gl_entries)
			super().add_party_gl_entries(gl_entries)
			self._kasbon_against(gl_entries, start)
			return
		# Expense / Income: one GL row per line, against the bank (IDR only — see
		# _apply_direct, which refuses a foreign bank).
		against = self.get(_bank_field(self))
		default_cc = self.cost_center or frappe.get_cached_value("Company", self.company, "cost_center")
		for r in _direct_lines(self):
			amt = flt(r.amount)
			side = "debit" if self.payment_type == "Pay" else "credit"
			gl_entries.append(self.get_gl_dict({
				"account": r.account,
				"against": against,
				"cost_center": r.cost_center or default_cc,
				side: amt,
				f"{side}_in_account_currency": amt,
				"remarks": " - ".join(x for x in (r.get("description"), r.get("remark")) if x) or self.remarks,
			}, item=r))

	def _bank_side(self):
		"""(GL side, account, account currency, rate, company-currency amount) of the bank."""
		if self.payment_type == "Receive":
			return "debit", self.paid_to, self.paid_to_account_currency, flt(self.target_exchange_rate) or 1, flt(self.base_received_amount)
		return "credit", self.paid_from, self.paid_from_account_currency, flt(self.source_exchange_rate) or 1, flt(self.base_paid_amount)

	def add_bank_gl_entries(self, gl_entries):
		"""Funded by Pending Cash: its advance / deposit account takes the bank's place.

		The money already moved when it was paid — a kasbon out of the bank (Dr Uang Muka / Cr
		Bank), a deposit into it (Dr Bank / Cr Deposit). Charging the bank again would move it
		twice. So a Pay credits the advance and a Receive debits the deposit; the bank takes what
		they do not cover, and what they over-cover goes back the other way.
		"""
		funding = _kasbon_funding(self)
		if not funding:
			return super().add_bank_gl_entries(gl_entries)
		side, bank, bank_ccy, rate, total = self._bank_side()
		against = self.party or (self.paid_from if side == "debit" else self.paid_to)
		for f in funding:
			gl_entries.append(self.get_gl_dict({
				"account": f["account"],
				"party_type": f["party_type"],
				"party": f["party"],
				"against": against,
				"account_currency": frappe.get_cached_value("Account", f["account"], "account_currency"),
				side: f["amount"],
				f"{side}_in_account_currency": f["amount"],
				"cost_center": self.cost_center,
				"post_net_value": True,
			}, item=self))
		from_bank = total - sum(f["amount"] for f in funding)
		if abs(from_bank) > 0.005:
			bank_side = side if from_bank > 0 else ("credit" if side == "debit" else "debit")
			gl_entries.append(self.get_gl_dict({
				"account": bank,
				"account_currency": bank_ccy,
				"against": against,
				bank_side: abs(from_bank),
				f"{bank_side}_in_account_currency": abs(from_bank) / rate,
				"cost_center": self.cost_center,
				"post_net_value": True,
			}, item=self))

	def _kasbon_against(self, gl_entries, start):
		"""The party rows' "against" names the accounts that actually paid them."""
		funding = _kasbon_funding(self)
		if not funding:
			return
		_side, bank, _ccy, _rate, total = self._bank_side()
		accounts = list(dict.fromkeys(f["account"] for f in funding))
		if total - sum(f["amount"] for f in funding) > 0.005:
			accounts.append(bank)
		for row in gl_entries[start:]:
			if row.get("party"):
				row["against"] = ", ".join(accounts)


# --------------------------------------------------------------------------- #
# before_validate
# --------------------------------------------------------------------------- #
def before_validate(doc, method=None):
	if doc.payment_type not in ("Pay", "Receive"):
		return
	_prepare_sides(doc)
	if not doc.get("depot_direct") and not doc.get("party_type"):
		# The form hides Party Type: it follows the direction.
		doc.party_type = "Customer" if doc.payment_type == "Receive" else "Supplier"
	if not doc.branch:
		from container_depot.invoicing import default_branch

		default_branch(doc)
	_lines_from_references(doc)
	_derive_references(doc)
	_apply_advance(doc)
	_apply_components(doc)
	_apply_amounts(doc)
	_apply_rounding(doc)
	_apply_kasbon(doc)
	_apply_remark(doc)
	doc.depot_bank_amount = _bank_amount(doc)
	doc.depot_references = ", ".join(dict.fromkeys(r.reference_name for r in doc.get("references") or []))


def _prepare_sides(doc):
	"""Settlement account, the bank side, and the Expense/Income placeholders."""
	if _is_settlement(doc):
		if not doc.get("depot_settlement_account"):
			frappe.throw(_("Mode of Payment <b>Settlement</b>: pilih <b>Akun Settlement</b>."))
		doc.set(_bank_field(doc), doc.depot_settlement_account)
	_fill_bank_side(doc)
	if doc.get("depot_direct"):
		_apply_direct(doc)


def _fill_bank_side(doc):
	"""The bank side (Pay: paid_from, Receive: paid_to), the erp_cakra way: from the Bank picked
	on the form, through its company Bank Account; without one, from the mode of payment's
	account, else the company's default bank / cash. Settlement has put its account there."""
	side = _bank_field(doc)
	if _is_settlement(doc):
		doc.depot_bank = doc.bank_account = None
	elif doc.get("depot_bank"):
		current = frappe.db.get_value("Bank Account", doc.bank_account, "bank") if doc.get("bank_account") else None
		if current != doc.depot_bank:
			ba = frappe.db.get_value(
				"Bank Account",
				{"bank": doc.depot_bank, "company": doc.company, "is_company_account": 1, "disabled": 0},
				["name", "account"], as_dict=True,
			)
			if not ba:
				frappe.throw(_("Bank <b>{0}</b> belum punya Bank Account (rekening company).").format(doc.depot_bank))
			doc.bank_account = ba.name
			doc.set(side, ba.account)
		elif not doc.get(side):
			doc.set(side, frappe.db.get_value("Bank Account", doc.bank_account, "account"))
	if not doc.get(side):
		acc = None
		if doc.get("mode_of_payment"):
			acc = frappe.db.get_value(
				"Mode of Payment Account", {"parent": doc.mode_of_payment, "company": doc.company}, "default_account"
			)
		acc = acc or frappe.get_cached_value("Company", doc.company, "default_bank_account") or frappe.get_cached_value(
			"Company", doc.company, "default_cash_account"
		)
		if not acc:
			frappe.throw(_("Akun Kas/Bank belum terisi. Pilih <b>Bank</b>, atau isi akun default di Mode of Payment."))
		doc.set(side, acc)
	if not _is_settlement(doc) and not doc.get("depot_bank"):
		# An account that came some other way still names its bank, so the form shows it.
		ba = frappe.db.get_value(
			"Bank Account", {"account": doc.get(side), "company": doc.company, "is_company_account": 1},
			["name", "bank"], as_dict=True,
		)
		if ba:
			doc.bank_account = doc.bank_account or ba.name
			doc.depot_bank = ba.bank
	for cur_f, acc_f in (("paid_from_account_currency", "paid_from"), ("paid_to_account_currency", "paid_to")):
		if doc.get(acc_f) and not doc.get(cur_f):
			doc.set(cur_f, frappe.get_cached_value("Account", doc.get(acc_f), "account_currency"))


def _direct_lines(doc):
	return [r for r in doc.get("depot_lines") or [] if not r.get("document_no") and flt(r.amount)]


def _apply_direct(doc):
	"""Expense / Income: no party, the lines post to their own accounts."""
	doc.party_type = doc.party = doc.party_name = None
	doc.set("references", [])
	lines = _direct_lines(doc)
	if not lines:
		frappe.throw(_("Mode Expense / Income: isi minimal satu baris (Account + Amount)."))
	missing = [str(r.idx) for r in lines if not r.get("account")]
	if missing:
		frappe.throw(_("Mode Expense / Income: baris {0} belum punya Account.").format(", ".join(missing)))
	bank = doc.get(_bank_field(doc))
	ccy = frappe.get_cached_value("Account", bank, "account_currency") or _company_currency(doc)
	if ccy != _company_currency(doc):
		# erp_cakra posted a foreign bank's lines at face value as company currency.
		frappe.throw(_("Mode Expense / Income hanya untuk akun Kas/Bank {0}.").format(_company_currency(doc)))
	# The party side is not posted in this mode (add_party_gl_entries writes the lines), but
	# the schema wants both accounts: the bank stands in for it.
	doc.set(_party_field(doc), doc.get(_party_field(doc)) or bank)
	doc.paid_from_account_currency = doc.paid_to_account_currency = ccy
	doc.source_exchange_rate = doc.target_exchange_rate = 1


def _lines_from_references(doc):
	"""A payment made from an invoice (Create > Payment) or with ERPNext's own "Get
	Outstanding Invoices" arrives with ``references`` and no lines: turn them into lines,
	so the grid stays the one place the payment is read and edited."""
	if doc.get("depot_direct") or any(r.get("document_no") for r in doc.get("depot_lines") or []):
		return
	for r in doc.get("references") or []:
		if r.reference_doctype not in ("Sales Invoice", "Purchase Invoice") or r.get("depot_from_line"):
			continue
		doc.append("depot_lines", {
			"document_type": r.reference_doctype,
			"document_no": r.reference_name,
			"date": frappe.db.get_value(r.reference_doctype, r.reference_name, "posting_date"),
			"grand_total": flt(r.total_amount),
			"outstanding": flt(r.outstanding_amount),
			"amount": flt(r.allocated_amount),
		})


def _derive_references(doc):
	"""``references`` = the document lines. Hand-made reference rows (other doctypes) stay."""
	if doc.get("depot_direct"):
		return
	lines = [r for r in doc.get("depot_lines") or [] if r.get("document_no")]
	keep = [
		r for r in doc.get("references") or []
		if not r.get("depot_from_line") and r.reference_doctype not in ("Sales Invoice", "Purchase Invoice")
	]
	doc.set("references", keep)
	for r in lines:
		# An empty amount means "all of it". A return is outstanding NEGATIVE and is kept so.
		r.amount = flt(r.amount) or flt(r.outstanding)
		doc.append("references", {
			"reference_doctype": r.document_type,
			"reference_name": r.document_no,
			"total_amount": flt(r.grand_total),
			"outstanding_amount": flt(r.outstanding),
			"allocated_amount": r.amount,
			"depot_from_line": 1,
		})
	if lines:
		_sync_party_account(doc)


def _sync_party_account(doc):
	"""The party side must be the account the invoices were booked to (ERPNext's rule), and
	one payment can only settle invoices on one account."""
	field = "debit_to" if doc.payment_type == "Receive" else "credit_to"
	accounts = {}
	for r in doc.get("references") or []:
		if r.reference_doctype in ("Sales Invoice", "Purchase Invoice"):
			acc = frappe.db.get_value(r.reference_doctype, r.reference_name, field)
			accounts.setdefault(acc, r.reference_name)
	if len(accounts) > 1:
		frappe.throw(
			_("Dokumen yang dipilih memakai akun {0} berbeda: {1}. Pisahkan jadi beberapa Payment Entry.").format(
				_("piutang") if doc.payment_type == "Receive" else _("hutang"),
				", ".join(f"<b>{a}</b> ({n})" for a, n in accounts.items()),
			)
		)
	if accounts:
		acc = next(iter(accounts))
		doc.set(_party_field(doc), acc)
		ccy_field = "paid_from_account_currency" if doc.payment_type == "Receive" else "paid_to_account_currency"
		doc.set(ccy_field, frappe.get_cached_value("Account", acc, "account_currency"))


def _component_accounts(doc) -> dict:
	s = frappe.get_cached_doc("Depot Finance Settings")
	if doc.payment_type == "Receive":
		from container_depot.invoicing import _tax_accounts

		sales = _tax_accounts(doc.company)
		return {
			"ppn": sales["ppn"],
			"pph": s.get("pph23_account"),
			"materai": s.get("materai_expense_account"),
			"admin": s.get("admin_fee_account"),
		}
	return {
		"ppn": s.get("pay_ppn_account"),
		"pph": s.get("pay_pph_account"),
		"materai": s.get("materai_expense_account"),
		"admin": s.get("admin_fee_account"),
	}


def _component_amounts(doc) -> dict:
	"""The header boxes as amounts. A percentage is taken of the lines being paid."""
	base = sum(flt(r.amount) for r in doc.get("depot_lines") or [])

	def smart(raw):
		mode, num = parse_smart(raw)
		return flt(base) * num / 100 if mode == "pct" else num

	return {
		"ppn": smart(doc.get("depot_tax_input")),
		"pph": smart(doc.get("depot_pph_input")),
		"materai": flt(doc.get("depot_materai")),
		"admin": flt(doc.get("depot_admin_fee")),
	}


def _apply_components(doc):
	"""Credit / Debit Notes on the lines and the header boxes -> native deduction rows.

	Rows this builds are flagged ``depot_auto`` and rebuilt on every save; rows a user typed
	and ERPNext's exchange gain/loss row are left alone. (erp_cakra recognised its own rows by
	their description, so a hand-typed row starting "PPh…" vanished on save.)

	    bank = alokasi + Credit Note − Debit Note ± komponen
	"""
	rows = []
	default_cc = doc.cost_center or frappe.get_cached_value("Company", doc.company, "cost_center")
	for r in doc.get("depot_lines") or []:
		if not r.get("document_no"):
			continue
		cn, dn = flt(r.credit_amount), flt(r.debit_amount)
		if cn and not r.credit_account:
			frappe.throw(_("Baris {0}: Credit Note terisi, Credit Account belum.").format(r.document_no))
		if dn and not r.debit_account:
			frappe.throw(_("Baris {0}: Debit Note terisi, Debit Account belum.").format(r.document_no))
		# A return line is allocated negative, so both notes flip with it; and Receive books
		# the notes the other way round from Pay (money coming in, not going out).
		sign = (-1 if flt(r.amount) < 0 else 1) * (-1 if doc.payment_type == "Receive" else 1)
		if cn:
			rows.append((r.credit_account, default_cc, sign * cn, f"Credit Note {r.document_no}"))
		if dn:
			rows.append((r.debit_account, default_cc, -sign * dn, f"Debit Note {r.document_no}"))

	amounts = _component_amounts(doc)
	accounts = None
	for key, label, direction in _COMPONENTS:
		amt = flt(amounts[key])
		if not amt:
			continue
		accounts = accounts or _component_accounts(doc)
		if not accounts.get(key):
			frappe.throw(_("Isi akun <b>{0}</b> ({1}) di Depot Finance Settings dulu.").format(label, doc.payment_type))
		rows.append((accounts[key], default_cc, (direction if doc.payment_type == "Pay" else 1) * amt, label))

	keep = [d for d in doc.get("deductions") or [] if not d.get("depot_auto")]
	doc.set("deductions", keep)
	for account, cc, amount, desc in rows:
		doc.append("deductions", {
			"account": account, "cost_center": cc, "amount": amount, "description": desc, "depot_auto": 1,
		})


def _apply_amounts(doc):
	"""Paid / received, so ERPNext's difference comes out at zero by itself.

	The amount is the user's (erp_cakra): typed, or set by the Pay / Receive button; only an
	empty one is worked out here. Receive: the party side (paid, party currency) is what the
	invoices are cleared by less the cuts; the bank (received) gets that. Pay: the bank (paid)
	pays the allocation plus the components; the party side (received) is the rest of it. More
	than the lines is left unallocated: ERPNext's own advance to the party.
	"""
	adj = sum(flt(d.amount) for d in doc.get("deductions") or [] if d.get("depot_auto"))
	if doc.get("depot_direct"):
		total = sum(flt(r.amount) for r in _direct_lines(doc))
		doc.paid_amount = doc.received_amount = total + adj if doc.payment_type == "Pay" else total - adj
		doc.depot_allocated = total
		return
	lines = [r for r in doc.get("depot_lines") or [] if r.get("document_no")]
	if not lines:
		return
	alloc = sum(flt(r.amount) for r in lines)
	doc.depot_allocated = alloc
	if not (flt(doc.source_exchange_rate) and flt(doc.target_exchange_rate)):
		doc.set_exchange_rate()  # a foreign invoice: the amounts below need its rate
	src = flt(doc.source_exchange_rate) or 1
	tgt = flt(doc.target_exchange_rate) or 1
	if doc.payment_type == "Receive":
		if not flt(doc.paid_amount):
			doc.paid_amount = alloc - adj / src
		doc.received_amount = doc.paid_amount * src / tgt
	else:
		if adj and doc.paid_to_account_currency != _company_currency(doc):
			frappe.throw(_("Potongan & biaya hanya bisa dipakai untuk hutang dalam {0}.").format(_company_currency(doc)))
		if not flt(doc.paid_amount):
			doc.paid_amount = (alloc * tgt + adj) / src
		doc.received_amount = (doc.paid_amount * src - adj) / tgt


def _apply_rounding(doc):
	"""A sub-rupiah tail between the bank and the invoices -> a "Pembulatan" deduction to the
	company's Round Off account: the bank moves whole rupiah, an invoice priced in decimals
	does not. Rebuilt on every save (flagged depot_auto, dropped by _apply_components)."""
	if doc.get("depot_direct") or not doc.get("references"):
		return
	alloc = sum(flt(r.allocated_amount) for r in doc.references)
	adj = sum(flt(d.amount) for d in doc.get("deductions") or [] if not d.get("is_exchange_gain_loss"))
	if doc.payment_type == "Pay":
		resid = flt(doc.paid_amount) - (alloc + adj)
	else:
		resid = (alloc - adj) - flt(doc.paid_amount)
	resid = flt(resid, 2)
	if not resid or abs(resid) > ROUNDING_LIMIT:
		return
	account, cost_center = frappe.get_cached_value("Company", doc.company, ["round_off_account", "round_off_cost_center"])
	if not account:
		frappe.throw(_("Selisih pembulatan {0}: isi <b>Round Off Account</b> di Company {1}.").format(resid, doc.company))
	doc.append("deductions", {
		"account": account, "cost_center": cost_center or doc.cost_center, "amount": resid,
		"description": ROUNDING, "depot_auto": 1,
	})
	if doc.payment_type == "Pay":
		doc.received_amount = flt(doc.received_amount) - resid


def _apply_remark(doc):
	"""Remark is the document's remarks (and the journal's); custom_remarks stops ERPNext
	writing its own "Amount X paid to ..." over it."""
	note = (doc.get("depot_remark_note") or "").strip()
	if note:
		doc.remarks = note
		doc.custom_remarks = 1


def _bank_amount(doc):
	"""What actually moves through the bank, in company currency: the amount less what a
	kasbon funds (the same arithmetic as DepotPaymentEntry.add_bank_gl_entries)."""
	if doc.payment_type == "Receive":
		base = flt(doc.received_amount) * (flt(doc.target_exchange_rate) or 1)
	else:
		base = flt(doc.paid_amount) * (flt(doc.source_exchange_rate) or 1)
	return flt(base - flt(doc.get("depot_kasbon_amount")), 2)


# --------------------------------------------------------------------------- #
# Advance Payable — an advance on Purchase Orders
# --------------------------------------------------------------------------- #
def _apply_advance(doc):
	"""Advance Payable rows -> native references to their Purchase Orders.

	ERPNext then books the payment as the advance it is (to the supplier's payable, or to the
	company's advance account when it books advances separately), keeps each order's Advance
	Paid, and lets the Purchase Invoice take it off later. A payment is an advance OR the
	settlement of invoices, never both (erp_cakra's rule): an advance has no invoice to
	balance against."""
	if doc.payment_type != "Pay" or doc.get("depot_direct"):
		doc.set("depot_advance", [])
		doc.depot_advance_amount = 0
		return
	rows = [r for r in doc.get("depot_advance") or [] if r.get("purchase_order")]
	doc.depot_advance_amount = 0
	if not rows:
		return
	if any(r.get("document_no") for r in doc.get("depot_lines") or []) or doc.get("depot_kasbon"):
		frappe.throw(_("Uang muka Purchase Order tidak bisa digabung dengan Payment Item / Pending Cash dalam satu Payment Entry. Buat Payment Entry terpisah."))
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_reference_details

	for r in rows:
		po = frappe.db.get_value(
			"Purchase Order", r.purchase_order, ["supplier", "transaction_date", "docstatus", "status"], as_dict=True
		)
		if not po or po.docstatus != 1 or po.status in ("Closed", "On Hold", "Completed"):
			frappe.throw(_("Purchase Order <b>{0}</b> belum submit atau sudah ditutup.").format(r.purchase_order))
		if doc.party and po.supplier != doc.party:
			frappe.throw(_("Purchase Order <b>{0}</b> milik supplier <b>{1}</b>, bukan <b>{2}</b>.").format(
				r.purchase_order, po.supplier, doc.party))
		ref = get_reference_details(
			"Purchase Order", r.purchase_order, doc.paid_to_account_currency or _company_currency(doc), doc.party_type, doc.party
		)
		left = flt(ref.outstanding_amount)
		if left <= 0.005:
			frappe.throw(_("Purchase Order <b>{0}</b> sudah diberi uang muka penuh.").format(r.purchase_order))
		r.supplier, r.date, r.grand_total, r.outstanding = po.supplier, po.transaction_date, flt(ref.total_amount), left
		r.allocated = flt(r.allocated) if flt(r.allocated) > 0 else left
		if r.allocated > left + 0.005:
			frappe.throw(_("Uang muka Purchase Order <b>{0}</b> ({1}) melebihi sisanya ({2}).").format(
				r.purchase_order, r.allocated, left))
		doc.append("references", {
			"reference_doctype": "Purchase Order",
			"reference_name": r.purchase_order,
			"total_amount": r.grand_total,
			"outstanding_amount": left,
			"allocated_amount": r.allocated,
			"depot_from_line": 1,
		})
	doc.depot_advance_amount = sum(flt(r.allocated) for r in rows)
	if not flt(doc.paid_amount):
		doc.paid_amount = doc.depot_advance_amount
	doc.received_amount = doc.paid_amount


@frappe.whitelist()
def get_purchase_orders(supplier, company, exclude=None):
	"""Submitted Purchase Orders of one supplier still open to an advance, for "Add Purchase
	Order": what is left is the order's total less its Advance Paid."""
	frappe.has_permission("Payment Entry", "create", throw=True)
	exclude = set(frappe.parse_json(exclude) or []) if exclude else set()
	out = []
	for po in frappe.get_list(
		"Purchase Order",
		filters={"supplier": supplier, "company": company, "docstatus": 1, "status": ["not in", ["Closed", "On Hold", "Completed"]]},
		fields=["name", "transaction_date", "grand_total", "rounded_total", "advance_paid", "currency"],
		order_by="transaction_date desc",
	):
		total = flt(po.rounded_total) or flt(po.grand_total)
		left = total - flt(po.advance_paid)
		if po.name not in exclude and left > 0.005:
			out.append({**po, "total": total, "outstanding": left})
	return out


# --------------------------------------------------------------------------- #
# Kasbon (Pending Cash) funding
# --------------------------------------------------------------------------- #
def _kasbon_used(names, exclude_parent=None) -> dict:
	"""{kasbon: amount already drawn by OTHER payments}. Drafts count — otherwise one kasbon
	could be drawn into two drafts and both submitted."""
	if not names:
		return {}
	filters = {"parenttype": "Payment Entry", "pending_cash": ["in", list(names)], "docstatus": ["<", 2]}
	if exclude_parent:
		filters["parent"] = ["!=", exclude_parent]
	used = {}
	for r in frappe.get_all("Payment Entry Kasbon", filters=filters, fields=["pending_cash", "allocated"], ignore_permissions=True):
		used[r.pending_cash] = used.get(r.pending_cash, 0.0) + flt(r.allocated)
	return used


def _direction(doc):
	"""The Pending Cash a payment can draw on: a Pay a kasbon (out), a Receive a deposit (in)."""
	return "Cash Inflow" if doc.payment_type == "Receive" else "Cash Outflow"


def _apply_kasbon(doc):
	"""Check each Pending Cash row against what is left of it (less other payments and its
	refunds). An empty row takes what is left, up to what this payment still needs."""
	if doc.payment_type not in ("Pay", "Receive"):
		doc.set("depot_kasbon", [])
		doc.depot_kasbon_amount = 0
		return
	rows = [r for r in doc.get("depot_kasbon") or [] if r.get("pending_cash")]
	if not rows:
		doc.depot_kasbon_amount = 0
		return
	info = {
		k.name: k for k in frappe.get_all(
			"Pending Cash", filters={"name": ["in", [r.pending_cash for r in rows]]},
			fields=["name", "total", "paid", "void", "pay_to", "receive_from", "direction", "refunded_amount", "dont_post_to_gl"],
			ignore_permissions=True,
		)
	}
	used = _kasbon_used(info, exclude_parent=doc.name)
	want = _direction(doc)
	need = flt(doc.paid_amount)
	for r in rows:
		k = info.get(r.pending_cash)
		if not k or not k.paid or k.void:
			frappe.throw(_("Pending Cash <b>{0}</b> belum dibayar atau sudah Void.").format(r.pending_cash))
		if k.dont_post_to_gl:
			# No journal, so no advance / deposit for this payment to close.
			frappe.throw(_("Pending Cash <b>{0}</b> tidak diposting ke GL — tidak bisa dipakai di Payment Entry.").format(k.name))
		if (k.direction or "Cash Outflow") != want:
			frappe.throw(_("Pending Cash <b>{0}</b> berarah <b>{1}</b>: tidak bisa dipakai di Payment Entry {2}.").format(
				k.name, k.direction or "Cash Outflow", doc.payment_type))
		if want == "Cash Inflow" and k.receive_from != doc.party:
			frappe.throw(_("Deposit <b>{0}</b> milik <b>{1}</b>, bukan <b>{2}</b>.").format(k.name, k.receive_from, doc.party))
		left = flt(k.total) - flt(used.get(k.name)) - flt(k.refunded_amount)
		if left <= 0.005:
			frappe.throw(_("Pending Cash <b>{0}</b> sudah habis dipakai atau di-refund.").format(k.name))
		r.pay_to, r.customer, r.grand_total, r.outstanding = k.pay_to, k.receive_from, flt(k.total), left
		r.allocated = flt(r.allocated) if flt(r.allocated) > 0 else (min(left, need) if need > 0 else left)
		if r.allocated > left + 0.005:
			frappe.throw(_("Pending Cash <b>{0}</b>: dipakai {1}, sisanya {2}.").format(k.name, r.allocated, left))
		need -= r.allocated
	doc.depot_kasbon_amount = sum(flt(r.allocated) for r in rows)


def _kasbon_funding(doc) -> list[dict]:
	"""The advance / deposit each Pending Cash row stands for, read off its OWN journal — the
	row that has to be closed is the one that was posted, with its party. A kasbon's advance
	is the debit row, a deposit the credit row."""
	if doc.payment_type not in ("Pay", "Receive"):
		return []
	posted = "credit" if doc.payment_type == "Receive" else "debit"
	out = []
	for r in doc.get("depot_kasbon") or []:
		if not (flt(r.allocated) and r.pending_cash):
			continue
		je = frappe.db.get_value("Pending Cash", r.pending_cash, "journal_entry")
		# The advance / deposit is the journal's first row; Admin Charge and Materai follow it
		# on the same (debit) side of a kasbon.
		side = je and frappe.db.get_value(
			"Journal Entry Account", {"parent": je, posted: [">", 0]}, ["account", "party_type", "party"], as_dict=True,
			order_by="idx asc",
		)
		if not side:
			frappe.throw(_("Kasbon <b>{0}</b> tidak punya jurnal pembayaran (belum Paid?).").format(r.pending_cash))
		out.append({"account": side.account, "party_type": side.party_type, "party": side.party, "amount": flt(r.allocated)})
	return out


# --------------------------------------------------------------------------- #
# "No. Pembayaran" on the invoices a payment touches — a list column, drafts included
# --------------------------------------------------------------------------- #
def sync_payment_links(doc, method=None):
	rows = list(doc.get("references") or [])
	before = doc.get_doc_before_save() if not doc.is_new() else None
	if before:
		rows += list(before.get("references") or [])
	# The Pending Cash it draws on: its Payment column and Completed.
	kasbon = {r.pending_cash for d in (doc, before) if d for r in d.get("depot_kasbon") or [] if r.get("pending_cash")}
	if kasbon:
		from container_depot.container_depot.doctype.pending_cash.pending_cash import sync_document_links

		sync_document_links(kasbon)
	targets = {
		(r.reference_doctype, r.reference_name)
		for r in rows
		if r.get("reference_doctype") in ("Sales Invoice", "Purchase Invoice") and r.get("reference_name")
	}
	try:
		for dt, name in targets:
			if not frappe.db.exists(dt, name):
				continue
			pes = sorted(set(frappe.get_all(
				"Payment Entry Reference",
				filters={"reference_doctype": dt, "reference_name": name, "parenttype": "Payment Entry", "docstatus": ["<", 2]},
				pluck="parent",
				ignore_permissions=True,
			)))
			values = {"payment_no": ", ".join(pes) or None}
			if dt == "Sales Invoice":
				values["depot_paid_date"] = paid_date(name)
			frappe.db.set_value(dt, name, values, update_modified=False)
	except Exception:
		# A list column, not bookkeeping: never let it fail a payment.
		frappe.log_error(frappe.get_traceback(), "Payment Entry: sync payment_no")


def paid_date(sales_invoice):
	"""Customer Paid: the date of the last submitted Payment Entry, once nothing is outstanding.

	Runs after ERPNext's own on_submit / on_cancel, so the outstanding read here is the new one."""
	si = frappe.db.get_value("Sales Invoice", sales_invoice, ["docstatus", "outstanding_amount"], as_dict=True)
	if not si or si.docstatus != 1 or flt(si.outstanding_amount) > 0:
		return None
	return frappe.db.sql(
		"""SELECT MAX(pe.posting_date) FROM `tabPayment Entry` pe
		JOIN `tabPayment Entry Reference` r ON r.parent = pe.name AND r.parenttype = 'Payment Entry'
		WHERE r.reference_doctype = 'Sales Invoice' AND r.reference_name = %s AND pe.docstatus = 1""",
		sales_invoice,
	)[0][0]


# --------------------------------------------------------------------------- #
# Pickers
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def get_payment_documents(party_type, party, company, payment_type, exclude=None):
	"""Outstanding invoices (and returns) of one party, straight from ERPNext's own
	``get_outstanding_reference_documents`` — the numbers the native dialog shows.

	Receive -> Sales Invoice + Credit Note; Pay -> Purchase Invoice + Debit Note. Only the
	branches the user works (Sales Invoice carries ``branch``)."""
	frappe.has_permission("Payment Entry", "create", throw=True)
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_outstanding_reference_documents
	from erpnext.accounts.party import get_party_account

	from container_depot.container_depot.user_branch import get_user_branches

	want = "Sales Invoice" if party_type == "Customer" else "Purchase Invoice"
	exclude = set(frappe.parse_json(exclude) or []) if exclude else set()
	accounts = [get_party_account(party_type, party, company)] + frappe.get_all(
		"Payment Ledger Entry",
		filters={"party_type": party_type, "party": party, "company": company, "delinked": 0},
		distinct=True, pluck="account",
	)
	docs, seen = [], set()
	for account in dict.fromkeys(a for a in accounts if a):
		for d in get_outstanding_reference_documents({
			"posting_date": nowdate(), "company": company, "party_type": party_type, "party": party,
			"party_account": account, "payment_type": payment_type, "get_outstanding_invoices": 1,
		}) or []:
			no = d.get("voucher_no")
			if d.get("voucher_type") != want or no in seen or no in exclude or not flt(d.get("outstanding_amount")):
				continue
			seen.add(no)
			docs.append(d)
	if not docs:
		return []
	fields = ["name", "is_return", "currency"] + (["branch"] if want == "Sales Invoice" else [])
	meta = {m.name: m for m in frappe.get_list(want, filters={"name": ["in", [d.voucher_no for d in docs]]}, fields=fields)}
	branches = get_user_branches()
	out = []
	for d in docs:
		m = meta.get(d.voucher_no)
		if not m or (branches and want == "Sales Invoice" and m.get("branch") and m.branch not in branches):
			continue  # not readable by this user, or another branch's invoice
		out.append({
			"document_type": want,
			"doc_label": ("Credit Note" if want == "Sales Invoice" else "Debit Note") if m.is_return else want,
			"document_no": d.voucher_no,
			"date": str(d.get("posting_date") or ""),
			"currency": m.currency,
			"grand_total": flt(d.get("invoice_amount")),
			"outstanding": flt(d.get("outstanding_amount")),
		})
	return out


@frappe.whitelist()
def default_bank():
	"""The Bank ticked Default Bank, where a new payment starts."""
	frappe.has_permission("Payment Entry", "create", throw=True)
	return frappe.db.get_value("Bank", {"depot_default_bank": 1}, "name")


@frappe.whitelist()
def get_kasbon(supplier=None, company=None, exclude=None, exclude_parent=None, payment_type="Pay", customer=None):
	"""Paid Pending Cash with something left, for "Add Pending Cash": a Pay draws on kasbon
	(Cash Outflow), a Receive on the customer's own deposits (Cash Inflow)."""
	frappe.has_permission("Payment Entry", "create", throw=True)
	filters = {"paid": 1, "void": 0, "dont_post_to_gl": 0, "direction": "Cash Inflow" if payment_type == "Receive" else "Cash Outflow"}
	if payment_type == "Receive":
		filters["receive_from"] = customer or "-"
	elif supplier:
		filters["pay_to"] = supplier
	if company:
		filters["company"] = company
	exclude = set(frappe.parse_json(exclude) or []) if exclude else set()
	rows = [
		r for r in frappe.get_list(
			"Pending Cash", filters=filters,
			fields=["name", "pay_to", "receive_from", "total", "refunded_amount", "paid_date"], order_by="paid_date desc",
		)
		if r.name not in exclude
	]
	used = _kasbon_used([r.name for r in rows], exclude_parent)
	out = []
	for r in rows:
		left = flt(r.total) - flt(used.get(r.name)) - flt(r.refunded_amount)
		if left > 0.005:
			out.append({**r, "outstanding": left})
	return out
