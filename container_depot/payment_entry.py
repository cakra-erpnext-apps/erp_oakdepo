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
* Cheque / reference number is not mandatory.

Deliberately NOT ported: erp_cakra's foreign-currency Expense Note path (this app has no
Expense Note), Validate/Void workflow, "Dont Post to GL" and the candidate cache (it was shared
across users and read with ignore_permissions — here every call is permission-checked and
branch-scoped instead).
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

	def add_bank_gl_entries(self, gl_entries):
		"""Pay funded by kasbon: the kasbon's advance account is credited instead of the bank.

		The kasbon already took the money out of the bank when it was paid (Dr Uang Muka / Cr
		Bank); charging the bank again would pay the same money twice. What the kasbon does not
		cover comes from the bank; what it over-covers goes back into it.
		"""
		funding = _kasbon_funding(self) if self.payment_type == "Pay" else []
		if not funding:
			return super().add_bank_gl_entries(gl_entries)
		for f in funding:
			gl_entries.append(self.get_gl_dict({
				"account": f["account"],
				"party_type": f["party_type"],
				"party": f["party"],
				"against": self.party or self.paid_to,
				"account_currency": frappe.get_cached_value("Account", f["account"], "account_currency"),
				"credit": f["amount"],
				"credit_in_account_currency": f["amount"],
				"cost_center": self.cost_center,
				"post_net_value": True,
			}, item=self))
		from_bank = flt(self.base_paid_amount) - sum(f["amount"] for f in funding)
		if abs(from_bank) > 0.005:
			side = "credit" if from_bank > 0 else "debit"
			gl_entries.append(self.get_gl_dict({
				"account": self.paid_from,
				"account_currency": self.paid_from_account_currency,
				"against": self.party or self.paid_to,
				side: abs(from_bank),
				f"{side}_in_account_currency": abs(from_bank) / (flt(self.source_exchange_rate) or 1),
				"cost_center": self.cost_center,
				"post_net_value": True,
			}, item=self))

	def _kasbon_against(self, gl_entries, start):
		"""The party rows' "against" names the accounts that actually paid them."""
		funding = _kasbon_funding(self) if self.payment_type == "Pay" else []
		if not funding:
			return
		accounts = list(dict.fromkeys(f["account"] for f in funding))
		if flt(self.base_paid_amount) - sum(f["amount"] for f in funding) > 0.005:
			accounts.append(self.paid_from)
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
	if not doc.branch:
		from container_depot.invoicing import default_branch

		default_branch(doc)
	_lines_from_references(doc)
	_derive_references(doc)
	_apply_components(doc)
	_apply_amounts(doc)
	_apply_kasbon(doc)
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
	"""Fill the bank side from the mode of payment, else the company's default bank / cash."""
	side = _bank_field(doc)
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
			frappe.throw(_("Akun Kas/Bank belum terisi. Pilih akunnya, atau isi akun default di Mode of Payment."))
		doc.set(side, acc)
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
	"""Paid / received from the lines, so ERPNext's difference comes out at zero by itself.

	Receive: the party side (paid, party currency) is what the invoices are cleared by less the
	cuts; the bank (received) gets that. Pay: the party side (received) is the allocation; the
	bank (paid) pays it plus the components.
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
		doc.paid_amount = alloc - adj / src
		doc.received_amount = doc.paid_amount * src / tgt
	else:
		if adj and doc.paid_to_account_currency != _company_currency(doc):
			frappe.throw(_("Potongan & biaya hanya bisa dipakai untuk hutang dalam {0}.").format(_company_currency(doc)))
		doc.received_amount = alloc
		doc.paid_amount = (alloc * tgt + adj) / src


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


def _apply_kasbon(doc):
	"""Check each kasbon row against what is left of it; default = all that is left."""
	if doc.payment_type != "Pay":
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
			fields=["name", "total", "paid", "void", "pay_to"], ignore_permissions=True,
		)
	}
	used = _kasbon_used(info, exclude_parent=doc.name)
	for r in rows:
		k = info.get(r.pending_cash)
		if not k or not k.paid or k.void:
			frappe.throw(_("Kasbon <b>{0}</b> belum dibayar atau sudah Void.").format(r.pending_cash))
		left = flt(k.total) - flt(used.get(k.name))
		if left <= 0.005:
			frappe.throw(_("Kasbon <b>{0}</b> sudah habis dipakai di Payment Entry lain.").format(k.name))
		r.pay_to, r.grand_total, r.outstanding = k.pay_to, flt(k.total), left
		r.allocated = flt(r.allocated) if flt(r.allocated) > 0 else left
		if r.allocated > left + 0.005:
			frappe.throw(_("Kasbon <b>{0}</b>: dipakai {1}, sisanya {2}.").format(k.name, r.allocated, left))
	doc.depot_kasbon_amount = sum(flt(r.allocated) for r in rows)


def _kasbon_funding(doc) -> list[dict]:
	"""The advance credit each kasbon row stands for, read off the kasbon's OWN journal — the
	row that has to be closed is the one that was posted, with its recipient as party."""
	out = []
	for r in doc.get("depot_kasbon") or []:
		if not (flt(r.allocated) and r.pending_cash):
			continue
		je = frappe.db.get_value("Pending Cash", r.pending_cash, "journal_entry")
		side = je and frappe.db.get_value(
			"Journal Entry Account", {"parent": je, "debit": [">", 0]}, ["account", "party_type", "party"], as_dict=True
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
def get_kasbon(supplier=None, company=None, exclude=None, exclude_parent=None):
	"""Paid kasbon with something left to draw on, for the "Ambil Kasbon" dialog."""
	frappe.has_permission("Payment Entry", "create", throw=True)
	filters = {"paid": 1, "void": 0}
	if supplier:
		filters["pay_to"] = supplier
	if company:
		filters["company"] = company
	exclude = set(frappe.parse_json(exclude) or []) if exclude else set()
	rows = [
		r for r in frappe.get_list(
			"Pending Cash", filters=filters, fields=["name", "pay_to", "total", "paid_date"], order_by="paid_date desc"
		)
		if r.name not in exclude
	]
	used = _kasbon_used([r.name for r in rows], exclude_parent)
	out = []
	for r in rows:
		left = flt(r.total) - flt(used.get(r.name))
		if left > 0.005:
			out.append({**r, "outstanding": left})
	return out
