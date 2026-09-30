"""Pending Cash Refund — money of a paid Pending Cash going back, a numbered document of its
own (erp_cakra). Keyed by PARTY, not by one Pending Cash: a supplier often returns what is
left of several kasbon in one transfer, so the user picks them in ``allocations``, one row
each, and Refund Amount is the sum of the rows, never typed.

  Supplier — kasbon (Cash Outflow) money coming back:  Dr Bank / Cr Uang Muka.
  Customer — deposit (Cash Inflow) we give back:       Dr Deposit / Cr Bank.

A NEW journal dated the refund day, the Paid journal left alone — so a refund in a later
month is safe even when the month it was paid is closed. Saving posts nothing; Validate does:

    Draft -> Validated (journal) -> Void (journal cancelled, kept as the trace)

Unlike erp_cakra, Invalidate cancels the journal and keeps it rather than deleting it, and
there is no currency / rate (IDR only, like Pending Cash).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import getseries
from frappe.utils import flt, formatdate, getdate, now_datetime, today

from container_depot.container_depot.doctype.pending_cash.pending_cash import (
	PAY_ROLES,
	_need,
	bank_gl_account,
	cancel_journal,
	post_journal,
	sync_refunded,
)

# Party Type -> the Pending Cash field holding it, which also fixes the direction.
PARTY_FIELD = {"Supplier": "pay_to", "Customer": "receive_from"}
# Locked once its journal is posted.
LOCKED = ("party_type", "party", "bank_account", "refund_date", "amount")


class PendingCashRefund(Document):
	def autoname(self):
		"""RF-{company abbr}-{yy}-0001, the year of the refund date."""
		abbr = frappe.get_cached_value("Company", self._company(), "abbr") or "NA"
		prefix = f"RF-{abbr}-{getdate(self.refund_date or today()).strftime('%y')}-"
		self.name = prefix + getseries(prefix, 4)

	def _company(self):
		from container_depot.invoicing import get_default_company

		return self.company or get_default_company()

	def validate(self):
		self.company = self._company()
		self.refund_date = self.refund_date or today()
		self._validate_bank_account()
		self._guard_locked_fields()
		self._sync_state()
		if not self.void:
			self._check_allocations()
		self.pending_cash_no = ", ".join(sorted({r.pending_cash for r in self.allocations if r.pending_cash})) or None

	def before_save(self):
		# Pending Cash whose rollup must be recomputed — including one just taken off the table.
		before = self.get_doc_before_save()
		self._touched = {r.pending_cash for r in self.allocations}
		if before:
			self._touched |= {r.pending_cash for r in before.allocations}

	def on_update(self):
		self._sync_journal()
		self._sync_parents()

	def on_trash(self):
		if self.journal_entry:
			frappe.throw(_("Refund yang sudah punya jurnal tidak bisa dihapus — Invalidate dulu, atau biarkan Void."))
		self._touched = {r.pending_cash for r in self.allocations}

	def after_delete(self):
		self._sync_parents()

	# ------------------------------------------------------------------ #
	def _validate_bank_account(self):
		ba = frappe.db.get_value("Bank Account", self.bank_account, ["company", "is_company_account"], as_dict=True)
		if not ba or not ba.is_company_account or ba.company != self.company:
			frappe.throw(_("<b>Refund To Bank</b> harus rekening milik {0}.").format(self.company))

	def _guard_locked_fields(self):
		"""Once the journal is posted the refund is what it booked. A wrong one: Invalidate (or
		Void) and make it again."""
		before = self.get_doc_before_save()
		if not before or not before.validated:
			return
		changed = [self.meta.get_label(f) for f in LOCKED if self.get(f) != before.get(f)]
		rows = lambda d: sorted((r.pending_cash, flt(r.amount)) for r in d.allocations)  # noqa: E731
		if rows(self) != rows(before):
			changed.append("Pending Cash")
		if changed:
			frappe.throw(
				_("Refund <b>{0}</b> sudah Validated, isinya tidak bisa diubah (<b>{1}</b>). <b>Invalidate</b> dulu.").format(
					self.name, ", ".join(changed)
				)
			)

	def _sync_state(self):
		user, stamp = frappe.session.user, now_datetime()
		if self.validated and not self.validated_by:
			self.validated_by, self.validated_date = user, stamp
		elif not self.validated:
			self.validated_by = self.validated_date = None
		if self.void and not self.void_by:
			self.void_by, self.void_datetime = user, stamp
		elif not self.void:
			self.void_by = self.void_datetime = None

	def open_pending_cash(self) -> dict:
		"""{name: row} of the party's paid, posted, non-void Pending Cash with something left,
		oldest first. The dropdown and the save check both read this one list."""
		if not (self.party_type in PARTY_FIELD and self.party):
			return {}
		rows = frappe.get_all(
			"Pending Cash",
			filters={
				PARTY_FIELD[self.party_type]: self.party,
				"company": self.company,
				"paid": 1,
				"void": 0,
				# No journal, so no advance to take back.
				"dont_post_to_gl": 0,
			},
			fields=["name", "total", "paid_date", "date"],
			order_by="paid_date asc, date asc, name asc",
			ignore_permissions=True,
		)
		out = {}
		for r in rows:
			# This refund's own rows are left out: its old figures must not shrink what is
			# being recomputed.
			r.available = frappe.get_doc("Pending Cash", r.name).available(exclude_refund=self.name)
			if r.available > 0.005:
				out[r.name] = r
		return out

	def _check_allocations(self):
		"""Each row against what is left of its Pending Cash — the server never trusts rows
		from the form. Refund Amount follows the rows."""
		if not self.allocations:
			frappe.throw(_("Pilih dulu Pending Cash-nya di tabel <b>Refund Pending Cash Item</b>."))
		available = self.open_pending_cash()
		total, seen = 0.0, set()
		for row in self.allocations:
			pc = available.get(row.pending_cash)
			if not pc:
				frappe.throw(
					_("Pending Cash <b>{0}</b> tidak punya sisa yang bisa direfund untuk {1} <b>{2}</b>.").format(
						row.pending_cash, self.party_type, self.party
					)
				)
			if row.pending_cash in seen:
				frappe.throw(_("Pending Cash <b>{0}</b> dipilih lebih dari sekali.").format(row.pending_cash))
			seen.add(row.pending_cash)
			if flt(row.amount) <= 0:
				frappe.throw(_("Nominal refund untuk {0} harus lebih dari 0.").format(row.pending_cash))
			if flt(row.amount) > pc.available + 0.005:
				frappe.throw(
					_("Refund {0} melebihi sisa Pending Cash {1} ({2}).").format(
						frappe.format(row.amount, "Currency"), row.pending_cash, frappe.format(pc.available, "Currency")
					)
				)
			row.paid_date, row.outstanding = pc.paid_date, pc.available
			total += flt(row.amount)
		self.amount = flt(total, 2)
		# Returning money before it left would put the advance below zero in between.
		last = max((getdate(r.paid_date) for r in self.allocations if r.paid_date), default=None)
		if last and getdate(self.refund_date) < last:
			frappe.throw(
				_("Refund Date <b>{0}</b> lebih awal dari Paid Date terakhir di tabel (<b>{1}</b>).").format(
					formatdate(self.refund_date), formatdate(last)
				)
			)

	# ------------------------------------------------------------------ #
	def _sync_journal(self):
		"""The journal exists exactly while the refund is Validated and not Void."""
		live = self.validated and not self.void
		if live and not self.journal_entry:
			self.db_set("journal_entry", self._create_journal_entry(), update_modified=False)
		elif not live and self.journal_entry and frappe.db.get_value("Journal Entry", self.journal_entry, "docstatus") == 1:
			cancel_journal(self.journal_entry)
			self.add_comment("Info", _("Journal Entry {0} dibatalkan.").format(self.journal_entry))
			# Void keeps the cancelled journal as its trace; Invalidate lets go of it, so the
			# next Validate posts a new one.
			if not self.void:
				self.db_set("journal_entry", None, update_modified=False)

	def _create_journal_entry(self):
		"""ONE journal: an advance row per Pending Cash, on its own account, party and cost
		center, and one bank row for the total — it is one transfer, and bank reconciliation
		looks for one figure."""
		money_in = self.party_type == "Supplier"
		side = "credit" if money_in else "debit"
		rows, cost_center = [], None
		for row in self.allocations:
			pc = frappe.get_doc("Pending Cash", row.pending_cash)
			account = pc.advance_account()
			cost_center = cost_center or pc.cost_center
			rows.append({
				"account": account,
				**pc.advance_party(account),
				f"{side}_in_account_currency": flt(row.amount),
				"cost_center": pc.cost_center,
				"user_remark": row.pending_cash,
			})
		rows.append({
			"account": bank_gl_account(self.bank_account),
			("debit" if money_in else "credit") + "_in_account_currency": flt(self.amount),
			"cost_center": cost_center,
		})
		return post_journal(
			self.company,
			self.refund_date,
			f"Refund Pending Cash {self.name}" + (f" - {self.remark}" if self.remark else ""),
			f"{self.name} - {self.party}",
			rows,
		)

	def _sync_parents(self):
		for name in getattr(self, "_touched", None) or {r.pending_cash for r in self.allocations}:
			sync_refunded(name)


# ---------------------------------------------------------------------- #
@frappe.whitelist()
def open_pending_cash_query(doctype, txt, searchfield, start, page_len, filters):
	"""Dropdown of the allocation table: the party's Pending Cash that can still be refunded
	and is not on another row — the same list validate checks against."""
	filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
	doc = frappe.new_doc("Pending Cash Refund")
	doc.party_type, doc.party = filters.get("party_type"), filters.get("party")
	doc.company = filters.get("company") or doc._company()
	doc.name = filters.get("exclude") or None
	taken = set(filters.get("chosen") or [])
	txt = (txt or "").lower()
	rows = [r for r in doc.open_pending_cash().values() if r.name not in taken and txt in r.name.lower()]
	return [
		[r.name, frappe.format(r.available, "Currency"), frappe.format(r.paid_date, "Date")]
		for r in rows[int(start): int(start) + int(page_len)]
	]


@frappe.whitelist()
def row_info(pending_cash, exclude=None):
	"""Paid date and what is left of one Pending Cash, to fill a row as soon as it is picked."""
	doc = frappe.get_doc("Pending Cash", pending_cash)
	doc.check_permission("read")
	return {"paid_date": doc.paid_date, "available": doc.available(exclude_refund=exclude)}


def _run(names, handler):
	"""The Pending Cash bulk runner, for refunds."""
	names = frappe.parse_json(names) if isinstance(names, str) and names.startswith("[") else names
	names = [names] if isinstance(names, str) else names
	done, failed = [], []
	for name in names or []:
		frappe.db.savepoint("pending_cash_refund_action")
		try:
			doc = frappe.get_doc("Pending Cash Refund", name)
			doc.check_permission("write")
			_need(PAY_ROLES)
			handler(doc)
			doc.save()
			done.append(name)
		except Exception as e:
			frappe.db.rollback(save_point="pending_cash_refund_action")
			frappe.clear_last_message()
			failed.append({"name": name, "error": frappe.utils.strip_html(str(e))})
	return {"done": done, "failed": failed}


@frappe.whitelist()
def bulk_validate(names):
	"""Post the journal. The refund is locked after this; Invalidate reopens it."""

	def handler(doc):
		if doc.void:
			frappe.throw(_("Refund {0} sudah Void.").format(doc.name))
		if doc.validated:
			frappe.throw(_("Refund {0} sudah Validated.").format(doc.name))
		doc.validated = 1

	return _run(names, handler)


@frappe.whitelist()
def bulk_invalidate(names):
	"""A wrong Validate: the journal is cancelled, the refund back to Draft."""

	def handler(doc):
		if doc.void:
			frappe.throw(_("Refund {0} sudah Void.").format(doc.name))
		if not doc.validated:
			frappe.throw(_("Refund {0} belum Validated.").format(doc.name))
		doc.validated = 0

	return _run(names, handler)


@frappe.whitelist()
def bulk_void(names):
	"""Cancel a refund for good: its journal is cancelled, its number stays used."""

	def handler(doc):
		if doc.void:
			frappe.throw(_("Refund {0} sudah Void.").format(doc.name))
		doc.void = 1

	return _run(names, handler)
