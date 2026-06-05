"""Isotank Booking — the booking spine for PRO-OPS-08 Tank In / Tank Out.

Carries the three Phase-3 critical controllers:

1. TOP credit-block (``before_submit``): TOP customers blocked when outstanding
   exceeds credit limit or any overdue Sales Invoice exists. Cash bookings
   require a *paid* linked Sales Invoice before submit.
2. TANK OUT gating (``validate`` when direction == 'Tank Out'): every item must
   reference a Container that is clean + ready, with a Cleaning Certificate
   whose ``valid_until`` covers today.
3. 72h Booking Code issuance on submit; expiry runs hourly via
   ``container_depot.tasks.expire_booking_codes`` (see hooks.py).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import add_to_date, getdate, now_datetime, today

from container_depot import invoicing, pricing
from container_depot.operations.doctype.booking_code.booking_code import (
	CODE_TTL_HOURS,
	generate_code,
)
from container_depot.operations.doctype.depot_contract.depot_contract import (
	get_active_contract,
)


CONTAINER_READY_STATUSES = {"Available", "Ready_For_Service", "Ready_For_Release", "Ready"}


class IsotankBooking(Document):
	# ---- naming ---------------------------------------------------------
	def autoname(self):
		prefix = "BKG-IN-" if self.direction == "Tank In" else "BKG-OUT-"
		self.name = make_autoname(prefix + ".YYYY.-.#####")

	# ---- lifecycle ------------------------------------------------------
	def validate(self):
		self._ensure_depot()
		self._sync_lift_type()
		self._resolve_containers()
		self._sync_payment_type_from_contract()
		if self.direction == "Tank Out":
			self._validate_tank_out_gating()

	def before_save(self):
		self._ensure_cash_invoice()
		self._sync_payment_status_from_invoice()

	def before_submit(self):
		self._enforce_payment_rules()
		self._validate_do()

	def on_submit(self):
		self._issue_booking_codes()
		self.db_set("booking_status", "Confirmed", update_modified=False)
		# Cash bookings clear their (Paid) invoice at submit; TOP accrues Unpaid
		# until swept by consolidated billing.
		self.db_set(
			"payment_status",
			"Paid" if self.payment_type == "Cash" else "Unpaid",
			update_modified=False,
		)
		self._auto_invoice()

	def on_cancel(self):
		# Status is system-managed; a cancelled booking voids its still-Active codes.
		self.db_set("booking_status", "Cancelled", update_modified=False)
		for code in frappe.get_all(
			"Booking Code", filters={"booking": self.name, "state": "Active"}, pluck="name"
		):
			frappe.db.set_value("Booking Code", code, "state", "Cancelled", update_modified=False)

	def on_cancel(self):
		self._discard_unpaid_draft_invoice()

	def on_trash(self):
		self._discard_unpaid_draft_invoice()

	def _sync_lift_type(self):
		"""Lift type is the billing/crane view of the same move as ``direction`` —
		it is *derived*, never entered twice:

		* Tank In  → ``Lift Off`` (the tank is lifted OFF the truck / dropped at the
		  depot).
		* Tank Out → ``Lift On``  (the tank is lifted ON to the truck / taken from
		  the depot).

		The value drives the tariff *service* lookup, so it is kept read-only and
		always in lock-step with ``direction``."""
		self.lift_type = "Lift Off" if self.direction == "Tank In" else "Lift On"

	def _ensure_depot(self):
		"""Depot is mandatory (multi-depot ops): the Desk form enforces it
		client-side. Programmatic callers (tests / data patches / future portal)
		that omit it fall back to the primary active depot so every booking still
		carries one rather than failing the mandatory check."""
		if self.depot:
			return
		depot = frappe.db.get_value("Depot", {"is_active": 1}, "name") or frappe.db.get_value(
			"Depot", {}, "name"
		)
		if depot:
			self.depot = depot

	# ---- container resolution (single-input model) ----------------------
	def _resolve_containers(self):
		"""Reconcile each item's container reference into a real Container record.

		The portal/Desk shows a single ``container`` Link (pick from master or
		"+ Create New"). Backend / API callers may instead pass a ``container_no``
		string. Either way every item ends up with both a ``container`` link and a
		``container_no`` so downstream (Tank Out gating, booking codes, gate entry)
		always has a master record.

		* ``container`` link set  → it is authoritative; ``container_no`` is filled
		  from it.
		* only ``container_no`` set → look the master up; for **Tank In** create it
		  if missing (born in the pre-arrival ``Booked`` state). Tank Out never
		  auto-creates — it must reference an existing tank.

		For Tank In, a never-gated-in container is normalised to ``Booked`` so it
		stays out of live inventory until it physically arrives.
		"""
		for idx, item in enumerate(self.items or [], start=1):
			if item.container_no:
				item.container_no = item.container_no.strip().upper()
			if item.container:
				cn = frappe.db.get_value("Container", item.container, "container_no")
				if cn:
					item.container_no = cn
			elif item.container_no:
				name = frappe.db.get_value("Container", {"container_no": item.container_no})
				if not name and self.direction == "Tank In":
					name = self._create_pre_arrival_container(item.container_no, item.container_type)
				if name:
					item.container = name
			if not item.container and not item.container_no:
				frappe.throw(_("Item row {0}: pick a Container or enter a Container No.").format(idx))
			if self.direction == "Tank In" and item.container:
				self._mark_pre_arrival(item.container)

	def _create_pre_arrival_container(self, container_no, container_type=None):
		"""Create a Container master for a pre-announced (not-yet-arrived) tank."""
		doc = frappe.get_doc({
			"doctype": "Container",
			"container_no": container_no,
			"container_type": container_type or "ISO Tank",
			"status": "Booked",
			"principal": self.customer,
		})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _mark_pre_arrival(self, container):
		"""Flip a never-gated-in container to ``Booked`` without tripping the status
		guard. Containers that have already gated in (``eir_in_date`` set) are left
		untouched, so this never pulls a live tank out of inventory."""
		row = frappe.db.get_value("Container", container, ["status", "eir_in_date"], as_dict=True)
		if not row or row.eir_in_date or row.status == "Booked":
			return
		if row.status not in (None, "", "Available"):
			return
		frappe.flags.in_status_automation = True
		try:
			c = frappe.get_doc("Container", container)
			c.status = "Booked"
			c.save(ignore_permissions=True)
		finally:
			frappe.flags.in_status_automation = False

	# ---- portal guards --------------------------------------------------
	def _validate_do(self):
		"""Every booking — drop-off (Lift Off / Tank In) and pick-up (Lift On /
		Tank Out) — needs a Delivery Order *reference* before it can be confirmed.
		Enforced at submit so a draft can still be saved while the paperwork is
		gathered. The uploaded document (``do_document``) is optional — it can be
		attached later."""
		if not self.do_reference:
			frappe.throw(_("A Delivery Order reference is required to confirm this booking."))

	# ---- billing --------------------------------------------------------
	def _booking_amount(self):
		service = self.lift_type or ("Lift Off" if self.direction == "Tank In" else "Lift On")
		rate = pricing.resolve_tariff_rate(self.contract, service)
		qty = len(self.items or []) or 1
		return rate * qty, rate, service

	def _ensure_cash_invoice(self):
		"""Cash booking (incl. walk-in without a contract): auto-create a *draft*
		Sales Invoice on first save so the Cashier has something to mark Paid. The
		paid invoice is the gate that releases the booking code on submit.

		Idempotent (skips once ``sales_invoice`` is set). Best-effort: a site that
		isn't invoice-ready (no company) simply gets no invoice and the booking
		stays a draft. Priced from the contract tariff when present; for a walk-in
		without a tariff the line rate is 0 for the Cashier to fill in."""
		if self.sales_invoice or self.docstatus != 0:
			return
		if (self.payment_type or "Cash") != "Cash":
			return
		service = self.lift_type or ("Lift Off" if self.direction == "Tank In" else "Lift On")
		rate = pricing.resolve_tariff_rate(self.contract, service) if self.contract else 0
		qty = len(self.items or []) or 1
		try:
			si = invoicing.create_draft_sales_invoice(
				self.customer,
				[{
					"description": f"Isotank Booking ({self.direction}) · {service} · {qty} ctr",
					"qty": qty,
					"rate": rate or 0,
				}],
				due_days=30,
				remarks=f"Cash booking for {self.customer} ({self.direction}). Cashier to confirm payment.",
			)
			if si:
				self.sales_invoice = si
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"cash booking draft invoice failed: {self.customer}")

	def _auto_invoice(self):
		"""Best-effort transactional invoice for a booking that has none yet.

		Skipped for TOP (postpaid): those accrue Unpaid and are billed later via
		``consolidated_billing.bill_customer``. Cash already carries its draft/paid
		invoice."""
		if self.payment_type == "TOP":
			return
		if self.sales_invoice or not self.contract:
			return
		total, rate, service = self._booking_amount()
		if not total or total <= 0:
			return
		try:
			si = invoicing.create_draft_sales_invoice(
				self.customer,
				[{
					"description": f"Isotank Booking {self.name} · {service} · {len(self.items or [])} ctr",
					"qty": len(self.items or []) or 1,
					"rate": rate,
				}],
				due_days=30,
				remarks=f"Auto-generated from Isotank Booking {self.name}",
			)
			if si:
				self.db_set("sales_invoice", si, update_modified=False)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"booking auto-invoice failed: {self.name}")

	def _sync_payment_status_from_invoice(self):
		"""Reflect the linked Sales Invoice's live settlement on this booking so a
		draft whose Cash invoice is already paid stops reading 'Unpaid'. Only set
		when the invoice says something concrete (submitted) — a draft invoice
		leaves the booking's status untouched, and we never blank an existing one."""
		target = _invoice_settlement(self.sales_invoice)
		if target:
			self.payment_status = target

	def _discard_unpaid_draft_invoice(self):
		"""Cancelling or discarding a booking must not leave its auto-created Cash
		Sales Invoice behind as an orphan. If that invoice is still an *unpaid
		draft* (no ledger impact) delete it and unlink. A submitted / paid invoice
		is a real accounting document and is left untouched for the operator to
		handle deliberately (e.g. issue a credit note)."""
		si = self.sales_invoice
		if not si or not frappe.db.exists("Sales Invoice", si):
			return
		row = frappe.db.get_value("Sales Invoice", si, ["docstatus"], as_dict=True)
		if not row or row.docstatus != 0:
			return  # submitted / cancelled invoice — never auto-delete real accounting docs
		# Unlink first so the invoice has no inbound Link, then delete the orphan.
		frappe.db.set_value(self.doctype, self.name, "sales_invoice", None, update_modified=False)
		frappe.delete_doc("Sales Invoice", si, ignore_permissions=True, force=True)

	# ---- helpers --------------------------------------------------------
	def _sync_payment_type_from_contract(self):
		if not self.contract:
			# Walk-in: no standing contract → treat as Cash (Cashier marks the
			# auto-created Sales Invoice Paid to release the booking code).
			if not self.payment_type:
				self.payment_type = "Cash"
			return
		contract = frappe.db.get_value(
			"Depot Contract",
			self.contract,
			["customer", "payment_type", "status"],
			as_dict=True,
		)
		if not contract:
			frappe.throw(_("Contract {0} not found.").format(self.contract))
		if self.customer and contract.customer != self.customer:
			frappe.throw(_("Contract {0} belongs to a different customer.").format(self.contract))
		if contract.status != "Active":
			frappe.throw(_("Contract {0} is not Active (status={1}).").format(self.contract, contract.status))
		self.payment_type = contract.payment_type

	def _validate_tank_out_gating(self):
		"""TANK OUT requires every item to ref a clean+ready Container with a
		Cleaning Certificate that's still valid today.
		"""
		failures: list[str] = []
		for item in self.items or []:
			if not item.container:
				failures.append(
					_("Item for {0}: container link required for Tank Out.").format(
						item.container_no or "(no number)"
					)
				)
				continue
			c = frappe.db.get_value(
				"Container",
				item.container,
				["status", "container_no", "next_pt_due"],
				as_dict=True,
			)
			if not c:
				failures.append(_("Container {0} not found.").format(item.container))
				continue
			if c.status not in CONTAINER_READY_STATUSES:
				failures.append(
					_("Container {0} is not Ready (status={1}).").format(c.container_no, c.status)
				)
				continue
			if c.next_pt_due and getdate(c.next_pt_due) < getdate(today()):
				failures.append(
					_("Container {0} periodic test overdue (due {1}).").format(
						c.container_no, c.next_pt_due
					)
				)
				continue
			cert = frappe.db.get_value(
				"Cleaning Certificate",
				{
					"container": item.container,
					"docstatus": 1,
				},
				["name", "valid_until"],
				as_dict=True,
				order_by="clean_date desc",
			)
			if not cert:
				failures.append(
					_("Container {0} has no submitted Cleaning Certificate.").format(c.container_no)
				)
				continue
			if cert.valid_until and getdate(cert.valid_until) < getdate(today()):
				failures.append(
					_("Container {0} cleaning cert {1} expired on {2}.").format(
						c.container_no, cert.name, cert.valid_until
					)
				)

		if failures:
			frappe.throw("<br>".join(failures))

	def _enforce_payment_rules(self):
		"""TOP (postpaid / accrual): submit freely — the charge accrues Unpaid and
		is swept later by on-demand consolidated billing (``consolidated_billing.
		bill_customer``); no per-transaction credit gate. Cash / walk-in (no
		contract): linked Sales Invoice must be Paid — the Cashier's confirmation
		that releases the booking code.

		``_enforce_top_credit`` is retained (unused) in case credit gating is
		reinstated as a setting later.
		"""
		contract = get_active_contract(self.customer)
		payment_type = (contract.payment_type if contract else None) or self.payment_type or "Cash"
		if payment_type == "TOP":
			return  # accrual: free submit, billed later via consolidated billing
		# Cash, or walk-in without a contract
		self._enforce_cash_paid_invoice()

	def _enforce_cash_paid_invoice(self):
		if not self.sales_invoice:
			self._hold_pending_payment(_("Cash booking requires a paid Sales Invoice before submit."))
		status, docstatus = frappe.db.get_value(
			"Sales Invoice", self.sales_invoice, ["status", "docstatus"]
		) or (None, None)
		if docstatus != 1:
			self._hold_pending_payment(_("Sales Invoice {0} is not submitted.").format(self.sales_invoice))
		if status not in {"Paid", "Credit Note Issued"}:
			self._hold_pending_payment(
				_("Sales Invoice {0} status is {1}; must be Paid.").format(
					self.sales_invoice, status
				)
			)

	def _hold_pending_payment(self, reason: str):
		"""A Cash booking submitted before its Sales Invoice is paid is *not* an
		error to flag — it is simply awaiting the Cashier's confirmation. Park it
		in ``Pending Payment`` (persisted outside the about-to-throw transaction so
		it survives the submit rollback and stays visible) and refuse the submit.
		Once the Cashier marks the invoice Paid the next submit confirms it.

		Contrast ``_block`` which commits a hard ``Blocked`` status and is reserved
		for genuine blocks (TOP credit limit / overdue invoices)."""
		self.booking_status = "Pending Payment"
		self.block_reason = None
		if not self.is_new():
			frappe.db.set_value(
				self.doctype,
				self.name,
				{"booking_status": "Pending Payment", "block_reason": None},
				update_modified=False,
			)
			# Persist across the about-to-throw rollback. Skipped under tests, where
			# a mid-test commit would break FrappeTestCase isolation and leak data.
			if not frappe.flags.in_test:
				frappe.db.commit()
		frappe.throw(reason)

	def _enforce_top_credit(self, contract):
		"""Block if outstanding > credit_limit, or any overdue invoice exists."""
		outstanding = (
			frappe.db.sql(
				"""
				SELECT COALESCE(SUM(outstanding_amount), 0)
				FROM `tabSales Invoice`
				WHERE customer = %s AND docstatus = 1 AND status != 'Cancelled'
				""",
				(self.customer,),
			)[0][0]
			or 0
		)
		credit_limit = contract.credit_limit or 0
		if credit_limit and outstanding > credit_limit:
			self._block(
				_("TOP credit block: outstanding {0} exceeds credit limit {1}.").format(
					outstanding, credit_limit
				)
			)
		overdue = frappe.db.count(
			"Sales Invoice",
			filters={
				"customer": self.customer,
				"docstatus": 1,
				"status": "Overdue",
			},
		)
		if overdue:
			self._block(
				_("TOP credit block: {0} overdue Sales Invoice(s) for customer.").format(overdue)
			)

	def _block(self, reason: str):
		# Persist outside the about-to-throw transaction so the Blocked status
		# survives the rollback and is visible in audit / portal.
		self.booking_status = "Blocked"
		self.block_reason = reason
		if not self.is_new():
			frappe.db.set_value(
				self.doctype,
				self.name,
				{"booking_status": "Blocked", "block_reason": reason},
				update_modified=False,
			)
			# Persist across the about-to-throw rollback. Skipped under tests, where
			# a mid-test commit would break FrappeTestCase isolation and leak data.
			if not frappe.flags.in_test:
				frappe.db.commit()
		frappe.throw(reason)

	def _issue_booking_codes(self):
		issued_at = now_datetime()
		expires_at = add_to_date(issued_at, hours=CODE_TTL_HOURS)
		for item in self.items or []:
			if item.booking_code:
				continue
			code = frappe.get_doc({
				"doctype": "Booking Code",
				"code": generate_code(),
				"booking": self.name,
				"direction": self.direction,
				"container": item.container,
				"container_no": item.container_no or (
					frappe.db.get_value("Container", item.container, "container_no")
					if item.container else None
				),
				"status_tag": item.status_tag or "Dirty",
				"state": "Active",
				"issued_at": issued_at,
				"expires_at": expires_at,
			}).insert(ignore_permissions=True)
			# Persist the back-ref without re-validating the parent.
			frappe.db.set_value(
				"Isotank Booking Item",
				item.name,
				"booking_code",
				code.name,
				update_modified=False,
			)


# ---- payment-status sync (booking ↔ its Sales Invoice) ----------------------
# Scoped to Isotank Booking only: these helpers never touch monthly invoices or
# any other billing artefact.

def _invoice_settlement(sales_invoice):
	"""Map a linked Sales Invoice's live state to a booking ``payment_status``:
	``"Paid"`` (settled / credit note), ``"Invoiced"`` (submitted, still owing),
	or ``None`` (draft / missing invoice — leave the booking's status as-is)."""
	if not sales_invoice:
		return None
	si = frappe.db.get_value(
		"Sales Invoice", sales_invoice, ["docstatus", "status", "outstanding_amount"], as_dict=True
	)
	if not si or si.docstatus != 1:
		return None
	if si.status in ("Paid", "Credit Note Issued") or (si.outstanding_amount or 0) <= 0:
		return "Paid"
	return "Invoiced"


def sync_bookings_for_invoice(sales_invoice):
	"""Push a Sales Invoice's settlement state onto every Isotank Booking pinned to
	it (draft or submitted)."""
	target = _invoice_settlement(sales_invoice)
	if not target:
		return
	for name in frappe.get_all("Isotank Booking", filters={"sales_invoice": sales_invoice}, pluck="name"):
		if frappe.db.get_value("Isotank Booking", name, "payment_status") != target:
			frappe.db.set_value("Isotank Booking", name, "payment_status", target, update_modified=False)


def on_payment_entry_change(doc, method=None):
	"""doc_event (Payment Entry on_submit / on_cancel): refresh the ``payment_status``
	of any Isotank Booking tied to the Sales Invoice(s) this payment settles. Runs
	after ERPNext has recomputed the invoice outstanding, so the read is current."""
	seen = set()
	for ref in (doc.get("references") or []):
		si = ref.reference_name if ref.reference_doctype == "Sales Invoice" else None
		if si and si not in seen:
			seen.add(si)
			sync_bookings_for_invoice(si)
