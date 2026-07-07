"""Container Booking — the booking spine for PRO-OPS-08 Tank In / Tank Out.

Carries the three Phase-3 critical controllers:

1. TOP credit-block (``before_submit``): TOP customers blocked when outstanding
   exceeds credit limit or any overdue Sales Invoice exists. Cash bookings
   require a *paid* linked Sales Invoice before submit.
2. TANK OUT gating (``validate`` when direction == 'Tank Out'): every item must
   reference a Container that is clean + ready, with a Cleaning Certificate
   whose ``valid_until`` covers today.
3. Booking Code issuance on submit (one per item). Codes do not expire.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import cint, getdate, now_datetime, today

from container_depot import invoicing, pricing, pricing_model
from container_depot.operations.doctype.booking_code.booking_code import (
	generate_code,
)
from container_depot.operations.doctype.depot_contract.depot_contract import (
	get_active_contract,
)
from container_depot.operations.container_activity import log_container_activity
from container_depot.state_machine import stage_for_status


CONTAINER_READY_STATUSES = {"Available"}

# The Item Group that holds every Lift Service (Lift On / Lift Off and any sized
# variants such as "Lift On 20F"). The booking's Lift Service picker is scoped to it,
# so a new sized service only needs to be filed under this group to become selectable.
LOLO_ITEM_GROUP = "LOLO"


def lift_direction_for(lift_item: str | None) -> str | None:
	"""Map a Lift Service item to the booking's in/out ``direction`` from its name.

	``lift_item`` is the ONE thing the operator picks; ``direction`` (Tank In / Tank Out)
	and ``lift_type`` are derived from it — never entered separately. The read is by the
	*Lift On* / *Lift Off* token in the name, tolerant of size / variant suffixes, so a
	service named ``Lift On 20F`` (or ``20F Lift On``) still resolves to outbound:

	* a name carrying *Lift On*  → ``Tank Out`` (tank lifted ON the truck / leaves depot)
	* a name carrying *Lift Off* → ``Tank In``  (tank lifted OFF the truck / enters depot)
	* empty / unrecognised / ambiguous → ``None`` (caller keeps the current direction).
	"""
	s = (lift_item or "").strip().lower()
	if not s:
		return None
	has_on = "lift on" in s
	has_off = "lift off" in s
	if has_on and not has_off:
		return "Tank Out"
	if has_off and not has_on:
		return "Tank In"
	return None


def status_tag_for_condition(condition: str | None) -> str:
	"""Clean/Dirty gate tag carried onto a Booking Code, derived from a line's
	``condition``: EMPTY CLEAN → ``Clean``; anything else (EMPTY DIRTY / LADEN / unset)
	→ ``Dirty``. A pure function — the tag is computed at booking-code issuance, not
	stored on the line (the line only keeps ``condition``)."""
	return "Clean" if condition == "EMPTY CLEAN" else "Dirty"


class ContainerBooking(Document):
	# ---- naming ---------------------------------------------------------
	def autoname(self):
		# Direction is derived from the picked Lift Service, so resolve it before the
		# BKG-IN / BKG-OUT prefix is chosen (autoname runs before validate on insert).
		self._sync_direction_from_lift()
		prefix = "BKG-IN-" if self.direction == "Tank In" else "BKG-OUT-"
		self.name = make_autoname(prefix + ".YYYY.-.#####")

	# ---- lifecycle ------------------------------------------------------
	def validate(self):
		if self.docstatus == 0 and self.booking_status == "Cancelled":
			# A voided draft (see ``void_draft``) is terminal — never re-price or
			# re-reserve it, so a re-save can't resurrect its rolled-back invoice / tanks.
			return
		self._ensure_depot()
		self._ensure_branch_and_principal()
		self._sync_direction_from_lift()
		self._resolve_pricing_context()
		self._resolve_containers()
		self._compute_lift_amount()
		self._sync_payment_type_from_contract()
		# Readiness is enforced at SUBMIT (see before_submit), not here — an outbound
		# booking may be saved as a draft while its container's EIR/Cleaning/M&R finish.

	def after_insert(self):
		# Notify Commercial / admin / Cashier that a new booking (and, for Cash, a
		# payment to collect) exists — shows in the PWA + Desk bell.
		from container_depot.operations.notify import notify_booking_created
		notify_booking_created(self)

	def before_save(self):
		self._ensure_cash_invoice()
		self._sync_payment_status_from_invoice()

	def before_submit(self):
		if self.booking_status == "Cancelled":
			frappe.throw(_("This booking was cancelled and cannot be confirmed. Create a new one."))
		self._require_contract()
		self._enforce_payment_rules()
		self._validate_do()
		# Presence-based in/out gates (draft allowed; only submit is blocked).
		if self.direction == "Tank Out":
			self._validate_out_ready()
		elif self.direction == "Tank In":
			self._validate_in_not_present()

	def on_submit(self):
		self._issue_booking_codes()
		self.db_set("booking_status", "Confirmed", update_modified=False)
		for item in (self.items or []):
			if item.get("container"):
				log_container_activity(
					item.container, "Booking",
					reference_doctype=self.doctype, reference_name=self.name,
					summary=f"Booking confirmed ({self.get('direction') or 'Tank In'})",
				)
		# Cash bookings clear their (Paid) invoice at submit; TOP accrues Unpaid
		# until swept by consolidated billing.
		self.db_set(
			"payment_status",
			"Paid" if self.payment_type == "Cash" else "Unpaid",
			update_modified=False,
		)
		self._auto_invoice()
		# Outbound (Lift On / Tank Out): task a Surveyor to locate each container's yard
		# position before it is pulled. Best-effort — never block the booking submit.
		if self.direction == "Tank Out":
			try:
				from container_depot.operations.position_survey import provision_position_survey_for_booking
				provision_position_survey_for_booking(self.name)
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"provision position survey for {self.name}")
		from container_depot.operations.notify import notify_booking_submitted
		notify_booking_submitted(self)

	def on_cancel(self):
		"""Cancelling a booking unwinds everything it spun up:

		1. ``booking_status`` → ``Cancelled`` (system-managed).
		2. Every still-``Active`` Booking Code is voided — a cancelled booking must
		   not keep live 72h gate-access codes.
		3. The auto-created Sales Invoice is cancelled but kept linked (a draft is marked
		   Cancelled in place; a submitted one has its Payment Entries reversed then is
		   cancelled), and ``payment_status`` is set to Cancelled.
		4. Pre-arrival containers are unwound (phantom deleted / flipped tank
		   reverted) — see ``_release_pre_arrival_containers``.
		"""
		self.db_set("booking_status", "Cancelled", update_modified=False)
		for code in frappe.get_all(
			"Booking Code", filters={"booking": self.name, "state": "Active"}, pluck="name"
		):
			frappe.db.set_value("Booking Code", code, "state", "Cancelled", update_modified=False)
		self._cancel_invoice_keep_link()
		self.db_set("payment_status", "Cancelled", update_modified=False)
		self._release_pre_arrival_containers()

	def on_trash(self):
		# A booking is never permanently deleted — it is voided/cancelled (Cancel) so its
		# audit trail and cancelled invoice stay. The UI Delete/Discard actions are also
		# hidden in the form script; raw maintenance (frappe.db.delete) bypasses this guard.
		frappe.throw(_("A Container Booking cannot be deleted — use Cancel to void it instead."))

	def _release_pre_arrival_containers(self):
		"""Unwind the Tank-In container reservations this booking made.

		For each item's container that is still ``Booked`` and has **never gated
		in** (``eir_in_date`` empty) and is not reserved by any *other* live
		booking:

		* **Phantom** (``created_by_booking == this booking``) — a master that
		  only exists because of this booking → delete it (force, since the
		  cancelled booking / voided codes still point at it).
		* **Pre-existing** tank this booking merely flipped → revert to
		  ``Available``.

		Containers that have gated in, moved on in their lifecycle, or are held by
		another active booking are left untouched."""
		for item in self.items or []:
			container = item.container
			if not container or not frappe.db.exists("Container", container):
				continue
			row = frappe.db.get_value(
				"Container", container, ["status", "eir_in_date", "created_by_booking"], as_dict=True
			)
			if not row or row.status != "Booked" or row.eir_in_date:
				continue  # live / already moved on — never touch
			if self._container_held_by_other_booking(container):
				continue  # another live booking still reserves it
			if row.created_by_booking == self.name:
				# Phantom born for this booking: drop the dangling links (item ref,
				# booking codes, and the auto-logged status Movement), then delete.
				frappe.db.set_value("Container Booking Item", item.name, "container", None, update_modified=False)
				frappe.db.delete("Booking Code", {"booking": self.name, "container": container})
				frappe.db.delete("Container Movement", {"container": container})
				frappe.delete_doc("Container", container, ignore_permissions=True, force=True)
			else:
				# Pre-existing tank we only flipped to Booked → release it. Direct
				# set_value bypasses Container.before_save, so set the stage too.
				frappe.db.set_value(
					"Container",
					container,
					{"status": "Available", "inventory_stage": stage_for_status("Available")},
					update_modified=False,
				)

	def _container_held_by_other_booking(self, container):
		"""True if a *different* non-cancelled Container Booking still has this
		container on an item (so cancel must leave the reservation alone)."""
		rows = frappe.db.sql(
			"""
			SELECT 1
			FROM `tabContainer Booking Item` i
			JOIN `tabContainer Booking` b ON b.name = i.parent
			WHERE i.container = %s AND b.name != %s AND b.docstatus < 2
			LIMIT 1
			""",
			(container, self.name),
		)
		return bool(rows)

	def _sync_direction_from_lift(self):
		"""The operator picks ONE thing — the Lift Service (``lift_item``). ``direction``
		(Tank In / Tank Out) and ``lift_type`` are both *derived* from it, never entered
		separately:

		* a Lift On service  → ``direction`` Tank Out, ``lift_type`` Lift On  (tank lifted
		  ON to the truck / taken from the depot).
		* a Lift Off service → ``direction`` Tank In,  ``lift_type`` Lift Off (tank lifted
		  OFF the truck / dropped at the depot).

		``direction`` stays the internal in/out flag the whole pipeline keys off (naming,
		Tank Out gating, Order Bongkar vs Order Muat, EIR, booking codes, survey). It is
		hidden/read-only on the form. When the service is empty (draft) or unrecognised,
		direction keeps its current value (doctype default Tank In) so a half-filled draft
		never flips arbitrarily. Tolerant of sized service names (e.g. ``Lift On 20F``)."""
		derived = lift_direction_for(self.lift_item)
		if derived:
			self.direction = derived
		self.lift_type = "Lift On" if self.direction == "Tank Out" else "Lift Off"

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

	def _ensure_branch_and_principal(self):
		"""Branch and Principal (Tank Owner) are mandatory and enforced on the Desk
		form. Programmatic callers (tests / API) that omit them fall back — branch from
		the depot (or any branch), principal from the booking customer — so every
		booking still carries both rather than failing the mandatory check (mirrors
		``_ensure_depot``)."""
		if not self.principal:
			self.principal = self.customer
		if not self.branch:
			self.branch = (
				frappe.db.get_value("Depot", self.depot, "branch") if self.depot else None
			) or frappe.db.get_value("Branch", {}, "name")

	# ---- pricing context (customer contract / price list) ---------------
	def _resolve_pricing_context(self):
		"""Pricing follows the customer's *active* Price List — the one published by their
		active contract and mirrored onto ``Customer.default_price_list``. It is resolved
		automatically (hidden, never picked by hand); its currency (USD / IDR) drives the
		Lift Rate with no exchange-rate conversion. The operator only picks the Lift
		Service, and its rate is read from that active list. The customer's active contract
		is also resolved (hidden) for the allowed payment modes; the hard "must have a
		contract / price list" rule is enforced at submit."""
		contract = get_active_contract(self.customer) if self.customer else None
		self.contract = contract.name if contract else None
		# The customer's active price list — auto-resolved, not shown or picked. Empty
		# only for a walk-in with no default list (then the Lift Rate stays 0).
		self.price_list = pricing_model.price_list_for_customer(self.customer) if self.customer else None
		# Programmatic submit (tests / API) without an explicit lift pick falls back to the
		# standard Lift Off / Lift On item; the Desk form makes the operator pick it.
		if self.docstatus == 1 and self.customer and not self.lift_item:
			self.lift_item = pricing.LIFT_OFF_ITEM if self.direction == "Tank In" else pricing.LIFT_ON_ITEM
		if self.price_list:
			self.currency = frappe.db.get_value("Price List", self.price_list, "currency") or self.currency
			self.lift_rate = (
				pricing_model.resolve_price(self.lift_item, self.price_list) if self.lift_item else 0
			) or 0
		else:
			self.lift_rate = 0

	def _compute_lift_amount(self):
		"""Qty = number of containers on the booking. The lift charge is billed *per
		container*, so the booking's lift amount = Lift Rate × Qty — the same quantity
		the Sales Invoice carries (see ``_booking_amount`` / ``_ensure_cash_invoice``)."""
		self.lift_qty = len(self.items or [])
		self.lift_amount = (self.lift_rate or 0) * (self.lift_qty or 0)

	def _require_contract(self):
		"""Block confirmation until the customer has an agreed price list. The lift
		charge and payment terms both come from the contract, so there is nothing to
		bill against without one."""
		if not self.contract:
			frappe.throw(
				_("{0} has no active contract / price list — create one for this customer first.").format(
					self.customer or _("This customer")
				)
			)

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

		The Clean/Dirty gate tag carried onto each Booking Code is derived from the line's
		``condition`` at issuance (see ``status_tag_for_condition``) — it is not stored
		on the line.

		For Tank In, a never-gated-in container is normalised to ``Booked`` so it
		stays out of live inventory until it physically arrives.
		"""
		for item in self.items or []:
			if item.container_no:
				item.container_no = item.container_no.strip().upper()
			if not item.container and not item.container_no:
				continue  # blank row — allowed on a draft; containers are enforced at submit
			if item.container:
				cn = frappe.db.get_value("Container", item.container, "container_no")
				if cn:
					item.container_no = cn
			elif item.container_no:
				name = frappe.db.get_value("Container", {"container_no": item.container_no})
				if not name and self.direction == "Tank In":
					name = self._create_pre_arrival_container(item.container_no)
				if name:
					item.container = name
			if self.direction == "Tank In" and item.container:
				self._mark_pre_arrival(item.container)

	def _create_pre_arrival_container(self, container_no):
		"""Create a Container master for a pre-announced (not-yet-arrived) tank.

		Stamped with ``created_by_booking`` so cancelling this booking can clean
		the phantom up (delete it) — as opposed to a pre-existing tank that this
		booking merely flipped to ``Booked``, which cancel only reverts. Owned by the
		booking's Principal (Tank Owner)."""
		doc = frappe.get_doc({
			"doctype": "Container",
			"container_no": container_no,
			"container_type": "ISO Tank",
			"status": "Booked",
			"principal": self.principal or self.customer,
			"created_by_booking": self.name,
		})
		# This runs inside the booking's own validate — the booking row is not in
		# the DB yet, so skip link validation on created_by_booking; it resolves as
		# soon as the booking is inserted (same transaction, immediately after).
		doc.insert(ignore_permissions=True, ignore_links=True)
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
	def _resolve_service_rate(self, service):
		"""Per-unit selling rate for a booking's lift ``service`` — read from the customer's
		active Price List (resolved in ``_resolve_pricing_context``), then the customer's
		contract tariff, then their default Price List (walk-in / draft). The first two
		normally point at the same published list. Returns 0 when nothing prices it so the
		Cashier can fill the rate in on the draft invoice."""
		if self.price_list:
			return pricing_model.resolve_price(service, self.price_list) or 0
		if self.contract:
			return pricing.resolve_tariff_rate(self.contract, service)
		price_list = pricing_model.price_list_for_customer(self.customer)
		return (pricing_model.resolve_price(service, price_list) if price_list else 0) or 0

	def _booking_amount(self):
		service = self.lift_item or self.lift_type or ("Lift Off" if self.direction == "Tank In" else "Lift On")
		rate = self._resolve_service_rate(service)
		qty = len(self.items or []) or 1
		return rate * qty, rate, service

	def _ensure_cash_invoice(self):
		"""Cash booking (incl. walk-in without a contract): auto-create a *draft*
		Sales Invoice on first save so the Cashier has something to mark Paid. The
		paid invoice is the gate that releases the booking code on submit.

		Idempotent (skips once ``sales_invoice`` is set). Best-effort: a site that
		isn't invoice-ready (no company) simply gets no invoice and the booking
		stays a draft. Priced from the contract tariff when present; for a walk-in
		without a contract the default rate comes from the customer's Price List
		(0 only when neither prices it, leaving it for the Cashier to fill in)."""
		if self.sales_invoice or self.docstatus != 0:
			return
		if self.booking_status == "Cancelled":
			return  # a voided draft must not resurrect its rolled-back invoice
		if (self.payment_type or "Cash") != "Cash":
			return
		service = self.lift_item or self.lift_type or ("Lift Off" if self.direction == "Tank In" else "Lift On")
		rate = self._resolve_service_rate(service)
		qty = len(self.items or []) or 1
		try:
			si = invoicing.create_draft_sales_invoice(
				self.customer,
				[{
					"item_code": service,
					"description": f"Container Booking ({self.direction}) · {service} · {qty} ctr",
					"qty": qty,
					"rate": rate or 0,
				}],
				due_days=30,
				remarks=f"Cash booking for {self.customer} ({self.direction}). Cashier to confirm payment.",
				currency=self.currency,
				selling_price_list=self.price_list,
				branch=self.branch,
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
					"item_code": service,
					"description": f"Container Booking {self.name} · {service} · {len(self.items or [])} ctr",
					"qty": len(self.items or []) or 1,
					"rate": rate,
				}],
				due_days=30,
				remarks=f"Auto-generated from Container Booking {self.name}",
				currency=self.currency,
				selling_price_list=self.price_list,
				branch=self.branch,
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

	def _cancel_invoice_keep_link(self):
		"""Cancel the booking's auto-created Sales Invoice but KEEP it linked, so the
		cancelled invoice stays visible on the booking for audit:

		* **Draft** auto-invoice (never submitted, no ledger impact) → mark it Cancelled
		  in place (docstatus 2) so it shows as a cancelled invoice on the booking.
		* **Submitted** → reverse settlement first (cancel its submitted Payment Entries),
		  then cancel the invoice (its GL is reversed).

		Best-effort: a failure is logged and never blocks the booking cancel. The
		``sales_invoice`` link is left intact either way."""
		si = self.sales_invoice
		if not si or not frappe.db.exists("Sales Invoice", si):
			return
		docstatus = frappe.db.get_value("Sales Invoice", si, "docstatus")
		if docstatus == 2:
			return  # already cancelled
		try:
			if docstatus == 1:
				self._cancel_linked_payments(si)
				inv = frappe.get_doc("Sales Invoice", si)
				inv.flags.ignore_permissions = True
				inv.cancel()
			else:
				frappe.db.set_value(
					"Sales Invoice", si, {"docstatus": 2, "status": "Cancelled"}, update_modified=False
				)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"booking invoice cancel failed: {self.name}")

	def _cancel_linked_payments(self, sales_invoice):
		"""Cancel every submitted Payment Entry that settles ``sales_invoice`` so the
		invoice can then be cancelled (a paid invoice can't be cancelled while live
		payments still reference it)."""
		payments = frappe.get_all(
			"Payment Entry Reference",
			filters={
				"reference_doctype": "Sales Invoice",
				"reference_name": sales_invoice,
				"docstatus": 1,
			},
			pluck="parent",
		)
		for pe in set(payments):
			if frappe.db.get_value("Payment Entry", pe, "docstatus") == 1:
				doc = frappe.get_doc("Payment Entry", pe)
				doc.flags.ignore_permissions = True
				doc.cancel()

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
		if contract.payment_type == "Both":
			# The customer may transact either way — keep the operator's pick (default Cash).
			if self.payment_type not in ("Cash", "TOP"):
				self.payment_type = "Cash"
		else:
			# Cash / TOP contract — the booking inherits the contract's single mode.
			self.payment_type = contract.payment_type

	def _validate_out_ready(self):
		"""TANK OUT submit gate: every container must be Available — i.e. present and with
		every related order (EIR-In, Cleaning, M&R) finished. A draft may be saved earlier;
		only the submit is blocked while work is outstanding."""
		from container_depot.operations.container_status import AVAILABLE

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
				"Container", item.container, ["status", "container_no"], as_dict=True
			)
			if not c:
				failures.append(_("Container {0} not found.").format(item.container))
				continue
			if c.status != AVAILABLE:
				failures.append(
					_(
						"Container {0} belum siap keluar (status {1}) — selesaikan EIR / Cleaning / "
						"M&R dulu sebelum submit booking keluar."
					).format(c.container_no, c.status)
				)

		if failures:
			frappe.throw("<br>".join(failures))

	def _validate_in_not_present(self):
		"""TANK IN submit gate: a container must NOT already be physically in a depot —
		import only a tank that is not currently present (In_Depot / Available)."""
		from container_depot.operations.container_status import PRESENT

		failures: list[str] = []
		for item in self.items or []:
			if not item.container:
				continue  # a brand-new pre-arrival phantom is created fresh — always fine
			status = frappe.db.get_value("Container", item.container, "status")
			if status in PRESENT:
				failures.append(
					_(
						"Container {0} masih ada di depo (status {1}) — tidak bisa dibuat booking masuk."
					).format(item.container_no or item.container, status)
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
		# self.payment_type is the booking's effective mode (synced from the contract in
		# validate; a Both contract leaves the operator's Cash/TOP choice intact).
		payment_type = self.payment_type or "Cash"
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
				"status_tag": status_tag_for_condition(item.condition),
				"state": "Active",
				"issued_at": issued_at,
			}).insert(ignore_permissions=True)
			# Persist the back-ref without re-validating the parent.
			frappe.db.set_value(
				"Container Booking Item",
				item.name,
				"booking_code",
				code.name,
				update_modified=False,
			)


# ---- Tank In booking link queries / pricing helpers (whitelisted) -----------

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def lift_item_query(doctype, txt, searchfield, start, page_len, filters):
	"""Lift services (Lift On / Lift Off) priced in the customer's *active* Price List —
	the options for a booking's Lift Service field. The price list is resolved from the
	customer (their contract-published / default list), never picked by hand."""
	customer = (filters or {}).get("customer")
	price_list = pricing_model.price_list_for_customer(customer) if customer else None
	if not price_list:
		return []
	like = f"%{txt or ''}%"
	# Every Lift Service filed under the LOLO group and priced in the customer's active
	# list — not a hard-coded ("Lift On", "Lift Off") pair — so sized variants like
	# "Lift On 20F" become selectable by simply filing them under LOLO. Direction then
	# derives from each item's name (see ``lift_direction_for``).
	return frappe.db.sql(
		"""
		SELECT ip.item_code
		FROM `tabItem Price` ip
		JOIN `tabItem` it ON it.name = ip.item_code
		WHERE ip.selling = 1 AND ip.price_list = %(pl)s
		  AND it.item_group = %(grp)s AND it.disabled = 0
		  AND ip.item_code LIKE %(like)s
		ORDER BY ip.item_code
		LIMIT {start}, {page_len}
		""".format(start=cint(start), page_len=cint(page_len)),
		{"pl": price_list, "grp": LOLO_ITEM_GROUP, "like": like},
	)


@frappe.whitelist()
def lift_rate_for(customer, item):
	"""Selling rate + currency for a lift Item from the customer's *active* Price List, so
	the form can format Lift Rate in the price-list currency (USD / IDR) before save. The
	list is resolved from the customer — no exchange-rate conversion, nothing picked."""
	price_list = pricing_model.price_list_for_customer(customer) if customer else None
	if not price_list or not item:
		return {"rate": 0, "currency": None}
	rate = pricing_model.resolve_price(item, price_list) or 0
	currency = frappe.db.get_value("Price List", price_list, "currency")
	return {"rate": rate, "currency": currency}


@frappe.whitelist()
def customer_payment_modes(customer):
	"""Payment modes a customer's bookings may use, from their active contract:
	``["Cash"]`` / ``["TOP"]`` / ``["Cash", "TOP"]``. Returns ``[]`` when the customer
	has no active contract — the caller must create a contract / price list first."""
	contract = get_active_contract(customer) if customer else None
	if not contract:
		return []
	return ["Cash", "TOP"] if contract.payment_type == "Both" else [contract.payment_type]


@frappe.whitelist()
def void_draft(booking):
	"""Void a *draft* Container Booking without deleting it.

	Cancel is the only 'undo' on a draft (a booking is never hard-deleted / discarded):
	it rolls back what the draft spun up — the auto-created Sales Invoice (cancelled but
	kept linked & visible) and the pre-arrival container reservations — sets the booking
	+ payment status to Cancelled, and marks the document itself Cancelled (docstatus 2)
	so it reads 'Cancelled', not 'Draft'. Submit stays the only approve."""
	doc = frappe.get_doc("Container Booking", booking)
	if doc.docstatus != 0:
		frappe.throw(_("Only a draft booking can be cancelled here."))
	doc._cancel_invoice_keep_link()
	doc._release_pre_arrival_containers()
	doc.db_set("booking_status", "Cancelled", update_modified=False)
	doc.db_set("payment_status", "Cancelled", update_modified=False)
	# A draft can't go through native submit→cancel, so mark Cancelled (docstatus 2)
	# directly; child rows mirror the parent docstatus.
	frappe.db.set_value("Container Booking", doc.name, "docstatus", 2, update_modified=False)
	frappe.db.sql("UPDATE `tabContainer Booking Item` SET docstatus=2 WHERE parent=%s", doc.name)
	return doc.booking_status


@frappe.whitelist()
def revert_booking_to_draft(booking):
	"""Bring a SUBMITTED booking back to an editable draft WITHOUT touching its payment.

	Use case: a Cash booking was paid (and so auto-confirmed), but a data correction is
	needed before the tank moves. Unlike Cancel — which reverses the Payment Entries and
	cancels the invoice — this keeps the paid Sales Invoice, its Payment Entries and the
	issued Booking Codes intact, and just flips the same record back to a draft so it can be
	edited and Submitted again (payment is already settled, so re-submit re-confirms it).

	Refused once any Booking Code has been consumed onto a bon (state ``Used``): the tank is
	already in motion at the gate, so the booking must not be reopened."""
	doc = frappe.get_doc("Container Booking", booking)
	doc.check_permission("cancel")
	if doc.docstatus != 1:
		frappe.throw(_("Hanya booking yang sudah disubmit yang bisa dikembalikan ke draft."))

	used = frappe.get_all(
		"Booking Code", filters={"booking": doc.name, "state": "Used"}, pluck="name"
	)
	if used:
		frappe.throw(_(
			"Tidak bisa dikembalikan ke draft: sudah ada container yang diproses di gate "
			"(Booking Code {0}). Batalkan bon terkait dulu jika perlu mengubah data."
		).format(", ".join(used)))

	# Flip the same record back to an editable draft. Payment / invoice / codes are left
	# exactly as they are — Submit again to re-confirm.
	frappe.db.set_value(
		"Container Booking", doc.name,
		{"docstatus": 0, "booking_status": "Pending Confirmation"},
		update_modified=False,
	)
	frappe.db.sql("UPDATE `tabContainer Booking Item` SET docstatus=0 WHERE parent=%s", doc.name)
	return {"booking": doc.name, "docstatus": 0, "booking_status": "Pending Confirmation"}


# ---- payment-status sync (booking ↔ its Sales Invoice) ----------------------
# Scoped to Container Booking only: these helpers never touch monthly invoices or
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


# --- Sales Invoice → Container Booking bridge -------------------------------------
# Every handler below is a no-op unless a Container Booking is pinned to the invoice,
# so plain ERPNext invoices (sales, POS, anything not born from a booking) are left
# completely untouched. Wired in hooks.doc_events["Sales Invoice"].

def relink_amended_invoice(doc, method=None):
	"""after_insert: when a booking's Sales Invoice is amended, the new invoice carries
	``amended_from`` = the old one. Move the booking's link onto the new invoice so the
	booking follows the amendment instead of dangling on the cancelled original."""
	if not doc.amended_from:
		return
	for name in frappe.get_all(
		"Container Booking", filters={"sales_invoice": doc.amended_from}, pluck="name"
	):
		frappe.db.set_value("Container Booking", name, "sales_invoice", doc.name, update_modified=False)


def sync_booking_on_invoice_submit(doc, method=None):
	"""on_submit: push the invoice's settlement onto any booking pinned to it (covers an
	invoice submitted directly, including an amended one). Guarded inside
	``sync_bookings_for_invoice`` — no-op when no booking links it."""
	sync_bookings_for_invoice(doc.name)


def resync_booking_on_invoice_cancel(doc, method=None):
	"""on_cancel: a booking's Sales Invoice was cancelled DIRECTLY (not via the booking's
	own cancel — that path sets ``booking_status`` = Cancelled first, which we skip). Mark
	the still-live booking Unpaid so it surfaces as needing a fresh invoice (Regenerate)."""
	for name in frappe.get_all("Container Booking", filters={"sales_invoice": doc.name}, pluck="name"):
		row = frappe.db.get_value(
			"Container Booking", name, ["docstatus", "booking_status", "payment_status"], as_dict=True
		)
		if (
			row
			and row.docstatus == 1
			and row.booking_status != "Cancelled"
			and row.payment_status != "Cancelled"
		):
			frappe.db.set_value("Container Booking", name, "payment_status", "Unpaid", update_modified=False)


@frappe.whitelist()
def regenerate_invoice(booking):
	"""Create a fresh DRAFT Sales Invoice for a confirmed booking whose linked invoice was
	cancelled (or is gone), and re-link it — so the booking can be re-billed without amending
	the dead invoice (which would leave a -1 duplicate the booking never follows). Scoped to
	Container Booking only."""
	frappe.has_permission("Container Booking", ptype="write", throw=True)
	doc = frappe.get_doc("Container Booking", booking)
	if doc.docstatus != 1 or doc.booking_status == "Cancelled":
		frappe.throw(_("Only a confirmed booking can regenerate its invoice."))
	cur = doc.sales_invoice
	if cur and frappe.db.exists("Sales Invoice", cur) and frappe.db.get_value("Sales Invoice", cur, "docstatus") != 2:
		frappe.throw(_("Booking still has a live Sales Invoice {0}. Cancel it first.").format(cur))
	_total, rate, service = doc._booking_amount()
	qty = len(doc.items or []) or 1
	si = invoicing.create_draft_sales_invoice(
		doc.customer,
		[{
			"item_code": service,
			"description": f"Container Booking {doc.name} · {service} · {qty} ctr (regenerated)",
			"qty": qty,
			"rate": rate or 0,
		}],
		due_days=30,
		remarks=f"Regenerated for Container Booking {doc.name} after the previous invoice was cancelled.",
		currency=doc.currency,
		selling_price_list=doc.price_list,
		branch=doc.branch,
	)
	if not si:
		frappe.throw(_("Could not create a Sales Invoice (is the site invoice-ready?)."))
	doc.db_set("sales_invoice", si, update_modified=False)
	doc.db_set("payment_status", "Unpaid", update_modified=False)
	return si


def sync_bookings_for_invoice(sales_invoice):
	"""Push a Sales Invoice's settlement state onto every Container Booking pinned to it.

	Cash is 'pay first': the booking waits as a draft until the Cashier settles its Sales
	Invoice. When the invoice reads Paid, a Cash booking is **auto-submitted (confirmed)** —
	the operator no longer confirms by hand. If the auto-submit can't go through (e.g. a
	required field is missing) the booking is left at Pending Confirmation for the admin to
	finish, and the gate shows "hubungi admin"."""
	target = _invoice_settlement(sales_invoice)
	if not target:
		return
	for name in frappe.get_all("Container Booking", filters={"sales_invoice": sales_invoice}, pluck="name"):
		row = frappe.db.get_value(
			"Container Booking", name,
			["payment_status", "docstatus", "payment_type", "booking_status"], as_dict=True,
		)
		if row.payment_status != target:
			frappe.db.set_value("Container Booking", name, "payment_status", target, update_modified=False)
		# Cash paid → auto-confirm the booking. Best-effort: fall back to Pending
		# Confirmation so a paid-but-unconfirmed booking is visible to the admin.
		if (
			target == "Paid"
			and row.docstatus == 0
			and (row.payment_type or "Cash") == "Cash"
			and row.booking_status in ("Pending Payment", "Pending Confirmation")
		):
			if not _auto_submit_paid_booking(name) and row.booking_status != "Pending Confirmation":
				frappe.db.set_value(
					"Container Booking", name, "booking_status", "Pending Confirmation", update_modified=False
				)


def _auto_submit_paid_booking(name) -> bool:
	"""Submit a paid Cash booking on the Cashier's behalf. Returns True on success.

	Never raises — a failed auto-submit must not abort the payment that triggered it. A
	savepoint isolates the rollback so only the failed submit is undone, never the Payment
	Entry that is mid-flight in the same transaction."""
	frappe.db.savepoint("auto_submit_booking")
	try:
		doc = frappe.get_doc("Container Booking", name)
		if doc.docstatus != 0 or doc.booking_status == "Cancelled":
			return False
		doc.flags.ignore_permissions = True
		doc.submit()
		return True
	except Exception:
		frappe.db.rollback(save_point="auto_submit_booking")
		frappe.log_error(frappe.get_traceback(), f"auto-submit paid booking {name}")
		return False


def on_payment_entry_change(doc, method=None):
	"""doc_event (Payment Entry on_submit / on_cancel): refresh the ``payment_status``
	of any Container Booking tied to the Sales Invoice(s) this payment settles. Runs
	after ERPNext has recomputed the invoice outstanding, so the read is current."""
	seen = set()
	for ref in (doc.get("references") or []):
		si = ref.reference_name if ref.reference_doctype == "Sales Invoice" else None
		if si and si not in seen:
			seen.add(si)
			sync_bookings_for_invoice(si)
