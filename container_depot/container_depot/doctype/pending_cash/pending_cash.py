"""Pending Cash — money that moves before the bill it will settle exists. erp_cakra's FICO
Pending Cash, form and flow (user, 2026-09-30: "pending cash belum ikut punya cakra"). Two
directions, set by its Pending Cash Type:

* **Cash Outflow** — a kasbon: money handed to a supplier (or an employee set up as one).
  Paid posts  Dr Uang Muka (party = the recipient) + Dr Admin Charge / Materai / Cr Bank.
* **Cash Inflow** — a customer's deposit (user, 2026-09-30: "di oak depo ada deposit customer").
  Paid (received) posts  Dr Bank (less the charges) + Dr the charges / Cr Deposit Customer.

A Payment Entry that later settles the party's bill can draw on it (``depot_kasbon``): a Pay
credits the advance instead of the bank, a Receive debits the deposit instead of the bank —
the cash already moved. What is left can be given back through a **Pending Cash Refund**, a
document of its own with its own journal (pending_cash_refund.py).

States, held as checkboxes so each carries its own who/when:

    Draft -> Validated -> Paid -> Completed (a submitted Payment Entry drew on it)
    Void (only before Paid), and each step has its way back

Deviations from erp_cakra, all deliberate:
* the actions are role-gated (Validate: Cashier / Finance; Pay, Unpaid, Void, Unvoid, Refund:
  Finance). In erp_cakra any account with ``write`` could pay out;
* the state rules (Paid needs Validated and a Bank Account) are enforced in ``validate``, not
  only in the buttons, so an API save cannot post a journal for a draft;
* Unpaid CANCELS the journal and keeps it — erp_cakra deleted it together with its GL rows,
  which rewrites posted history;
* IDR only (no currency / exchange rate), like the Payment Entry;
* "this type must name its document" is a tick on the Pending Cash Type (``need_connection``),
  not a list in a settings page.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model import no_value_fields
from frappe.model.document import Document
from frappe.model.naming import getseries
from frappe.utils import flt, getdate, now_datetime, today

# Connection: which document the Pending Cash is for, and the field naming its party.
CONNECTIONS = {
	"Container Booking": "customer",
	"Repair Order": "principal",
	"Cleaning Order": "container_principal",
	"Purchase Order": "supplier_name",
}
# The party a connected document must belong to: a kasbon's PO to the supplier it pays, a
# deposit's order to the customer who paid it. Repair Order's principal is free text.
CONNECTION_OWNER = {
	"Supplier": {"Purchase Order": "supplier"},
	"Customer": {"Container Booking": "customer", "Cleaning Order": "container_principal"},
}

# What may still change once a Pending Cash is Validated: its own state, what other documents
# write onto it, and — until it is paid from it — the Bank Account.
STATE_FIELDS = {
	"status", "validated", "validated_by", "validated_date", "paid", "paid_by", "paid_date",
	"paid_notes", "void", "void_by", "void_datetime", "journal_entry", "connection_party",
	"direction", "need_connection", "net_amount_paid", "refunded_amount", "refund_bank",
	"refund_date", "payment_no", "settled",
	# Who may see it, not what it books.
	"confidential",
}
INFLOW = "Cash Inflow"

VALIDATE_ROLES = ("Cashier", "Finance", "Accounts Manager", "System Manager")
PAY_ROLES = ("Finance", "Accounts Manager", "System Manager")
# Who sees a Confidential Pending Cash besides the one who made it.
CONFIDENTIAL_ROLES = PAY_ROLES

# ERPNext lets a party sit only on Receivable / Payable / Equity accounts, or untyped ones.
PARTY_ACCOUNT_TYPES = ("Receivable", "Payable", "Equity", "", None)


class PendingCash(Document):
	def autoname(self):
		"""PC-{type}-{company abbr}-{yy}-0001 — counting per type, company and year of ``date``."""
		code = frappe.db.get_value(
			"Pending Cash Type", self.pending_cash_type, ["numbering_code", "code"], as_dict=True
		) or {}
		type_code = (code.get("numbering_code") or code.get("code") or "GEN").strip()
		abbr = frappe.get_cached_value("Company", self._company(), "abbr") or "NA"
		prefix = f"PC-{type_code}-{abbr}-{getdate(self.date or today()).strftime('%y')}-"
		self.name = prefix + getseries(prefix, 4)

	def before_insert(self):
		if not self.branch:
			from container_depot.container_depot.user_branch import get_user_branches

			branches = get_user_branches() or []
			if len(branches) == 1:
				self.branch = branches[0]

	def validate(self):
		self.company = self._company()
		self.cost_center = self.cost_center or frappe.get_cached_value("Company", self.company, "cost_center")
		if flt(self.total) <= 0:
			frappe.throw(_("Amount Paid harus lebih dari 0."))
		self._guard_type_change()
		kind = frappe.db.get_value(
			"Pending Cash Type", self.pending_cash_type, ["direction", "need_connection"], as_dict=True
		) or {}
		self.direction = kind.get("direction") or "Cash Outflow"
		self.need_connection = kind.get("need_connection") or 0
		self._sync_party()
		# What the bank moves: a kasbon costs the charges on top, a deposit arrives less them.
		charges = flt(self.admin_fee) + flt(self.stamp_duty)
		self.net_amount_paid = flt(self.total) - charges if self.inflow() else flt(self.total) + charges
		if self.net_amount_paid <= 0:
			frappe.throw(_("Admin Charge + Materai tidak boleh melebihi Amount Paid."))
		self._validate_bank_account()
		self._sync_connection()
		if not self.is_new():
			# Rolled up from the refunds and payments, never typed — recomputed here too, so a
			# form saved after one of them was made cannot write back a stale figure.
			self.update(_refund_rollup(self.name))
			self.update(_payment_rollup(self.name))
		self._validate_state()
		self._sync_state()
		self._guard_locked_fields()

	def on_update(self):
		self._sync_journal()

	def on_trash(self):
		if self.journal_entry or self.paid:
			frappe.throw(_("Pending Cash yang sudah Paid tidak bisa dihapus — Unpaid dulu, lalu Void."))

	# ------------------------------------------------------------------ #
	def inflow(self) -> bool:
		return self.direction == INFLOW

	def party(self):
		"""(party_type, party) on the advance / deposit."""
		return ("Customer", self.receive_from) if self.inflow() else ("Supplier", self.pay_to)

	def _company(self):
		from container_depot.invoicing import get_default_company

		return self.company or get_default_company()

	def _guard_type_change(self):
		"""The type is in the number (PC-{type}-…), so it stays what it was saved as."""
		before = self.get_doc_before_save()
		if before and before.pending_cash_type != self.pending_cash_type:
			frappe.throw(_("<b>Type</b> tidak bisa diganti setelah disimpan — nomornya memuat kode type. Buat Pending Cash baru."))

	def _sync_party(self):
		"""Clear the side the direction does not use, so a party of the wrong kind never reaches
		the journal, and require the side it does."""
		if self.inflow():
			self.pay_to = None
			if not self.receive_from:
				frappe.throw(_("<b>Receive From</b> wajib diisi untuk Pending Cash <b>Cash Inflow</b>."))
		else:
			self.receive_from = None
			if not self.pay_to:
				frappe.throw(_("<b>Pay To</b> wajib diisi untuk Pending Cash <b>Cash Outflow</b>."))

	def _validate_bank_account(self):
		if not self.bank_account:
			return
		ba = frappe.db.get_value("Bank Account", self.bank_account, ["company", "is_company_account"], as_dict=True)
		if not ba or not ba.is_company_account or ba.company != self.company:
			frappe.throw(_("<b>Bank Account</b> harus rekening milik {0}.").format(self.company))

	def _sync_connection(self):
		if not self.modul:
			self.number = self.connection_party = None
		else:
			if self.modul not in CONNECTIONS:
				frappe.throw(_("Dokumen {0} tidak bisa dihubungkan ke Pending Cash.").format(self.modul))
			if self.number:
				self._assert_connection_party()
			self.connection_party = (
				frappe.db.get_value(self.modul, self.number, CONNECTIONS[self.modul]) if self.number else None
			)
		# The type's rule holds for drafts only: a validated one is locked and saved again by
		# every action, and a rule switched on later must not make it unpayable.
		before = self.get_doc_before_save()
		if self.need_connection and not (before and before.validated) and not (self.modul and self.number):
			frappe.throw(
				_("Pending Cash type <b>{0}</b> wajib ditautkan ke dokumen: isi <b>Modul</b> dan <b>Source No</b> di section Connection.").format(
					self.pending_cash_type
				)
			)

	def _assert_connection_party(self):
		"""The dropdown only offers the party's own documents; a typed number or an API save
		is checked here."""
		party_type, party = self.party()
		field = CONNECTION_OWNER[party_type].get(self.modul)
		if not (field and party):
			return
		owner = frappe.db.get_value(self.modul, self.number, field)
		if owner and owner != party:
			frappe.throw(
				_("{0} <b>{1}</b> milik <b>{2}</b>, bukan <b>{3}</b>.").format(self.modul, self.number, owner, party)
			)

	def _validate_state(self):
		"""The rules the buttons follow, enforced for every save — read-only fields are still
		writable over the API, and a Pending Cash marked paid posts a journal."""
		if self.paid and not self.validated:
			frappe.throw(_("Pending Cash harus Validated sebelum Paid."))
		if self.paid and not self.bank_account:
			frappe.throw(_("Isi <b>Bank Account</b> sebelum Pending Cash di-Pay."))
		if self.paid and self.paid_date and getdate(self.paid_date) < getdate(self.date):
			frappe.throw(
				_("<b>Paid Date</b> {0} mendahului tanggal Pending Cash {1}.").format(
					frappe.format(self.paid_date, "Date"), frappe.format(self.date, "Date")
				)
			)

	def _sync_state(self):
		user, stamp = frappe.session.user, now_datetime()
		if self.validated and not self.validated_by:
			self.validated_by, self.validated_date = user, stamp
		elif not self.validated:
			self.validated_by = self.validated_date = None
		if self.paid:
			self.paid_by = self.paid_by or user
			self.paid_date = self.paid_date or today()
		else:
			self.paid_by = self.paid_date = self.paid_notes = None
		if self.void and not self.void_by:
			self.void_by, self.void_datetime = user, stamp
		elif not self.void:
			self.void_by = self.void_datetime = None
		self.status = status_of(self)

	def _guard_locked_fields(self):
		"""After Validate the Pending Cash is what was approved; only its state moves."""
		before = self.get_doc_before_save()
		if not before or not before.validated:
			return
		allowed = set(STATE_FIELDS)
		if not before.paid:
			allowed.add("bank_account")
		changed = [
			df.label or df.fieldname
			for df in self.meta.fields
			if df.fieldtype not in no_value_fields
			and df.fieldname not in allowed
			and (self.get(df.fieldname) or None) != (before.get(df.fieldname) or None)
		]
		if changed:
			frappe.throw(
				_("Pending Cash ini sudah {0} — isinya tidak bisa diubah lagi.{1}<br>Field yang berubah: <b>{2}</b>").format(
					before.status,
					"" if before.paid else _(" Hanya <b>Bank Account</b> yang masih bisa direvisi."),
					", ".join(changed),
				)
			)

	# ------------------------------------------------------------------ #
	def _sync_journal(self):
		"""The journal exists exactly while the Pending Cash is Paid, not Void, and posted."""
		live = self.paid and not self.void and not self.dont_post_to_gl
		if live and not self.journal_entry:
			self.db_set("journal_entry", self._create_journal_entry(), update_modified=False)
		elif not live and self.journal_entry:
			je = self.journal_entry
			self.db_set("journal_entry", None, update_modified=False)
			cancel_journal(je)
			self.add_comment("Info", _("Journal Entry {0} dibatalkan ({1}).").format(je, self.status))

	def advance_account(self):
		company_default = "default_advance_received_account" if self.inflow() else "default_advance_paid_account"
		account = frappe.db.get_value("Pending Cash Type", self.pending_cash_type, "advance_account") or (
			frappe.get_cached_value("Company", self.company, company_default)
		)
		if not account:
			frappe.throw(
				_("Isi <b>Advance Account</b> di Pending Cash Type {0}, atau {1} di Company.").format(
					self.pending_cash_type,
					"Default Advance Received Account" if self.inflow() else "Default Advance Paid Account",
				)
			)
		return account

	def advance_party(self, account) -> dict:
		"""The party on the advance row, so its balance closes per person — where the account
		allows one. A Cash/Bank-typed advance account is posted without it."""
		if frappe.get_cached_value("Account", account, "account_type") not in PARTY_ACCOUNT_TYPES:
			return {}
		party_type, party = self.party()
		return {"party_type": party_type, "party": party}

	def _charge_lines(self):
		"""[(amount, account)] for Admin Charge and Materai: the bank's cost of this transfer,
		not part of the advance. Always a debit (expense). Refused when filled in without an
		account — silently skipping it would unbalance the journal."""
		out = []
		for field, account_field, label in (
			("admin_fee", "admin_fee_account", "Admin Charge"),
			("stamp_duty", "materai_expense_account", "Materai"),
		):
			value = flt(self.get(field))
			if value <= 0:
				continue
			account = charge_account(account_field)
			if not account:
				frappe.throw(
					_("<b>{0}</b> diisi, tapi akunnya belum diset di Depot Finance Settings > Potongan Payment Entry.").format(label)
				)
			out.append((value, account))
		return out

	def _create_journal_entry(self):
		"""Paid. Outflow: Dr Uang Muka + Dr charges / Cr Bank (all of it). Inflow: Dr Bank (what
		arrives) + Dr charges / Cr Deposit (the whole amount)."""
		account = self.advance_account()
		amount = flt(self.total)
		inflow = self.inflow()
		rows = [{
			"account": account,
			**self.advance_party(account),
			("credit" if inflow else "debit") + "_in_account_currency": amount,
			"cost_center": self.cost_center,
		}]
		charges = 0.0
		for value, charge_account in self._charge_lines():
			rows.append({"account": charge_account, "debit_in_account_currency": value, "cost_center": self.cost_center})
			charges += value
		rows.append({
			"account": bank_gl_account(self.bank_account),
			("debit" if inflow else "credit") + "_in_account_currency": amount - charges if inflow else amount + charges,
			"cost_center": self.cost_center,
		})
		return post_journal(
			self.company,
			self.paid_date or self.date,
			f"Pending Cash {self.name}" + (f" - {self.paid_notes}" if self.paid_notes else ""),
			f"{self.name} - {self.party()[1]}",
			rows,
		)

	def available(self, exclude_refund=None) -> float:
		"""What is left to draw on or refund: the total less what payments use (drafts too) and
		what live refunds (drafts too) take."""
		from container_depot.payment_entry import _kasbon_used

		used = _kasbon_used([self.name]).get(self.name, 0)
		return flt(flt(self.total) - flt(used) - refunded_total(self.name, exclude_refund), 2)


def charge_account(setting) -> str | None:
	"""Admin Charge / Materai expense account — the Payment Entry's own (Depot Finance Settings)."""
	return frappe.db.get_single_value("Depot Finance Settings", setting)


def status_of(d) -> str:
	return (
		"Void" if d.void
		else "Completed" if d.paid and d.settled
		else "Paid" if d.paid
		else "Validated" if d.validated
		else "Draft"
	)


def bank_gl_account(bank_account) -> str:
	account = frappe.db.get_value("Bank Account", bank_account, "account")
	if not account:
		frappe.throw(
			_("Bank Account <b>{0}</b> belum tertaut ke akun GL (field <b>Account</b> di Bank Account).").format(bank_account)
		)
	return account


def post_journal(company, posting_date, remark, title, rows) -> str:
	je = frappe.get_doc({
		"doctype": "Journal Entry",
		"voucher_type": "Journal Entry",
		# Born from a document, not typed by anyone — ERPNext's own flag for that.
		"is_system_generated": 1,
		"company": company,
		"posting_date": posting_date,
		"user_remark": remark,
		"accounts": rows,
	})
	je.flags.ignore_permissions = True
	je.insert()
	# After insert: JournalEntry.validate overwrites the title while the document is new.
	je.title = title
	je.submit()
	return je.name


def cancel_journal(name):
	if name and frappe.db.exists("Journal Entry", name):
		je = frappe.get_doc("Journal Entry", name)
		if je.docstatus == 1:
			je.flags.ignore_permissions = True
			je.cancel()


# ---------------------------------------------------------------------- #
# Confidential: only its maker and Finance see it. The query filters lists and reports,
# has_permission a document opened by URL, get_doc or print.
# ---------------------------------------------------------------------- #
def _may_see_confidential(user) -> bool:
	return bool(set(CONFIDENTIAL_ROLES) & set(frappe.get_roles(user)))


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if _may_see_confidential(user):
		return ""
	return f"(`tabPending Cash`.confidential = 0 or `tabPending Cash`.owner = {frappe.db.escape(user)})"


def has_permission(doc, ptype=None, user=None):
	if not doc.get("confidential"):
		return True
	user = user or frappe.session.user
	return doc.owner == user or _may_see_confidential(user)


# ---------------------------------------------------------------------- #
# What other documents write onto a Pending Cash
# ---------------------------------------------------------------------- #
def in_payment_entries(name, submitted_only=False) -> list[str]:
	"""Payment Entries that draw on this Pending Cash — drafts too, unless ``submitted_only``."""
	return sorted(set(frappe.get_all(
		"Payment Entry Kasbon",
		filters={"pending_cash": name, "parenttype": "Payment Entry", "docstatus": 1 if submitted_only else ["<", 2]},
		pluck="parent",
		ignore_permissions=True,
	)))


def _payment_rollup(name) -> dict:
	"""The Payment column, and Completed once a submitted payment has drawn on it."""
	return {
		"payment_no": ", ".join(in_payment_entries(name)) or None,
		"settled": 1 if in_payment_entries(name, submitted_only=True) else 0,
	}


def sync_document_links(names):
	"""Called from the Payment Entry side. Written straight to the row: a paid Pending Cash is
	locked, and these figures are nobody's input."""
	for name in {n for n in names or [] if n}:
		d = frappe.db.get_value("Pending Cash", name, ["paid", "void", "validated"], as_dict=True)
		if not d:
			continue
		values = _payment_rollup(name)
		d.settled = values["settled"]
		values["status"] = status_of(d)
		frappe.db.set_value("Pending Cash", name, values, update_modified=False)


def refund_rows(pending_cash, active_only=True):
	"""Refund allocations of one Pending Cash. Active = not Void (drafts claim their amount, as
	a draft payment does); the form's table shows the voided ones too, struck through."""
	return frappe.db.sql(
		"""SELECT a.parent, a.amount, r.refund_date, r.remark, r.void, r.validated, r.bank_account
		FROM `tabPending Cash Refund Allocation` a
		JOIN `tabPending Cash Refund` r ON r.name = a.parent
		WHERE a.parenttype = 'Pending Cash Refund' AND a.pending_cash = %s {0}
		ORDER BY r.refund_date, a.parent""".format("AND r.void = 0" if active_only else ""),
		pending_cash,
		as_dict=True,
	)


def refunded_total(pending_cash, exclude=None) -> float:
	return flt(sum(flt(r.amount) for r in refund_rows(pending_cash) if r.parent != exclude), 2)


def _refund_rollup(name) -> dict:
	"""Refund Total, and the bank and date of the latest live refund (list columns)."""
	rows = refund_rows(name)
	last = max(rows, key=lambda r: (getdate(r.refund_date), r.parent)) if rows else None
	return {
		"refunded_amount": flt(sum(flt(r.amount) for r in rows), 2),
		"refund_bank": last.bank_account if last else None,
		"refund_date": last.refund_date if last else None,
	}


def sync_refunded(name):
	if frappe.db.exists("Pending Cash", name):
		frappe.db.set_value("Pending Cash", name, _refund_rollup(name), update_modified=False)


@frappe.whitelist()
def get_refunds(pending_cash):
	"""The refund table on the form."""
	frappe.has_permission("Pending Cash", "read", doc=pending_cash, throw=True)
	return refund_rows(pending_cash, active_only=False)


@frappe.whitelist()
def get_available(pending_cash):
	"""What is left to refund — the form offers Refund only while there is some."""
	doc = frappe.get_doc("Pending Cash", pending_cash)
	doc.check_permission("read")
	return doc.available()


# ---------------------------------------------------------------------- #
# Actions (form buttons + list bulk). Three pairs, each the exact undo of the other —
# Validate/Invalidate, Pay/Unpaid, Void/Unvoid — and Refund, which may repeat.
# ---------------------------------------------------------------------- #
def _need(roles):
	if not set(roles) & set(frappe.get_roles()):
		frappe.throw(_("Aksi ini hanya untuk {0}.").format(" / ".join(roles[:2])), frappe.PermissionError)


def _assert_not_void(doc):
	if doc.void:
		frappe.throw(_("Pending Cash {0} sudah Void. Jalankan <b>Unvoid</b> dulu.").format(doc.name))


def _validate(doc, **_kw):
	_need(VALIDATE_ROLES)
	_assert_not_void(doc)
	if doc.validated:
		frappe.throw(_("Pending Cash {0} sudah Validated.").format(doc.name))
	doc.validated = 1


def _invalidate(doc, **_kw):
	_need(VALIDATE_ROLES)
	_assert_not_void(doc)
	if not doc.validated:
		frappe.throw(_("Pending Cash {0} masih Draft.").format(doc.name))
	if doc.paid:
		frappe.throw(_("Pending Cash {0} masih Paid — jalankan <b>Unpaid</b> dulu.").format(doc.name))
	doc.validated = 0


def _pay(doc, paid_date=None, paid_notes=None, bank_account=None, **_kw):
	"""Paid, and its journal. A draft is validated in the same step: paying it approves it."""
	_need(PAY_ROLES)
	_assert_not_void(doc)
	if doc.paid:
		frappe.throw(_("Pending Cash {0} sudah Paid.").format(doc.name))
	doc.validated = 1
	doc.bank_account = bank_account or doc.bank_account
	doc.paid, doc.paid_date, doc.paid_notes = 1, getdate(paid_date or today()), paid_notes or None


def _guard_not_used(doc):
	"""A payment credits the advance this journal debited: undoing it would leave that payment
	pointing at an advance that never existed."""
	used = in_payment_entries(doc.name)
	if used:
		frappe.throw(
			_("Pending Cash {0} sudah dipakai di Payment Entry <b>{1}</b>. Hapus dulu barisnya di sana.").format(
				doc.name, ", ".join(used)
			)
		)


def _guard_not_refunded(doc):
	"""A refund's journal returns money from this one's: void the refund first."""
	active = sorted({r.parent for r in refund_rows(doc.name)})
	if active:
		frappe.throw(
			_("Pending Cash {0} masih punya refund aktif (<b>{1}</b>). Void dulu refund-nya.").format(doc.name, ", ".join(active))
		)


def _unpaid(doc, **_kw):
	"""Undo a wrong Pay: the journal is cancelled, the document back to Validated."""
	_need(PAY_ROLES)
	_assert_not_void(doc)
	if not doc.paid:
		frappe.throw(_("Pending Cash {0} belum Paid.").format(doc.name))
	_guard_not_used(doc)
	_guard_not_refunded(doc)
	doc.paid = 0


def _void(doc, **_kw):
	"""Only for money that has not moved. A paid one goes back through Unpaid, or is refunded."""
	_need(PAY_ROLES)
	if doc.void:
		frappe.throw(_("Pending Cash {0} sudah Void.").format(doc.name))
	if doc.paid:
		frappe.throw(
			_("Pending Cash {0} sudah Paid — jalankan <b>Unpaid</b> dulu (atau <b>Refund</b> kalau uangnya memang sudah keluar).").format(doc.name)
		)
	doc.void = 1


def _unvoid(doc, **_kw):
	_need(PAY_ROLES)
	if not doc.void:
		frappe.throw(_("Pending Cash {0} tidak sedang Void.").format(doc.name))
	doc.void = 0


def _refund(doc, amount=None, refund_date=None, remark=None, **_kw):
	"""A draft Pending Cash Refund for what is left (or ``amount`` of it), pinned to this one.
	Its journal is posted when the refund itself is validated."""
	_need(PAY_ROLES)
	_assert_not_void(doc)
	if not doc.paid:
		frappe.throw(_("Pending Cash {0} belum Paid.").format(doc.name))
	if doc.dont_post_to_gl:
		frappe.throw(_("Pending Cash {0} tidak diposting ke GL — tidak ada jurnal yang bisa dikembalikan.").format(doc.name))
	left = doc.available()
	if left <= 0.005:
		frappe.throw(_("Pending Cash {0} tidak punya sisa yang bisa direfund.").format(doc.name))
	refund = frappe.new_doc("Pending Cash Refund")
	refund.party_type, refund.party = doc.party()
	refund.company = doc.company
	refund.bank_account = doc.bank_account
	refund.refund_date = getdate(refund_date or today())
	refund.remark = remark
	refund.append("allocations", {"pending_cash": doc.name, "amount": flt(amount) or left})
	refund.insert()
	return refund.name


ACTIONS = {
	"validate": _validate,
	"invalidate": _invalidate,
	"pay": _pay,
	"unpaid": _unpaid,
	"void": _void,
	"unvoid": _unvoid,
	"refund": _refund,
}
ACTION_ARGS = ("paid_date", "paid_notes", "bank_account", "amount", "refund_date", "remark")


@frappe.whitelist()
def run_action(names, action, **kwargs):
	"""Apply one action to one or many Pending Cash. Each succeeds or fails on its own.

	Returns ``{"done": [...], "failed": [{"name", "error"}], "created": [refunds]}``."""
	handler = ACTIONS.get(action)
	if not handler:
		frappe.throw(_("Aksi tidak dikenal: {0}").format(action))
	if isinstance(names, str):
		names = frappe.parse_json(names) if names.startswith("[") else [names]
	done, failed, created = [], [], []
	for name in names:
		frappe.db.savepoint("pending_cash_action")
		try:
			doc = frappe.get_doc("Pending Cash", name)
			doc.check_permission("write")
			out = handler(doc, **{k: kwargs.get(k) for k in ACTION_ARGS})
			if action == "refund":
				created.append(out)  # the refund is the new document; this one is not re-saved
			else:
				doc.save()
			done.append(name)
		except Exception as e:
			frappe.db.rollback(save_point="pending_cash_action")
			frappe.clear_last_message()
			failed.append({"name": name, "error": frappe.utils.strip_html(str(e))})
	return {"done": done, "failed": failed, "created": created}


@frappe.whitelist()
def connection_query(doctype, txt, searchfield, start, page_len, filters):
	"""Picker for ``number``: open documents of the chosen kind, the party's own where the
	document names one, searchable by number or party ("PO-0001 - PT ABC")."""
	filters = filters or {}
	modul = filters.get("modul")
	if modul not in CONNECTIONS:
		return []
	party_field = CONNECTIONS[modul]
	doc_filters = {"docstatus": ["<", 2]}
	if modul == "Purchase Order":
		# An advance is paid before the goods: a finished or closed order takes none.
		doc_filters["status"] = ["not in", ("Closed", "Completed")]
	party_type, party = ("Customer", filters.get("receive_from")) if filters.get("receive_from") else ("Supplier", filters.get("pay_to"))
	owner = CONNECTION_OWNER[party_type].get(modul)
	if owner and party:
		doc_filters[owner] = party
	return frappe.get_list(
		modul,
		filters=doc_filters,
		or_filters={"name": ["like", f"%{txt}%"], party_field: ["like", f"%{txt}%"]},
		fields=["name", party_field],
		start=start,
		page_length=page_len,
		order_by="modified desc",
		as_list=True,
	)


@frappe.whitelist()
def get_connection_party(modul, number):
	"""The connected document's customer / vendor, shown as soon as it is picked."""
	if modul not in CONNECTIONS or not number or not frappe.has_permission(modul, "read", doc=number):
		return None
	return frappe.db.get_value(modul, number, CONNECTIONS[modul])
