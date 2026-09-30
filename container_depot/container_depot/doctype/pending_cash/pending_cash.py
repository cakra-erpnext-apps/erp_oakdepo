"""Pending Cash — a kasbon: money handed to a supplier (or an employee set up as one) before
the bill it will settle exists. Ported from erp_cakra's FICO module.

Four states, held as checkboxes so each carries its own who/when:

    Draft -> Validated -> Paid        (Void from anywhere, and back)

**Paid** posts the money out:  Dr Uang Muka (party = the recipient) / Cr Kas-Bank. A Payment
Entry that later pays the recipient's bill can draw on it (``depot_kasbon`` table): the credit
then lands on the advance account instead of the bank, because the cash already left.

Deviations from erp_cakra, all deliberate:
* the actions are role-gated here (Validate: Cashier / Finance; Pay, Unpaid, Void, Unvoid:
  Finance). In erp_cakra any account with ``write`` could pay out;
* the state rules (Paid needs Validated and a Kas/Bank account) are enforced in ``validate``,
  not only in the buttons, so an API save cannot post a journal for a draft;
* Unpaid CANCELS the journal and keeps it, like Void — erp_cakra deleted it together with its
  GL rows, which rewrites posted history;
* IDR only (no currency / exchange rate), and ``bank_account`` is the Kas/Bank GL account
  itself — this site has no Bank Account records.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import getseries
from frappe.utils import flt, getdate, now_datetime, today

# Connection: which document the kasbon is for, and where that document names its party.
CONNECTIONS = {
	"Container Booking": "customer",
	"Repair Order": "principal",
	"Cleaning Order": "container_principal",
	"Purchase Order": "supplier_name",
}

# What may still change once a kasbon is Validated: its own state, and the Kas/Bank account
# until it is paid from it.
STATE_FIELDS = (
	"status", "validated", "validated_by", "validated_date", "paid", "paid_by", "paid_date",
	"paid_notes", "void", "void_by", "void_datetime", "journal_entry", "connection_party",
)

VALIDATE_ROLES = ("Cashier", "Finance", "Accounts Manager", "System Manager")
PAY_ROLES = ("Finance", "Accounts Manager", "System Manager")


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
			frappe.throw(_("Nominal kasbon harus lebih dari 0."))
		self._validate_bank_account()
		self._sync_connection()
		self._validate_state()
		self._sync_state()
		self._guard_locked_fields()

	def on_update(self):
		self._sync_journal()

	def on_trash(self):
		if self.journal_entry or self.paid:
			frappe.throw(_("Kasbon yang sudah dibayar tidak bisa dihapus — pakai Void."))

	# ------------------------------------------------------------------ #
	def _company(self):
		from container_depot.invoicing import get_default_company

		return self.company or get_default_company()

	def _validate_bank_account(self):
		if not self.bank_account:
			return
		acc = frappe.db.get_value(
			"Account", self.bank_account, ["account_type", "is_group", "company"], as_dict=True
		)
		if not acc or acc.is_group or acc.account_type not in ("Bank", "Cash") or acc.company != self.company:
			frappe.throw(_("<b>Dibayar dari</b> harus akun Kas/Bank milik {0}.").format(self.company))

	def _sync_connection(self):
		if not self.modul:
			self.number = None
			self.connection_party = None
			return
		if self.modul not in CONNECTIONS:
			frappe.throw(_("Dokumen {0} tidak bisa dihubungkan ke kasbon.").format(self.modul))
		self.connection_party = (
			frappe.db.get_value(self.modul, self.number, CONNECTIONS[self.modul]) if self.number else None
		)

	def _validate_state(self):
		"""The rules the buttons follow, enforced for every save — read-only fields are still
		writable over the API, and a kasbon marked paid posts a journal."""
		if self.paid and not self.validated:
			frappe.throw(_("Kasbon harus Validated sebelum dibayar."))
		if self.paid and not self.bank_account:
			frappe.throw(_("Isi <b>Dibayar dari (Kas/Bank)</b> sebelum kasbon dibayar."))

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
		self.status = (
			"Void" if self.void else "Paid" if self.paid else "Validated" if self.validated else "Draft"
		)

	def _guard_locked_fields(self):
		"""After Validate the kasbon is what was approved; only its state moves."""
		before = self.get_doc_before_save()
		if not before or not before.validated:
			return
		allowed = set(STATE_FIELDS)
		if not before.paid:
			allowed.add("bank_account")
		changed = [
			df.label or df.fieldname
			for df in self.meta.fields
			if df.fieldtype not in ("Section Break", "Column Break", "Tab Break")
			and df.fieldname not in allowed
			and (self.get(df.fieldname) or None) != (before.get(df.fieldname) or None)
		]
		if changed:
			frappe.throw(
				_("Kasbon ini sudah {0} — isinya tidak bisa diubah lagi. Field yang berubah: {1}").format(
					before.status, ", ".join(changed)
				)
			)

	# ------------------------------------------------------------------ #
	def _sync_journal(self):
		"""Post the journal when the kasbon is paid; cancel it when it no longer is."""
		live = self.paid and not self.void
		if live and not self.journal_entry:
			self.db_set("journal_entry", self._create_journal_entry(), update_modified=False)
		elif not live and self.journal_entry:
			je = frappe.get_doc("Journal Entry", self.journal_entry)
			if je.docstatus == 1:
				je.flags.ignore_permissions = True
				je.cancel()
			self.add_comment("Info", _("Journal Entry {0} dibatalkan ({1}).").format(je.name, self.status))
			self.db_set("journal_entry", None, update_modified=False)

	def advance_account(self):
		account = frappe.db.get_value("Pending Cash Type", self.pending_cash_type, "advance_account") or (
			frappe.get_cached_value("Company", self.company, "default_advance_paid_account")
		)
		if not account:
			frappe.throw(
				_("Isi <b>Akun Uang Muka</b> di Pending Cash Type {0}, atau Default Advance Paid Account di Company.").format(
					self.pending_cash_type
				)
			)
		return account

	def _create_journal_entry(self):
		account = self.advance_account()
		debit = {"account": account, "debit_in_account_currency": flt(self.total), "cost_center": self.cost_center}
		# The recipient is the party on the advance, so its balance can be closed per person.
		if frappe.get_cached_value("Account", account, "account_type") in ("Receivable", "Payable", "Equity", "", None):
			debit.update(party_type="Supplier", party=self.pay_to)
		je = frappe.get_doc({
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": self.company,
			"posting_date": self.paid_date or self.date,
			"user_remark": f"Pending Cash {self.name}" + (f" - {self.paid_notes}" if self.paid_notes else ""),
			"title": f"{self.name} - {self.pay_to}",
			"accounts": [
				debit,
				{"account": self.bank_account, "credit_in_account_currency": flt(self.total), "cost_center": self.cost_center},
			],
		})
		je.flags.ignore_permissions = True
		je.insert()
		je.submit()
		return je.name


def in_payment_entries(name) -> list[str]:
	"""Payment Entries (draft or submitted) that draw on this kasbon."""
	return sorted(set(frappe.get_all(
		"Payment Entry Kasbon",
		filters={"pending_cash": name, "parenttype": "Payment Entry", "docstatus": ["<", 2]},
		pluck="parent",
		ignore_permissions=True,
	)))


# ---------------------------------------------------------------------- #
# Actions (form buttons + list bulk)
# ---------------------------------------------------------------------- #
def _need(roles):
	if not set(roles) & set(frappe.get_roles()):
		frappe.throw(_("Aksi ini hanya untuk {0}.").format(" / ".join(roles[:2])), frappe.PermissionError)


def _validate(doc, **_kw):
	_need(VALIDATE_ROLES)
	if doc.void or doc.validated:
		frappe.throw(_("Hanya kasbon Draft yang bisa di-Validate."))
	doc.validated = 1


def _invalidate(doc, **_kw):
	_need(VALIDATE_ROLES)
	if doc.void or not doc.validated or doc.paid:
		frappe.throw(_("Hanya kasbon Validated yang belum dibayar yang bisa di-Invalidate."))
	doc.validated = 0


def _pay(doc, paid_date=None, paid_notes=None, **_kw):
	_need(PAY_ROLES)
	if doc.void or not doc.validated or doc.paid:
		frappe.throw(_("Hanya kasbon Validated yang bisa dibayar."))
	doc.paid, doc.paid_date, doc.paid_notes = 1, paid_date or today(), paid_notes


def _guard_not_used(doc):
	used = in_payment_entries(doc.name)
	if used:
		frappe.throw(_("Kasbon ini dipakai di Payment Entry {0} — batalkan/hapus itu dulu.").format(", ".join(used)))


def _unpaid(doc, **_kw):
	_need(PAY_ROLES)
	if doc.void or not doc.paid:
		frappe.throw(_("Kasbon ini belum dibayar."))
	_guard_not_used(doc)
	doc.paid = 0


def _void(doc, **_kw):
	_need(PAY_ROLES)
	if doc.void:
		frappe.throw(_("Kasbon ini sudah Void."))
	if doc.paid:
		_guard_not_used(doc)
	doc.void = 1


def _unvoid(doc, **_kw):
	_need(PAY_ROLES)
	if not doc.void:
		frappe.throw(_("Kasbon ini tidak Void."))
	doc.void = 0


ACTIONS = {
	"validate": _validate,
	"invalidate": _invalidate,
	"pay": _pay,
	"unpaid": _unpaid,
	"void": _void,
	"unvoid": _unvoid,
}


@frappe.whitelist()
def run_action(names, action, paid_date=None, paid_notes=None):
	"""Apply one action to one or many kasbon. Each document succeeds or fails on its own.

	Returns ``{"done": [...], "failed": [{"name", "error"}]}``."""
	handler = ACTIONS.get(action)
	if not handler:
		frappe.throw(_("Aksi tidak dikenal: {0}").format(action))
	if isinstance(names, str):
		names = frappe.parse_json(names) if names.startswith("[") else [names]
	done, failed = [], []
	for name in names:
		frappe.db.savepoint("pending_cash_action")
		try:
			doc = frappe.get_doc("Pending Cash", name)
			doc.check_permission("write")
			handler(doc, paid_date=paid_date, paid_notes=paid_notes)
			doc.save()
			done.append(name)
		except Exception as e:
			frappe.db.rollback(save_point="pending_cash_action")
			frappe.clear_last_message()
			failed.append({"name": name, "error": frappe.utils.strip_html(str(e))})
	return {"done": done, "failed": failed}


@frappe.whitelist()
def connection_query(doctype, txt, searchfield, start, page_len, filters):
	"""Picker for ``number``: open documents of the chosen kind, searchable by party too."""
	modul = (filters or {}).get("modul")
	if modul not in CONNECTIONS:
		return []
	party = CONNECTIONS[modul]
	return frappe.get_list(
		modul,
		filters={"docstatus": ["<", 2]},
		or_filters={"name": ["like", f"%{txt}%"], party: ["like", f"%{txt}%"]},
		fields=["name", party],
		start=start,
		page_length=page_len,
		order_by="modified desc",
		as_list=True,
	)
