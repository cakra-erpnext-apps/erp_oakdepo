"""Container Booking — the booking spine for PRO-OPS-08 Tank In / Tank Out.

``direction`` is the operator's pick and the axis everything turns on: Tank In = Lift Off
(tank dropped at the depot), Tank Out = Lift On (tank taken from it). It decides the
BKG-IN / BKG-OUT number, which status gate the containers face, and whether a bon becomes
an Order Bongkar or an Order Muat.

Carries the critical controllers:

1. TOP credit-block (``before_submit``): TOP customers blocked when outstanding
   exceeds credit limit or any overdue Sales Invoice exists. Cash bookings
   require a *paid* linked Sales Invoice before submit — unless the booking bills
   nothing, in which case there is no invoice and nothing to gate on.
2. TANK OUT gating (``validate`` when direction == 'Tank Out'): every item must
   reference a Container that is clean + ready, with a finished Cleaning Order
   whose ``valid_until`` covers today.
3. Booking Code issuance on submit (one per item). Codes do not expire.
4. Staged billing. A booking starts at ``Draft`` and generates NOTHING, so the operator
   can get it right first. **Generate Invoice** raises the draft Sales Invoice and moves
   it to ``Pending Payment``, where the billing facts are frozen. **Kembali ke Draft
   (batalkan invoice)** is the way back while the invoice is still unpaid; once the
   Cashier submits it, only cancelling the invoice (or the booking) reopens anything. See
   :func:`generate_invoice` / :func:`rollback_to_draft` / ``_guard_locked_charges``.

   Its counterpart on a SUBMITTED booking is **Kembali ke Draft (pembayaran tetap)** —
   same destination, opposite cost: that one undoes the submit and keeps the settled
   invoice, this one undoes the invoice. The two share a name because they share an
   outcome, and are told apart by the qualifier; they never appear together, since each
   exists at only one docstatus. See :func:`revert_booking_to_draft`.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime, today

from container_depot import finance, invoicing, pricing_model
from container_depot.container_depot.doctype.booking_code.booking_code import (
	generate_code,
)
from container_depot.container_depot.doctype.depot_contract.depot_contract import (
	get_active_contract,
)
from container_depot.container_depot.container_activity import log_container_activity
from container_depot.container_depot.container_status import GATE_OUT, assert_rows_active
from container_depot.state_machine import stage_for_status


CONTAINER_READY_STATUSES = {"Available"}

# container_summary is a Data field (140 chars). Keep whole container numbers and
# append a "(+N)" marker rather than clipping one mid-number.
_SUMMARY_MAXLEN = 140


def build_container_summary(container_nos) -> str:
	"""Join container numbers into the list-view summary, truncating with a ``(+N)``
	remainder marker so a long booking never exceeds the Data field length. Shared by
	the doctype's validate hook and the backfill patch so both format identically."""
	nums = [n for n in (container_nos or []) if n]
	summary = ", ".join(nums)
	if len(summary) <= _SUMMARY_MAXLEN:
		return summary
	# Reserve room for the trailing " (+N)" marker (12 chars covers up to "(+9999)").
	budget = _SUMMARY_MAXLEN - 12
	out = []
	for n in nums:
		if len(", ".join(out + [n])) > budget:
			break
		out.append(n)
	return ", ".join(out) + " (+{0})".format(len(nums) - len(out))

# Depot Service Menu that scopes the booking's charge picker — the same mechanism M&R /
# Cleaning / Survey use, so *which* items a booking may bill is decided by an operator in
# Desk instead of being buried in code. An empty / inactive menu does not filter: the
# picker then offers everything priced in the customer's list.
BOOKING_MENU = "Booking"


def _billing_signature(doc) -> tuple:
	"""Everything about a booking that a raised Sales Invoice depends on: the party, the
	currency and each charge line. Compared before / after an edit to decide whether a
	raised invoice would be left stale (see ``ContainerBooking._guard_locked_charges``)."""
	return (
		doc.get("customer"),
		doc.get("currency"),
		tuple(
			(r.item, flt(r.qty), flt(r.rate))
			for r in (doc.get("charges") or [])
			if r.item
		),
	)


def status_tag_for_condition(condition: str | None) -> str:
	"""Clean/Dirty gate tag carried onto a Booking Code, derived from a line's
	``condition``: EMPTY CLEAN → ``Clean``; anything else (EMPTY DIRTY / LADEN / unset)
	→ ``Dirty``. A pure function — the tag is computed at booking-code issuance, not
	stored on the line (the line only keeps ``condition``)."""
	return "Clean" if condition == "EMPTY CLEAN" else "Dirty"


class ContainerBooking(Document):
	# ---- naming ---------------------------------------------------------
	def autoname(self):
		# Direction is the operator's pick (doctype default Tank In) and is set_only_once,
		# so the BKG-IN / BKG-OUT prefix chosen here can never drift from it later.
		prefix = "BKG-IN-" if self.direction == "Tank In" else "BKG-OUT-"
		self.name = make_autoname(prefix + ".YYYY.-.#####")

	# ---- lifecycle ------------------------------------------------------
	def validate(self):
		if self.docstatus == 0 and self.booking_status == "Cancelled":
			# A voided draft (see ``void_draft``) is terminal — never re-price or
			# re-reserve it, so a re-save can't resurrect its rolled-back invoice / tanks.
			return
		self._require_containers()
		self._ensure_depot()
		self._ensure_branch_and_principal()
		self._validate_depot_in_branch()
		self._sync_lift_type()
		self._resolve_pricing_context()
		self._resolve_containers()
		# After resolution, so a row that arrived as a bare number is judged on the master it
		# resolved to. Rows already on the booking are untouched — see assert_rows_active.
		assert_rows_active(self, "items")
		self._default_row_shipper()
		self._validate_row_principal()
		self._validate_unique_containers()
		self._sync_container_summary()
		self._guard_locked_charges()
		self._reset_charges_on_customer_change()
		self._price_charges()
		self._sync_payment_type_from_contract()
		# Readiness is enforced at SUBMIT (see before_submit), not here — an outbound
		# booking may be saved as a draft while its container's EIR/Cleaning/M&R finish.

	def after_insert(self):
		# Notify Commercial / admin / Cashier that a new booking (and, for Cash, a
		# payment to collect) exists — shows in the PWA + Desk bell.
		from container_depot.container_depot.notify import notify_booking_created
		notify_booking_created(self)

	def before_save(self):
		# No invoice is created here. A booking stays at Draft carrying nothing until the
		# operator presses Generate Invoice (see :func:`generate_invoice`), so a half-filled
		# booking never reaches the Cashier's queue.
		self._sync_payment_status_from_invoice()

	def before_submit(self):
		if self.booking_status == "Cancelled":
			frappe.throw(_("This booking was cancelled and cannot be confirmed. Create a new one."))
		self._enforce_payment_rules()
		self._validate_no_open_booking()
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
				from container_depot.container_depot.position_survey import provision_position_survey_for_booking
				provision_position_survey_for_booking(self.name)
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"provision position survey for {self.name}")
		from container_depot.container_depot.notify import notify_booking_submitted
		notify_booking_submitted(self)

	# ---- revision in place (docstatus stays 1, status stays Confirmed) --------
	# Correcting a Confirmed booking used to mean Kembali ke Draft, and that door is now shut
	# once a bon exists. This is the way in that does not move the booking backwards: the
	# fields below are `allow_on_submit`, so Frappe saves them on a submitted document and
	# routes the save through these two hooks instead of validate/before_save.
	#
	# `before_update_after_submit` runs BEFORE the row is written — guards and anything that
	# mutates the document belong here, because nothing assigned in the post-save hook would
	# be persisted. `on_update_after_submit` runs after, and is where the side effects go
	# (issuing a code for a new row, voiding one for a dropped row, re-raising the invoice).

	def before_update_after_submit(self):
		self._guard_rows_already_on_a_bon()
		self._guard_billing_on_revision()
		# Same derivations validate() does for a draft, minus the ones keyed on fields a
		# revision cannot reach (direction / lift_type are set_only_once or read-only).
		self._require_containers()
		self._ensure_depot()
		self._ensure_branch_and_principal()
		self._validate_depot_in_branch()
		self._resolve_pricing_context()
		self._resolve_containers()
		assert_rows_active(self, "items")
		self._default_row_shipper()
		self._validate_row_principal()
		self._validate_unique_containers()
		self._price_charges()
		self._sync_container_summary()
		# Stash what the post-save hook needs; `get_doc_before_save()` is the only view of
		# the pre-edit document, and rows dropped from `items` are gone by then.
		before = self.get_doc_before_save()
		kept = {row.name for row in (self.items or [])}
		self.flags.revision_dropped_codes = [
			code
			for code in (
				self._row_code(row)
				for row in ((before.items if before else None) or [])
				if row.name not in kept
			)
			if code
		]
		self.flags.revision_rebilled = bool(
			before and _billing_signature(before) != _billing_signature(self)
		)

	def on_update_after_submit(self):
		# A row added by the revision has no Booking Code yet — issue it, exactly as
		# on_submit does for the original rows (the helper skips rows that already have one).
		self._issue_booking_codes()
		# A row dropped by the revision takes its code out of circulation. Void rather than
		# delete: the code may already have been quoted to the customer, and a cancelled
		# code answers "why was this refused at the gate?" where a missing row cannot.
		for code in self.flags.get("revision_dropped_codes") or []:
			if frappe.db.exists("Booking Code", code):
				frappe.db.set_value("Booking Code", code, "state", "Cancelled", update_modified=False)
		if self.flags.get("revision_rebilled"):
			self._rebill_after_revision()

	# Fields of a container row a revision may change. `container_no` and `booking_code` are
	# system-written and stay read-only in every state.
	REVISABLE_ITEM_FIELDS = (
		"container", "condition", "cargo", "shipper",
		"truck_plate", "driver", "driver_phone", "ro", "tanggal_bongkar", "remarks",
	)

	def _row_code(self, row):
		"""The Booking Code a container row belongs to.

		Normally the stored link, written by :meth:`_issue_booking_codes`. Falls back to a
		lookup by container number, because the guards below are a safety property and must
		not quietly pass on a row whose link was never written — a booking whose codes were
		issued by some other path would otherwise look unprotected.
		"""
		if row.booking_code:
			return row.booking_code
		if not row.container_no:
			return None
		return frappe.db.get_value(
			"Booking Code", {"booking": self.name, "container_no": row.container_no}, "name"
		)

	def _guard_rows_already_on_a_bon(self):
		"""A container that has been put on a bon is finished as far as this booking goes.

		The bon is printed paper carrying that container's truck, driver and dates; letting
		the booking row drift away from it would leave two documents describing one tank and
		no way to tell which one the gate should believe. Rows NOT yet on a bon stay fully
		editable, and rows may still be added — that is the whole point of revising in place.
		"""
		before = self.get_doc_before_save()
		if not before:
			return
		frozen = _codes_on_a_bon(self.name)
		if not frozen:
			return
		current = {row.name: row for row in (self.items or [])}
		for row in before.items or []:
			code = self._row_code(row)
			if code not in frozen:
				continue
			label = row.container_no or row.container or code
			now = current.get(row.name)
			if now is None:
				frappe.throw(
					_("Container {0} tidak bisa dihapus: sudah masuk bon (Booking Code {1}).").format(
						label, code
					),
					title=_("Baris Terkunci"),
				)
			# str() both sides: a Date round-trips as `datetime.date` from the DB and as
			# "YYYY-MM-DD" from the client, and an empty field arrives as None or "".
			changed = [
				field
				for field in self.REVISABLE_ITEM_FIELDS
				if str(now.get(field) or "") != str(row.get(field) or "")
			]
			if changed:
				frappe.throw(
					_(
						"Container {0} tidak bisa direvisi: sudah masuk bon (Booking Code {1}). "
						"Field yang diubah: {2}. Perbaikan datanya dilakukan lewat bon."
					).format(label, code, ", ".join(changed)),
					title=_("Baris Terkunci"),
				)

	def _guard_billing_on_revision(self):
		"""Billing facts may move during a revision only while nothing is in the ledger.

		The three cases, and why they differ:

		* **Submitted invoice** — refused. The numbers are booked; a booking that quietly
		  disagrees with a submitted invoice is the exact drift this whole lock exists to
		  prevent. Cancel the invoice (or issue a credit note) first.
		* **Draft invoice** — allowed, and the invoice is re-raised afterwards
		  (:meth:`_rebill_after_revision`) so the Cashier is never handed a document that
		  disagrees with the booking it came from.
		* **No invoice** — allowed. A TOP booking is billed later by
		  ``consolidated_billing.bill_customer``, which reads the booking at run time and so
		  picks the revision up on its own.

		Contrast :meth:`_guard_locked_charges`, which polices the same facts on a DRAFT
		booking and simply refuses: there, "Kembali ke Draft (batalkan invoice)" is the way
		through, and that button does not exist on a submitted one.
		"""
		before = self.get_doc_before_save()
		if not before or _billing_signature(before) == _billing_signature(self):
			return
		if (
			self.sales_invoice
			and frappe.db.get_value("Sales Invoice", self.sales_invoice, "docstatus") == 1
		):
			frappe.throw(
				_(
					"Sales Invoice {0} sudah disubmit — charges / customer booking ini tidak bisa "
					"direvisi. Batalkan invoice-nya dulu (atau terbitkan credit note)."
				).format(self.sales_invoice),
				title=_("Invoice Sudah Disubmit"),
			)

	def _rebill_after_revision(self):
		"""Charges moved on a Confirmed booking → its DRAFT invoice is stale. Void it and
		raise a fresh one, so the two never disagree.

		A submitted invoice cannot reach this: :meth:`_guard_billing_on_revision` refuses the
		edit that would strand it. A booking with no invoice is left alone — TOP accrues and
		is swept later, and a site with finance switched off never raises one at all."""
		if not self.sales_invoice:
			return
		self._cancel_invoice_keep_link()
		old = self.sales_invoice
		self.db_set("sales_invoice", None, update_modified=False)
		self.sales_invoice = None
		self._auto_invoice()
		frappe.msgprint(
			_("Charges berubah — Sales Invoice {0} dibatalkan dan diganti {1}.").format(
				old, self.sales_invoice or _("(belum ada, akan ditagih lewat billing bulanan)")
			),
			indicator="orange",
			alert=True,
		)

	def before_cancel(self):
		# Before, not on_cancel: on_cancel has already voided the codes and reversed the
		# payment by the time it runs, so a throw there would leave the unwinding half done.
		_block_if_bon_raised(self.name, _("dibatalkan"))

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

	def _sync_lift_type(self):
		"""``lift_type`` is the crane-side reading of ``direction``, nothing more:

		* Tank In  → Lift Off (tank lifted OFF the truck / dropped at the depot)
		* Tank Out → Lift On  (tank lifted ON to the truck / taken from the depot)

		``direction`` is now the operator's pick — it used to be *derived* from a single
		``lift_item``, which stopped working once a booking could carry several priced
		services (or none). ``direction`` remains the in/out flag the whole pipeline keys
		off: naming, Tank Out gating, Order Bongkar vs Order Muat, EIR, booking codes,
		survey. ``lift_type`` is kept hidden + derived so existing reports and the
		consolidated-billing description keep reading."""
		self.lift_type = "Lift On" if self.direction == "Tank Out" else "Lift Off"

	def _require_containers(self):
		"""A booking must carry at least one container line.

		Enforced HERE rather than by marking the field ``reqd``, which is what it used to
		be: Frappe opens every new document with a blank row in each mandatory table
		(``create_mandatory_children``), so the grid greeted the operator with a half-
		started line before they had picked anything. The Charges grid starts empty and
		reads better for it, so Containers now does too — the rule is the same, it is just
		checked at save instead of pre-filled on screen.
		"""
		if not (self.items or []):
			frappe.throw(_("Isi minimal satu container."), title=_("Container Kosong"))

	def _ensure_depot(self):
		"""Which depot this booking happens at.

		**Tank Out never asks.** The tank is already sitting somewhere, and the master
		says where — so the depot is DERIVED from the rows (the form hides the field for
		an outbound booking) and overwrites whatever was there. Anything else lets an
		operator name a depot the tank is not in.

		**Tank In** is the operator's pick (the tank has not arrived yet, so no master can
		answer): mandatory on the Desk form. Programmatic callers (tests / data patches /
		future portal) that omit it fall back to the primary active depot so every booking
		still carries one rather than failing the mandatory check.
		"""
		self.flags.depot_from_containers = False
		if self.direction == "Tank Out":
			derived = self._depot_from_containers()
			if derived:
				self.depot = derived
				self.flags.depot_from_containers = True
				return
			# No row names a depot yet (empty draft, or a legacy tank whose master was
			# never stamped with one) — fall through to the same fallback Tank In uses.
		if self.depot:
			return
		# Inside the booking's own Branch first: a fallback that lands in another branch
		# would only have to be corrected by hand (and, on a Tank Out, would look like a
		# derived answer it is not).
		depot = (
			(
				frappe.db.get_value("Depot", {"is_active": 1, "branch": self.branch}, "name")
				if self.branch
				else None
			)
			or frappe.db.get_value("Depot", {"is_active": 1}, "name")
			or frappe.db.get_value("Depot", {}, "name")
		)
		if depot:
			self.depot = depot

	def _depot_from_containers(self):
		"""The one depot the booking's tanks are currently in, or None when no row names
		one (blank draft, or a legacy master with an empty ``depot``).

		``Container.depot`` is stamped at gate-in from the inbound booking's depot
		(``order_bongkar._sync_container_arrival``), so a tank that came in through the
		normal flow always knows where it is.

		Rows spanning TWO depots are refused: one booking issues one set of booking codes
		for one gate, so tanks from different depots cannot ride on it — they are two
		bookings.
		"""
		depots: dict[str, list[str]] = {}
		for item in self.items or []:
			name = item.get("container") or (
				frappe.db.get_value("Container", {"container_no": item.container_no.strip().upper()})
				if item.container_no
				else None
			)
			if not name:
				continue
			depot = frappe.db.get_value("Container", name, "depot")
			if depot:
				depots.setdefault(depot, []).append(item.container_no or name)
		if len(depots) > 1:
			frappe.throw(
				_("Container-nya ada di depo yang berbeda — satu booking hanya untuk satu depo:")
				+ "<br>"
				+ "<br>".join(f"<b>{d}</b>: {', '.join(nos)}" for d, nos in depots.items()),
				title=_("Beda Depo"),
			)
		return next(iter(depots), None)

	def _validate_depot_in_branch(self):
		"""Tank Out: the derived depot must sit in the booking's Branch.

		The depot comes off the container, the branch is the operator's pick — when they
		disagree the tank is simply not in the branch this booking belongs to (only
		reachable through the Excel import / API; the Desk picker is branch-scoped). Said
		plainly rather than silently rewriting Branch, which is what scopes the document
		for every branch-restricted user.
		"""
		# Only a depot the CONTAINERS answered for is judged here. A fallback depot (no
		# row names one yet) says nothing about where the tanks are, so holding the branch
		# against it would refuse a legacy tank for a mismatch it never claimed.
		if not self.flags.get("depot_from_containers"):
			return
		if self.direction != "Tank Out" or not (self.depot and self.branch):
			return
		depot_branch = frappe.db.get_value("Depot", self.depot, "branch")
		if depot_branch and depot_branch != self.branch:
			frappe.throw(
				_(
					"Container-nya ada di depo {0} (Branch {1}), bukan Branch {2} yang dipilih "
					"— ganti Branch booking atau pilih container dari depo Branch ini."
				).format(self.depot, depot_branch, self.branch),
				title=_("Beda Branch"),
			)

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
		automatically (hidden, never picked by hand); its currency (USD / IDR) drives every
		charge line with no exchange-rate conversion. The customer's active contract is also
		resolved (hidden) for the allowed payment modes.

		Neither is *required*: a booking with no charge lines bills nothing, so a walk-in
		with no contract is a legitimate booking rather than something to block."""
		contract = get_active_contract(self.customer) if self.customer else None
		self.contract = contract.name if contract else None
		# The customer's active price list — auto-resolved, not shown or picked. Empty only
		# for a walk-in with no default list (charge rates then stay whatever was typed).
		self.price_list = pricing_model.price_list_for_customer(self.customer) if self.customer else None
		if self.price_list:
			self.currency = frappe.db.get_value("Price List", self.price_list, "currency") or self.currency

	def _reset_charges_on_customer_change(self):
		"""Drop every charge line when the customer changes.

		Each customer has their own rate card, and a rate is *stored* on the line once
		seeded — so carrying the old lines over would bill the previous customer's prices
		under the new one's name. The Desk form clears them client-side; this covers the
		API / import path too."""
		before = self.get_doc_before_save()
		if not before or before.customer == self.customer:
			return
		self.charges = []

	def _price_charges(self):
		"""Fill in and total the booking's charge lines.

		A booking may carry any number of priced services — or none at all, in which case
		nothing is billed and no invoice is created. This replaced the old single
		``lift_item`` + ``lift_rate`` pair, which could only ever express one charge and
		forced every booking to have one.

		Per line: ``item_name`` and ``currency`` are refreshed from the master, ``qty``
		defaults to the number of containers (the lift is billed per container) and ``rate``
		is seeded from the customer's active Price List.

		The seed fires only on a rate that was never SET — ``None``, not ``0``. That
		distinction is what lets a line be free: a typed 0 is a real answer and stays,
		while "no rate given" still picks up the list price. (Testing ``not rate`` instead
		would bounce every deliberate 0 straight back to the list price.) A rate read back
		from the database is always a number, so a saved line — negotiated, zeroed or
		list-priced — is never re-seeded on a later save."""
		total = 0.0
		container_qty = len(self.items or []) or 1
		for row in self.charges or []:
			if not row.item:
				continue
			row.item_name = frappe.db.get_value("Item", row.item, "item_name") or row.item
			row.currency = self.currency
			if not flt(row.qty):
				row.qty = container_qty
			if row.get("rate") is None and self.price_list:
				row.rate = pricing_model.resolve_price(row.item, self.price_list) or 0
			row.amount = flt(row.qty) * flt(row.rate)
			total += flt(row.amount)
		self.charges_total = total

	def _billable_lines(self) -> list[dict]:
		"""The booking's charges as Sales Invoice line dicts — or ``[]`` when the booking
		is worth nothing.

		"Worth nothing" covers BOTH shapes: no charge rows at all, and rows that total
		zero (a free service, or one the price list does not price). Neither is billed —
		raising a zero-value invoice would just hand the Cashier something to collect that
		nobody owes. The single source of truth for every invoicing path (create, draft
		re-sync, submit-time auto-invoice, regenerate) and for the payment gate, so they
		cannot disagree about whether this booking bills.

		Individual zero-rate rows inside an otherwise paid booking ARE kept — a free line
		belongs on the invoice next to the paid ones."""
		if flt(self.charges_total) <= 0:
			return []
		lines = []
		for row in self.charges or []:
			if not row.item:
				continue
			lines.append({
				"item_code": row.item,
				"description": f"{row.item_name or row.item} · {self.name or _('Booking')} ({self.direction})",
				"qty": flt(row.qty) or 1,
				"rate": flt(row.rate),
			})
		return lines

	# ---- container resolution (single-input model) ----------------------
	def _validate_row_principal(self):
		"""Every container on the booking must belong to its Principal (Tank Owner).

		The Principal is not decoration: it is who owns the tank, it scopes the Desk
		picker, and it is stamped onto a master that has none. Nothing enforced it on the
		rows themselves, so a file imported under the wrong owner — or a row pasted /
		posted past the picker — booked another principal's tanks and submitted cleanly,
		leaving the master data saying two different things about who owns them.

		Only a container whose master already NAMES a different owner is refused. A blank
		one is not a conflict: ``_stamp_principal`` has just filled it in with this
		booking's Principal, which is how a tank that reached the master ownerless gets
		adopted.

		Runs after ``_resolve_containers`` so every row has a real Container to ask.
		"""
		if not self.principal:
			return
		wrong = []
		for item in self.items or []:
			if not item.container:
				continue
			owner = frappe.db.get_value("Container", item.container, "principal")
			if owner and owner != self.principal:
				wrong.append((item.container_no or item.container, owner))
		if not wrong:
			return
		frappe.throw(
			_("Container berikut bukan milik Principal <b>{0}</b>:").format(self.principal)
			+ "<br>"
			+ "<br>".join(f"<b>{no}</b> — milik {owner}" for no, owner in wrong)
			+ "<br><br>"
			+ _("Ganti Principal booking atau keluarkan baris itu."),
			title=_("Beda Principal"),
		)

	def _validate_unique_containers(self):
		"""One line per container. Booking the same tank twice would bill the lift
		twice and issue two Booking Codes for it, so the gate would show a phantom
		second container to move.

		Runs after ``_resolve_containers`` so every row already carries a normalised
		(stripped, upper-cased) ``container_no`` — comparing raw input would let
		"tclu1234567" slip past "TCLU1234567".
		"""
		seen = {}
		for row in self.items or []:
			key = row.container_no or row.container
			if not key:
				continue  # blank row — allowed on a draft, containers are enforced at submit
			if key in seen:
				frappe.throw(
					_("Container {0} is already on row {1} — each container may appear only once.").format(
						key, seen[key]
					),
					title=_("Duplicate Container"),
				)
			seen[key] = row.idx

	def _sync_container_summary(self):
		"""Denormalise the container numbers onto a single Data field for the Desk list
		view and search (a list column can't render a child table). Runs after
		``_resolve_containers`` so every row already has a ``container_no``."""
		self.container_summary = build_container_summary(
			[i.container_no for i in (self.items or []) if i.container_no]
		)

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

		Each row's ``is_new_container`` is (re)derived here from the Container's own
		``created_by_booking``: after a bulk import the operator has to be able to tell at
		a glance which lines minted a master and which picked an existing tank.
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
			if item.container:
				self._stamp_principal(item.container)
				self._claim_imported_container(item)
				# "Was this tank's master minted by this booking?" — read back off the
				# Container rather than remembered from the branch above, so the flag stays
				# true across re-saves and a revision that repoints the row to an existing
				# tank drops it by itself.
				item.is_new_container = (
					1
					if frappe.db.get_value("Container", item.container, "created_by_booking")
					== self.name
					else 0
				)
			if self.direction == "Tank In" and item.container:
				self._mark_pre_arrival(item.container)

	def _default_row_shipper(self):
		"""Each container line carries its own EMKL / angkutan (``shipper``) — one booking
		may be split across several transporters, and the tank owner (Principal) is often
		not the one who trucks it.

		The booking's ``customer`` (Bill To) is only the DEFAULT: a blank row inherits it
		here, and the form fills the rows the moment Bill To is set or changed. A row the
		operator pointed at a different transporter is never touched — this only ever
		fills a BLANK. Nothing financial reads the field: pricing, contract and the Sales
		Invoice all key off ``customer``."""
		for item in self.items or []:
			if not item.shipper:
				item.shipper = self.customer

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

	def _stamp_principal(self, container):
		"""Fill a container's Principal (Tank Owner) from the booking when the master has
		none.

		A tank announced through a booking belongs to that booking's Principal. A
		pre-arrival phantom is born with it (``_create_pre_arrival_container``), but a
		container that reached the master by some other route — an early import, legacy
		data — can sit there ownerless, and an ownerless tank drops out of every
		principal-scoped list and Excel the depot works from.

		Only ever fills a BLANK. A container already owned by someone else is never
		reassigned by a booking: changing who owns a tank is a master-data decision, and
		silently doing it here would rewrite ownership from a typo'd Principal field.
		``db.set_value`` so this can never trip Container's own status automation.
		"""
		if not self.principal:
			return
		if frappe.db.get_value("Container", container, "principal"):
			return
		frappe.db.set_value("Container", container, "principal", self.principal)

	def _claim_imported_container(self, item):
		"""Adopt a Container master the grid's Excel import registered for this booking.

		The importer has to create the master up front — the row's Container link is
		mandatory, so the Desk refuses to save a row without one, and the tank would never
		reach a booking at all — but at that point this booking has no name to stamp on it
		(see :func:`parse_container_xlsx`). This is where that stamp lands, and with it the
		phantom becomes cleanable: cancelling the booking DELETES a tank it created
		(``_release_pre_arrival_containers``) rather than leaving a record of a tank that
		never arrived.

		Deliberately narrow, because the consequence of a wrong claim is a real tank being
		deleted on cancel. The row's flag alone is not trusted — it comes from the client —
		so the Container must also still look exactly like a just-registered master:
		``Gate_Out`` (never in the yard), never gated in, and claimed by nobody. A tank
		that is actually in the depot fails the first test, and one that really did leave
		fails the second. Runs BEFORE ``_mark_pre_arrival`` for that reason: once that has
		reserved the tank, a pre-existing tank this booking merely flipped is
		indistinguishable from one it created.
		"""
		if not item.get("is_new_container"):
			return
		row = frappe.db.get_value(
			"Container", item.container, ["status", "eir_in_date", "created_by_booking"], as_dict=True
		)
		if not row or row.created_by_booking or row.status != GATE_OUT or row.eir_in_date:
			return
		frappe.db.set_value(
			"Container", item.container, "created_by_booking", self.name, update_modified=False
		)

	def _mark_pre_arrival(self, container):
		"""Flip a never-gated-in container to ``Booked`` without tripping the status
		guard. Containers that have already gated in (``eir_in_date`` set) are left
		untouched, so this never pulls a live tank out of inventory.

		``Gate_Out`` counts as never-arrived here, guarded by that same ``eir_in_date``:
		a master registered by hand on the Container form, or by the grid's Excel import,
		is born there and has never been through a gate. A tank that genuinely left keeps
		its ``eir_in_date`` and is skipped — it comes back in through the gate, not through
		a status flip.
		"""
		row = frappe.db.get_value("Container", container, ["status", "eir_in_date"], as_dict=True)
		if not row or row.eir_in_date or row.status == "Booked":
			return
		if row.status not in (None, "", "Available", GATE_OUT):
			return
		frappe.flags.in_status_automation = True
		try:
			c = frappe.get_doc("Container", container)
			c.status = "Booked"
			# This runs inside the booking's own validate, and the tank may already carry
			# this booking in `created_by_booking` (stamped a moment ago by
			# `_claim_imported_container`) — a row that is not in the DB until the insert
			# right after. Skip link validation for the same reason
			# `_create_pre_arrival_container` does; the only field this save changes is
			# `status`.
			c.flags.ignore_links = True
			c.save(ignore_permissions=True)
		finally:
			frappe.flags.in_status_automation = False

	# ---- portal guards --------------------------------------------------
	# ---- billing --------------------------------------------------------
	def _build_draft_invoice(self):
		"""Raise the booking's draft Sales Invoice from its charges and link it.

		Called ONLY from :func:`generate_invoice` — an invoice is never born on a plain
		save. A booking starts at ``Draft`` carrying nothing, so the operator can get the
		containers and the charges right before anything reaches the Cashier's queue.
		Before this, the invoice appeared on the very first save and every later edit
		rewrote it, so the amount the Cashier was looking at could move under them.

		Returns the invoice name, or None when the site is not invoice-ready (no company)
		— the caller reports that rather than leaving a half-moved booking."""
		lines = self._billable_lines()
		if not lines:
			return None
		return invoicing.create_draft_sales_invoice(
			self.customer,
			lines,
			due_days=30,
			remarks=f"Cash booking for {self.customer} ({self.direction}). Cashier to confirm payment.",
			currency=self.currency,
			selling_price_list=self.price_list,
			branch=self.branch,
		)

	def _guard_locked_charges(self):
		"""Freeze the billing facts — charges, customer, currency — outside ``Draft``.

		``Draft`` is the only state where a booking is still being figured out; it carries
		no invoice, so anything may change. Once **Generate Invoice** has run there is a
		document the Cashier can act on, and the booking must not drift away from it. The
		way back is deliberate, not accidental:

		* invoice still a draft  -> **Kembali ke Draft (batalkan invoice)** (voids the
		  invoice, reopens the booking) — see :func:`rollback_to_draft`.
		* invoice already submitted / paid -> cancel the invoice (and its payments) or the
		  whole booking; the numbers are in the ledger by then.

		Everything that is not a billing fact — containers, DO reference, remarks, EMKL —
		stays editable in every state, because none of it changes what was invoiced."""
		if self.is_new() or self.docstatus != 0:
			return
		if self.booking_status in ("Draft", "Cancelled"):
			return
		before = self.get_doc_before_save()
		if not before or _billing_signature(before) == _billing_signature(self):
			return
		submitted = (
			self.sales_invoice
			and frappe.db.get_value("Sales Invoice", self.sales_invoice, "docstatus") == 1
		)
		if submitted:
			frappe.throw(
				_(
					"Sales Invoice {0} sudah disubmit — charges / customer booking ini tidak bisa "
					"diubah lagi. Batalkan invoice-nya dulu, atau batalkan booking ini dan buat "
					"yang baru."
				).format(self.sales_invoice),
				title=_("Invoice Sudah Disubmit"),
			)
		frappe.throw(
			_(
				"Invoice untuk booking ini sudah dibuat. Tekan <b>Kembali ke Draft "
				"(batalkan invoice)</b> dulu kalau mau mengubah charges atau customer."
			),
			title=_("Booking Terkunci"),
		)

	def _auto_invoice(self):
		"""Best-effort transactional invoice for a booking that has none yet.

		Skipped for TOP (postpaid): those accrue Unpaid and are billed later via
		``consolidated_billing.bill_customer``. Cash already carries its draft/paid
		invoice, and a booking with no charges is never invoiced at all."""
		if self.payment_type == "TOP":
			return
		if self.sales_invoice:
			return
		lines = self._billable_lines()
		if not lines:
			return
		try:
			si = invoicing.create_draft_sales_invoice(
				self.customer,
				lines,
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
		"""TANK OUT submit gate: every container must be present with no OPEN order left.

		The rule is the absence of unfinished work, not the presence of finished work — a
		tank that needed no cleaning has no cleaning to wait for. A draft may always be
		saved (so the booking can be prepared while the yard finishes up); only the submit
		is blocked, and it names the exact orders standing in the way.
		"""
		failures: list[str] = []
		# Submit-only hard requirement: a Tank Out must reference a real, existing tank
		# (unlike Tank In, it never auto-creates one).
		for item in self.items or []:
			if not item.container:
				failures.append(
					_("Item for {0}: container link required for Tank Out.").format(
						item.container_no or "(no number)"
					)
				)
			elif not frappe.db.exists("Container", item.container):
				failures.append(_("Container {0} not found.").format(item.container))
		# Status readiness — shared with the draft warning so the two never disagree.
		for m in _find_status_mismatches(
			"Tank Out", [(i.container, i.container_no) for i in (self.items or [])]
		):
			failures.append(_describe_out_block(m))

		if failures:
			frappe.throw("<br><br>".join(failures), title=_("Container Belum Siap Keluar"))

	def _validate_no_open_booking(self):
		"""SUBMIT gate: a container must not already be spoken for by another booking.

		The status gates alone never caught this. A Tank In tank sits at ``Booked`` — which
		is not in ``PRESENT`` — and a Tank Out booking does not move the tank off
		``Available``, so in both directions a second booking submitted cleanly and the
		gate ended up holding two live codes for the same tank.

		A Booking Code is the right signal: it is issued at submit and consumed
		(``Used``) the moment the container is placed on a bon, so a still-``Active`` code
		means exactly "confirmed, no bon yet". Once the bon exists the tank is in motion
		and the next cycle's booking is legitimate, so ``Used`` codes never block.
		Cancelling a booking voids its codes, so a cancelled booking never blocks either.

		Cross-document, unlike ``_validate_unique_containers``, which only dedups the rows
		of THIS form.
		"""
		conflicts = _find_booking_conflicts(
			self.name, [(i.container, i.container_no) for i in (self.items or [])]
		)
		if conflicts:
			failures = [
				_(
					"Container {0} masih terikat booking {1} ({2}) yang belum dibuatkan bon — "
					"batalkan booking itu dulu atau terbitkan bon-nya."
				).format(c["container_no"], c["booking"], c["direction"] or "-")
				for c in conflicts
			]
			frappe.throw("<br>".join(failures), title=_("Container Sudah Dibooking"))

	def _validate_in_not_present(self):
		"""TANK IN submit gate: a container must NOT already be physically in a depot —
		import only a tank that is not currently present (In_Depot / Available).

		Shares ``_find_status_mismatches`` with the draft warning; a brand-new pre-arrival
		tank has no master yet, so it is skipped there and created fresh on save."""
		failures = [
			_(
				"Container {0} masih ada di depo (status {1}) — tidak bisa dibuat booking masuk."
			).format(m["container_no"], m["status"])
			for m in _find_status_mismatches(
				"Tank In", [(i.container, i.container_no) for i in (self.items or [])]
			)
		]
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
		# With finance off no invoice is ever raised, so waiting for one to be paid would
		# park every Cash booking in Pending Payment permanently — the depot could not
		# confirm a single booking. The charges stay on the record either way.
		if not finance.is_enabled():
			return
		# A booking that bills nothing has nothing to collect — the Cash gate would
		# otherwise park a free booking in Pending Payment forever, waiting on an invoice
		# that is deliberately never raised.
		if not self._billable_lines():
			return
		# self.payment_type is the booking's effective mode (synced from the contract in
		# validate; a Both contract leaves the operator's Cash/TOP choice intact).
		payment_type = self.payment_type or "Cash"
		if payment_type == "TOP":
			return  # accrual: free submit, billed later via consolidated billing
		# Cash, or walk-in without a contract
		self._enforce_cash_paid_invoice()

	def _enforce_cash_paid_invoice(self):
		if not self.sales_invoice:
			# No invoice yet: the booking is still a Draft that was never taken through
			# Generate Invoice. That is a missing step, not a payment being waited on, so
			# say which button to press instead of parking it in Pending Payment (which now
			# means "invoice raised") and leaving the operator to guess.
			frappe.throw(
				_("Booking Cash ini belum dibuatkan invoice — tekan <b>Generate Invoice</b> dulu."),
				title=_("Invoice Belum Dibuat"),
			)
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
def booking_container_query(doctype, txt, searchfield, start, page_len, filters):
	"""Options for a booking line's Container — the picker the operator actually works
	from, narrowed by the DIRECTION so an unusable tank is never offered in the first
	place.

	Both directions: the tank must be in the fleet (``is_active``) and owned by the
	booking's Principal (Tank Owner) when one is set.

	**Tank Out** additionally offers only tanks that are physically here — status in
	``PRESENT`` (In_Depot / Available) — and only those in a depot of the booking's
	Branch. A tank that already left, or one sitting in another branch's yard, cannot be
	lifted out of this depot; it used to be pickable and only bounced at submit, which is
	the worst moment to find out. Open work (cleaning / repair / periodic test) is NOT
	filtered here: those tanks are legitimately being prepared for this very booking, the
	draft warning names the orders, and ``_validate_out_ready`` blocks the submit.

	**Tank In** is left open: an inbound tank is by definition not in the depot, and a
	number the master does not know yet is registered on save.
	"""
	from container_depot.container_depot.container_status import PRESENT

	filters = filters or {}
	direction = filters.get("direction") or "Tank In"
	principal = filters.get("principal")
	branch = filters.get("branch")

	cond = {"is_active": 1}
	if principal:
		cond["principal"] = principal
	# Container is named by its number (autoname field:container_no), so one LIKE on the
	# name covers the search box — which leaves `or_filters` free for the depot group.
	txt = (txt or "").strip()
	if txt and txt.lower() != "undefined":
		cond["name"] = ["like", f"%{txt}%"]
	or_filters = None
	if direction == "Tank Out":
		cond["status"] = ["in", list(PRESENT)]
		if branch:
			depots = frappe.get_all("Depot", filters={"branch": branch}, pluck="name")
			# A tank whose master carries no depot at all (legacy / imported data) is still
			# offered — refusing it would hide real tanks the depot is holding.
			or_filters = [["depot", "in", depots or [""]], ["depot", "is", "not set"]]
	return frappe.get_all(
		"Container",
		filters=cond,
		or_filters=or_filters,
		fields=["name", "status", "depot"],
		order_by="container_no asc",
		limit_start=cint(start),
		limit_page_length=cint(page_len),
		as_list=True,
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def charge_item_query(doctype, txt, searchfield, start, page_len, filters):
	"""Options for a booking charge line: the Depot Service Menu "Booking" ∩ the items
	priced in the customer's *active* Price List.

	Same two-step narrowing the M&R / Periodic Test pickers use, so *which* services a
	booking may bill is maintained by an operator in Desk rather than pinned to one Item
	Group in code.

	**No customer / no price list -> no options.** One booking must never mix rate cards, so
	the picker stays empty until a customer is chosen (the form also clears the charge rows
	when the customer changes). The menu narrowing does fall back open — a menu that is
	missing, inactive or empty simply applies no group filter — so a half-configured site is
	still workable.
	"""
	from container_depot.container_depot.service_menu import filter_items_by_menu, is_real_menu

	customer = (filters or {}).get("customer")
	price_list = pricing_model.price_list_for_customer(customer) if customer else None
	if not price_list:
		return []
	candidate = frappe.get_all(
		"Item Price",
		filters={"price_list": price_list, "selling": 1},
		pluck="item_code",
		distinct=True,
	)
	if is_real_menu(BOOKING_MENU):
		candidate = filter_items_by_menu(candidate, BOOKING_MENU)
	if not candidate:
		return []

	or_filters = None
	txt = (txt or "").strip()
	if txt and txt.lower() != "undefined":
		or_filters = {"item_code": ["like", f"%{txt}%"], "item_name": ["like", f"%{txt}%"]}
	# Narrowed BEFORE the limit so a page of 20 never comes back short.
	return frappe.get_all(
		"Item",
		filters={"name": ["in", candidate], "disabled": 0},
		or_filters=or_filters,
		fields=["name", "item_name"],
		order_by="item_name asc",
		limit_start=cint(start),
		limit_page_length=cint(page_len),
		as_list=True,
	)


@frappe.whitelist()
def charge_pricing(customer, item):
	"""Rate + currency + name for one charge Item under the customer's *active* Price List.

	The Desk form calls this the moment a Service is picked so the row's Tarif fills in
	immediately instead of only after a save. It is a starting point only — the rate stays
	editable and is never re-applied once filled (see ``_price_charges``). An item the list
	does not price returns rate 0, which is a valid free line rather than an error."""
	price_list = pricing_model.price_list_for_customer(customer) if customer else None
	return {
		"rate": (pricing_model.resolve_price(item, price_list) or 0) if (price_list and item) else 0,
		"currency": frappe.db.get_value("Price List", price_list, "currency") if price_list else None,
		"item_name": frappe.db.get_value("Item", item, "item_name") if item else None,
	}


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
def generate_invoice(booking):
	"""Draft -> Pending Payment: raise the booking's Sales Invoice, then lock the billing.

	The deliberate step between "still figuring it out" and "the Cashier can collect this".
	A booking generates nothing until this runs, so the operator can fix containers, rates
	and the customer freely first; afterwards ``_guard_locked_charges`` freezes exactly
	those facts so the amount the Cashier sees cannot move under them.

	Refused unless the booking is an editable Draft that actually bills something. TOP is
	postpaid and carries no per-booking invoice at all — it is swept later by consolidated
	billing — so it is refused here too."""
	frappe.has_permission("Container Booking", ptype="write", throw=True)
	finance.require_enabled(_("Generate Invoice"))
	doc = frappe.get_doc("Container Booking", booking)
	if doc.docstatus != 0 or doc.booking_status != "Draft":
		frappe.throw(_("Hanya booking berstatus Draft yang bisa dibuatkan invoice."))
	if doc.sales_invoice:
		frappe.throw(_("Booking ini sudah punya Sales Invoice {0}.").format(doc.sales_invoice))
	if (doc.payment_type or "Cash") != "Cash":
		frappe.throw(
			_("Booking TOP tidak dibuatkan invoice per-booking — ditagih belakangan lewat consolidated billing.")
		)
	if not doc._billable_lines():
		frappe.throw(_("Booking ini tidak menagihkan apa pun (Total Charges 0) — tidak ada yang di-invoice."))

	si = doc._build_draft_invoice()
	if not si:
		frappe.throw(_("Sales Invoice gagal dibuat (apakah site sudah siap untuk invoicing?)."))
	# db_set: the booking itself is unchanged, only its billing state moves. Re-running
	# validate here would re-price charges that are about to be frozen.
	doc.db_set("sales_invoice", si, update_modified=False)
	doc.db_set("payment_status", "Unpaid", update_modified=False)
	doc.db_set("booking_status", "Pending Payment", update_modified=False)
	return {"sales_invoice": si, "booking_status": "Pending Payment"}


@frappe.whitelist()
def rollback_to_draft(booking):
	"""Pending Payment -> Draft: void the booking's draft invoice and reopen it for editing.

	The form button is **Kembali ke Draft (batalkan invoice)**. The function keeps its own
	name — it is a whitelisted endpoint others may call — so the label is recorded here
	rather than guessed from it.

	The undo for :func:`generate_invoice`, and the ONLY way to change charges once an
	invoice exists. Allowed strictly while nothing has settled:

	* the Sales Invoice must still be a **draft** — a submitted one has hit the ledger, so
	  it must be cancelled through the accounting side (which reverses its Payment Entries)
	  before the booking can move;
	* the booking must still be an unsubmitted draft.

	The invoice is marked Cancelled in place (docstatus 2, no ledger impact) and unlinked,
	so the next Generate Invoice raises a fresh one rather than resurrecting a stale
	document. The cancelled invoice stays in the system for audit."""
	frappe.has_permission("Container Booking", ptype="write", throw=True)
	doc = frappe.get_doc("Container Booking", booking)
	if doc.docstatus != 0:
		frappe.throw(_("Hanya booking yang belum disubmit yang bisa dikembalikan ke Draft."))
	if doc.booking_status in ("Draft", "Cancelled"):
		frappe.throw(_("Booking ini sudah berstatus {0}.").format(doc.booking_status))

	si = doc.sales_invoice
	if si and frappe.db.exists("Sales Invoice", si):
		row = frappe.db.get_value("Sales Invoice", si, ["docstatus", "status"], as_dict=True)
		if row.docstatus == 1:
			frappe.throw(
				_(
					"Sales Invoice {0} sudah disubmit ({1}) — batalkan invoice-nya dulu "
					"(pembayarannya ikut dibalik) sebelum booking bisa kembali ke Draft."
				).format(si, row.status),
				title=_("Invoice Sudah Disubmit"),
			)
		if row.docstatus == 0:
			frappe.db.set_value(
				"Sales Invoice", si, {"docstatus": 2, "status": "Cancelled"}, update_modified=False
			)
	doc.db_set("sales_invoice", None, update_modified=False)
	doc.db_set("payment_status", "Unpaid", update_modified=False)
	doc.db_set("booking_status", "Draft", update_modified=False)
	return {"booking_status": "Draft", "cancelled_invoice": si}


# --- "a bon was raised" — the point of no return ----------------------------------
# Once a bon exists, the booking is frozen: it can no longer be reverted to a draft or
# cancelled. The bon is a printed document handed to a driver at the gate, and it names
# this booking; reopening the booking for edits, or voiding it, would leave that paper
# pointing at a record that no longer says what it said when it was signed.
BON_DOCTYPES = ("Order Bongkar", "Order Muat")


def _bons_raised(booking: str) -> list[str]:
	"""Every bon ever raised from ``booking``, newest doctype first.

	Deliberately NOT filtered by docstatus. A voided bon (``void_order`` releases its
	Booking Codes back to ``Active``) still happened: it was printed, and the tank may
	already have moved on it. "Was one ever issued?" is the question that decides whether
	this booking is still the operator's to take back, not "is one live right now?".
	"""
	out = []
	for doctype in BON_DOCTYPES:
		out += [
			f"{doctype} {name}"
			for name in frappe.get_all(doctype, filters={"booking": booking}, pluck="name")
		]
	return out


# The bon's container rows live in a different child doctype per direction, but both carry
# `booking_code` — that link is what ties a bon row back to a booking row.
_BON_CONTAINER_TABLES = (
	("Order Bongkar", "Container Booking Item"),
	("Order Muat", "Order Container Item"),
)


def _codes_on_a_bon(booking: str) -> set[str]:
	"""Booking Codes of ``booking`` that already sit on a bon — the rows a revision may not
	touch (see ``ContainerBooking._guard_rows_already_on_a_bon``).

	Read off the bons themselves rather than off ``Booking Code.state``: voiding a bon puts
	its codes back to ``Active``, and the row is still on paper that was printed.
	"""
	out = set()
	for doctype, child in _BON_CONTAINER_TABLES:
		bons = frappe.get_all(doctype, filters={"booking": booking}, pluck="name")
		if not bons:
			continue
		out |= set(
			frappe.get_all(
				child,
				filters={
					"parenttype": doctype,
					"parent": ["in", bons],
					"booking_code": ["is", "set"],
				},
				pluck="booking_code",
			)
		)
	return out


def _block_if_bon_raised(booking: str, action: str) -> None:
	bons = _bons_raised(booking)
	if bons:
		frappe.throw(
			_("Booking ini tidak bisa {0}: bon sudah pernah terbit ({1}).").format(
				action, ", ".join(bons)
			)
			+ " "
			+ _("Perbaikan data setelah bon terbit dilakukan lewat bon-nya, bukan lewat booking.")
		)


@frappe.whitelist()
def revision_state(booking: str) -> dict:
	"""What the form script needs to know before it lets anyone touch a Confirmed booking.

	One round trip for both answers, because both have the same cause and neither is
	derivable from the document on screen — nothing on the booking form links to a bon
	(they are reachable only through the Connections tab):

	``bons``
	    every bon ever raised. Non-empty means the booking is frozen as a whole: no Revert
	    to Draft, no Cancel.
	``locked_containers``
	    the container numbers already carried on a bon. Those rows cannot be edited or
	    removed; every other row, and the rest of the booking, stays revisable in place.
	"""
	frappe.has_permission("Container Booking", "read", doc=booking, throw=True)
	codes = _codes_on_a_bon(booking)
	return {
		"bons": _bons_raised(booking),
		"locked_containers": sorted(
			frappe.get_all(
				"Booking Code", filters={"name": ["in", list(codes)]}, pluck="container_no"
			)
		)
		if codes
		else [],
	}


@frappe.whitelist()
def void_draft(booking):
	"""Void a *draft* Container Booking without deleting it.

	Cancel is the only 'undo' on a draft (a booking is never hard-deleted / discarded):
	it rolls back what the draft spun up — the auto-created Sales Invoice (cancelled but
	kept linked & visible) and the pre-arrival container reservations — sets the booking
	+ payment status to Cancelled, and marks the document itself Cancelled (docstatus 2)
	so it reads 'Cancelled', not 'Draft'. Submit stays the only approve."""
	doc = frappe.get_doc("Container Booking", booking)
	# Same gate the native Cancel would apply — this method exists only because a DRAFT
	# cannot go through submit→cancel, not because the permission stops mattering. Nothing
	# below would catch a caller without it: `get_doc` checks nothing and the writes go out
	# through db_set/db.sql. A read-only Finance account could void a booking, cancel its
	# invoice and release its reservations.
	doc.check_permission("cancel")
	if doc.docstatus != 0:
		frappe.throw(_("Only a draft booking can be cancelled here."))
	# Defence in depth. A draft cannot normally hold a bon — a bon needs a Confirmed
	# booking, and `revert_booking_to_draft` refuses to reopen one that has raised any —
	# so this only fires if some other path put the pair in that state.
	_block_if_bon_raised(doc.name, _("dibatalkan"))
	doc._cancel_invoice_keep_link()
	doc._release_pre_arrival_containers()
	doc.db_set("booking_status", "Cancelled", update_modified=False)
	doc.db_set("payment_status", "Cancelled", update_modified=False)
	# A draft can't go through native submit→cancel, so mark Cancelled (docstatus 2)
	# directly; child rows mirror the parent docstatus.
	frappe.db.set_value("Container Booking", doc.name, "docstatus", 2, update_modified=False)
	frappe.db.sql("UPDATE `tabContainer Booking Item` SET docstatus=2 WHERE parent=%s", doc.name)
	# Cancelled through the button, not native submit->cancel, so the on_cancel
	# doc_event never fires — clear the "Booking baru ..." notification here too.
	from container_depot.container_depot.notify import revoke
	revoke("Container Booking", doc.name)
	return doc.booking_status


@frappe.whitelist()
def revert_booking_to_draft(booking):
	"""Bring a SUBMITTED booking back to an editable draft WITHOUT touching its payment.

	The form button is **Kembali ke Draft (pembayaran tetap)** — the qualifier IS the
	difference from :func:`rollback_to_draft`, which reaches the same Draft by voiding the
	invoice instead. The function keeps its own name for the same reason as that one.

	Use case: a Cash booking was paid (and so auto-confirmed), but a data correction is
	needed before the tank moves. Unlike Cancel — which reverses the Payment Entries and
	cancels the invoice — this keeps the paid Sales Invoice, its Payment Entries and the
	issued Booking Codes intact, and just flips the same record back to a draft so it can be
	edited and Submitted again (payment is already settled, so re-submit re-confirms it).

	Refused on two counts, and they are not the same question:

	* a bon has ever been raised (:func:`_bons_raised`) — paper exists that names this
	  booking, whether or not that bon is still live;
	* a Booking Code has been consumed (state ``Used``) — the tank is in motion at the gate.

	In practice the first implies the second, since ``make_order`` is what consumes a code.
	Both are kept because neither implies the other in the other direction: voiding a bon
	releases its codes back to ``Active`` (so the code check alone would reopen the booking
	the moment the bon was voided), and a code can be marked ``Used`` by hand or by a future
	gate path that raises no bon at all."""
	doc = frappe.get_doc("Container Booking", booking)
	doc.check_permission("cancel")
	if doc.docstatus != 1:
		frappe.throw(_("Hanya booking yang sudah disubmit yang bisa dikembalikan ke draft."))

	_block_if_bon_raised(doc.name, _("dikembalikan ke draft"))

	used = frappe.get_all(
		"Booking Code", filters={"booking": doc.name, "state": "Used"}, pluck="name"
	)
	if used:
		frappe.throw(_(
			"Tidak bisa dikembalikan ke draft: sudah ada container yang diproses di gate "
			"(Booking Code {0})."
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
	own cancel — that path sets ``booking_status`` = Cancelled first, which we skip).

	The dead link is DROPPED, not kept. Frappe runs ``_validate_links`` before ``validate``
	and refuses to save any document that links a cancelled one, so a live booking still
	pointing at its cancelled invoice could not be saved at all — not even to fix a remark
	(``CancelledLinkError``). Unlinking also lets the booking re-bill by itself: a draft
	raises a fresh invoice on the next save, a submitted one via Regenerate Invoice.

	A cancelled booking keeps its cancelled invoice linked for audit — that is
	``_cancel_invoice_keep_link``'s job and it is deliberately skipped here."""
	for name in frappe.get_all("Container Booking", filters={"sales_invoice": doc.name}, pluck="name"):
		row = frappe.db.get_value(
			"Container Booking", name, ["docstatus", "booking_status", "payment_status"], as_dict=True
		)
		if (
			row
			and row.docstatus in (0, 1)
			and row.booking_status != "Cancelled"
			and row.payment_status != "Cancelled"
		):
			frappe.db.set_value(
				"Container Booking",
				name,
				{"sales_invoice": None, "payment_status": "Unpaid"},
				update_modified=False,
			)


@frappe.whitelist()
def regenerate_invoice(booking):
	"""Create a fresh DRAFT Sales Invoice for a confirmed booking whose linked invoice was
	cancelled (or is gone), and re-link it — so the booking can be re-billed without amending
	the dead invoice (which would leave a -1 duplicate the booking never follows). Scoped to
	Container Booking only."""
	frappe.has_permission("Container Booking", ptype="write", throw=True)
	finance.require_enabled(_("Regenerate Invoice"))
	doc = frappe.get_doc("Container Booking", booking)
	if doc.docstatus != 1 or doc.booking_status == "Cancelled":
		frappe.throw(_("Only a confirmed booking can regenerate its invoice."))
	if doc.payment_type == "TOP":
		# Not cosmetic — this is the money guard. A per-booking invoice fills
		# ``sales_invoice``, and consolidated_billing.bill_customer only picks up TOP
		# bookings where that field is EMPTY, so the charge would vanish from the
		# customer's monthly statement without anyone being told. TOP has no legitimate
		# use for this endpoint: a cancelled consolidated invoice already unlinks its
		# sources (_unmark_billed), which is what puts the booking back in the next run.
		frappe.throw(
			_(
				"Booking TOP ditagih lewat invoice bulanan, bukan per booking. "
				"Jalankan penagihan konsolidasi untuk {0} — booking ini otomatis ikut."
			).format(doc.customer)
		)
	cur = doc.sales_invoice
	if cur and frappe.db.exists("Sales Invoice", cur) and frappe.db.get_value("Sales Invoice", cur, "docstatus") != 2:
		frappe.throw(_("Booking still has a live Sales Invoice {0}. Cancel it first.").format(cur))
	lines = doc._billable_lines()
	if not lines:
		frappe.throw(_("Booking ini tidak menagihkan apa pun (Total Charges 0) — tidak ada yang bisa di-invoice."))
	si = invoicing.create_draft_sales_invoice(
		doc.customer,
		lines,
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


# --- Open-booking conflict (submit block + draft early warning) ---------------

def _find_booking_conflicts(exclude_booking, containers) -> list[dict]:
	"""Containers already spoken for by ANOTHER non-cancelled booking, keyed off a
	still-``Active`` Booking Code (issued at submit, consumed -> ``Used`` when the tank
	goes on a bon, voided on cancel — so ``Active`` means "confirmed, no bon yet").

	``containers``: iterable of ``(container, container_no)`` pairs (either may be None).
	Returns ``[{container_no, booking, direction}]``, one entry per (container, booking).

	The single source of truth for both the submit block (``_validate_no_open_booking``)
	and the draft-time early warning (``open_booking_conflicts``), so the warning can
	never disagree with what Submit will actually refuse.
	"""
	out, seen = [], set()
	for container, container_no in containers:
		keys = [k for k in (container, container_no) if k]
		if not keys:
			continue
		rows = frappe.get_all(
			"Booking Code",
			filters={"state": "Active", "booking": ["!=", exclude_booking or ""]},
			or_filters=[["container", "in", keys], ["container_no", "in", keys]],
			fields=["booking", "direction"],
		)
		for r in rows:
			label = container_no or container
			key = (label, r.booking)
			if key in seen:
				continue
			seen.add(key)
			out.append({"container_no": label, "booking": r.booking, "direction": r.direction})
	return out


@frappe.whitelist()
def open_booking_conflicts(booking=None, containers=None) -> list[dict]:
	"""Draft-time early warning for the form: which of the given containers are already
	held by another active booking (see :func:`_find_booking_conflicts`). Purely
	informational — Submit is where it is actually blocked — so it never throws.

	``containers``: JSON (or list) of ``{container, container_no}`` — the grid rows.
	"""
	rows = frappe.parse_json(containers) if isinstance(containers, str) else (containers or [])
	pairs = [(r.get("container"), r.get("container_no")) for r in rows]
	return _find_booking_conflicts(booking, pairs)


def _describe_out_block(mismatch) -> str:
	"""Why one container cannot leave, in the words the operator needs to act on.

	Two different problems wear the same "not ready" label, and the fix for each is
	different: work still open (go finish these orders) versus the tank not being in the
	depot at all (nothing to finish — it is elsewhere). So they are said separately, and
	the open ones are listed by name.
	"""
	open_orders = mismatch.get("open_orders") or []
	if not open_orders:
		return _(
			"Container {0} tidak ada di depo (status {1}) — tidak bisa dibuat booking keluar."
		).format(mismatch["container_no"], mismatch["status"])
	items = "".join(
		"<li>{0} <b>{1}</b> — {2}</li>".format(o["label"], o["name"], o.get("status") or "-")
		for o in open_orders
	)
	return _("Container {0} masih punya order yang belum selesai:").format(
		mismatch["container_no"]
	) + f"<ul>{items}</ul>" + _("Selesaikan order di atas dulu sebelum submit booking keluar.")


def _find_status_mismatches(direction, containers) -> list[dict]:
	"""Containers whose CURRENT master status conflicts with the booking direction —
	the single source of truth for the submit status gates AND the draft early warning,
	so the two can never disagree. Mirrors the physical Lift service:

	* Lift Off / Tank In — the tank must NOT already be in the depot (status not in
	  ``PRESENT``); one that is present cannot be brought in again.
	* Lift On / Tank Out — the tank must be present with NO open order left. Judged from
	  the orders themselves (``container_open_orders``), not from the cached ``Available``
	  status: the status is a derived convenience that only moves when an order's hook
	  fires, so a tank that never needed work could sit at ``In_Depot`` with nothing to
	  finish and be refused forever. Readiness is the absence of open work — never the
	  presence of a completed cleaning.

	Only containers that actually EXIST are judged: a Tank In may name a not-yet-created
	tank (born ``Booked`` on save), which is fine and skipped. ``containers``: iterable of
	``(container, container_no)`` pairs. Returns
	``[{container_no, status, direction, open_orders}]``, where ``open_orders`` lists the
	work still holding a Tank Out back (empty for a Tank In mismatch).
	"""
	from container_depot.container_depot.container_status import PRESENT, container_open_orders

	out = []
	for container, container_no in containers:
		name = container or (
			frappe.db.get_value("Container", {"container_no": container_no}) if container_no else None
		)
		if not name:
			continue
		status = frappe.db.get_value("Container", name, "status")
		if not status:
			continue
		open_orders = []
		if direction == "Tank In":
			bad = status in PRESENT
		else:
			# Not here = cannot leave; here = may leave once nothing is open.
			open_orders = container_open_orders(name) if status in PRESENT else []
			bad = status not in PRESENT or bool(open_orders)
		if bad:
			out.append({
				"container_no": container_no or name,
				"status": status,
				"direction": direction,
				"open_orders": open_orders,
			})
	return out


@frappe.whitelist()
def status_direction_warnings(direction=None, containers=None) -> list[dict]:
	"""Draft-time early warning: containers whose status will be refused for the chosen
	Direction (see :func:`_find_status_mismatches`). Never throws — Submit is where it is
	blocked.

	``direction`` is now the operator's own pick, so the form passes it straight through
	and the warning is correct the instant it changes — no derivation from a lift item any
	more. Defaults to Tank In (the doctype default) when not given.
	"""
	resolved = direction or "Tank In"
	rows = frappe.parse_json(containers) if isinstance(containers, str) else (containers or [])
	pairs = [(r.get("container"), r.get("container_no")) for r in rows]
	return _find_status_mismatches(resolved, pairs)


# --- Container import (Desk grid "Import Excel") ------------------------------

# The Condition column accepts exactly these — mirrors the Container Booking Item
# ``condition`` Select. Kept here so the template + parser share one greppable source.
CONTAINER_CONDITIONS = ("EMPTY CLEAN", "EMPTY DIRTY", "LADEN")


def _write_cargo_sheet(wb, fmts):
	"""Add a "Cargo" worksheet listing the active Cargo master, and return its row count.

	Both downloads carry it: the operator picking a container also has to name what was
	last in it, and typing that free-hand is how the wrong cleaning item gets quoted. The
	template's Last Cargo dropdown points at this sheet's column A.
	"""
	cargos = frappe.get_all(
		"Cargo",
		filters={"is_active": 1},
		fields=["name", "non_stolt_class", "stolt_class"],
		order_by="name asc",
	)
	ws = wb.add_worksheet("Cargo")
	for col, title in enumerate(["Cargo", "Non-Stolt Class", "Stolt Class"]):
		ws.write(0, col, title, fmts["header"])
	ws.set_column(0, 0, 36)
	ws.set_column(1, 2, 20)
	ws.freeze_panes(1, 0)
	for i, c in enumerate(cargos, start=1):
		ws.write_row(i, 0, [c.name, c.non_stolt_class, c.stolt_class])
	ws.autofilter(0, 0, max(len(cargos), 1), 2)
	return len(cargos)


@frappe.whitelist(methods=["GET"])
def download_container_template():
	"""Blank import template for the booking's Containers grid: Container, Condition and
	Last Cargo, with one illustrative row and dropdowns constraining Condition to the
	valid set and Last Cargo to the Cargo master (listed on the second sheet)."""
	from container_depot.xlsx_utils import finish_sheet, new_sheet

	headers = ["Container", "Condition", "Last Cargo"]
	output, wb, ws, fmts = new_sheet("Template", headers, [24, 18, 28])
	ws.write_row(1, 0, ["ABCD1234567", CONTAINER_CONDITIONS[0], ""])
	# Dropdown on the Condition column so the file cannot carry a typo'd condition.
	ws.data_validation(1, 1, 1000, 1, {"validate": "list", "source": list(CONTAINER_CONDITIONS)})
	n_cargo = _write_cargo_sheet(wb, fmts)
	if n_cargo:
		# Range, not an inline list: Excel caps an inline source at 255 characters, and the
		# cargo master is far past that.
		ws.data_validation(
			1, 2, 1000, 2,
			{"validate": "list", "source": f"=Cargo!$A$2:$A${n_cargo + 1}"},
		)
	finish_sheet(output, wb, ws, "container_import_template.xlsx", 1, len(headers) - 1)


@frappe.whitelist(methods=["GET"])
def download_container_master(principal: str | None = None):
	"""Reference list of existing containers under a bold Principal (owner) banner — the
	numbers to put in the template's Container column. Optional ``principal`` scopes it to
	one owner (the form passes its Principal). Retired tanks (``is_active`` off) are left
	out — this is a pick-list, and offering a tank that is out of the fleet only invites a
	booking that will be refused. A Tank In booking may name a container absent here; the
	import registers it."""
	from container_depot.xlsx_utils import finish_sheet, new_sheet

	filters = {"is_active": 1}
	if principal:
		filters["principal"] = principal
	containers = frappe.get_all(
		"Container",
		filters=filters,
		fields=["container_no", "container_type", "size", "status", "last_cargo", "principal"],
		order_by="principal asc, container_no asc",
	)
	grouped = {}
	for c in containers:
		grouped.setdefault(c.principal or _("(no owner)"), []).append(c)

	headers = ["Container", "Type", "Size", "Status", "Last Cargo"]
	output, wb, ws, fmts = new_sheet("Containers", headers, [24, 14, 10, 14, 28])
	row = 1
	for owner in sorted(grouped):
		# Banner spans the full width so the section reads as one band.
		ws.write(row, 0, owner, fmts["group"])
		for col in range(1, len(headers)):
			ws.write(row, col, "", fmts["group"])
		row += 1
		for c in grouped[owner]:
			ws.write_row(row, 0, [c.container_no, c.container_type, c.size, c.status, c.last_cargo])
			row += 1
	# The Cargo master rides along on a second sheet: it is what the template's Last Cargo
	# column has to be spelled from.
	_write_cargo_sheet(wb, fmts)
	finish_sheet(output, wb, ws, "container_master.xlsx", row - 1, len(headers) - 1)


def _create_imported_container(container_no: str, principal: str) -> str:
	"""Register a Container master for a number an inbound file introduced.

	``status`` is left to the doctype's own default — ``Gate_Out``, i.e. stage *Departed*,
	"the master exists but the tank is not in my yard" — so an imported tank is registered
	on exactly the terms the Container form registers one by hand. It is NOT born
	``Booked``: that status means *reserved by a Tank In booking*, and at import time the
	booking is still unsaved and has no name to be reserved by. Saving the booking is what
	makes both true — it claims the master (``_claim_imported_container``) and reserves it
	(``_mark_pre_arrival``) — so an abandoned draft leaves a plain unregistered-tank
	record rather than one that claims a booking nobody can find.
	"""
	doc = frappe.get_doc({
		"doctype": "Container",
		"container_no": container_no,
		"container_type": "ISO Tank",
		"principal": principal,
	})
	doc.insert()
	return doc.name


def _import_block(master, direction, principal, allowed_depots) -> str | None:
	"""Why an imported row may not go on this booking, or None when it may.

	The same tests the Desk picker applies as filters, said as a sentence — an import has
	no picker to narrow, so the file is judged after the fact and the operator is told
	which number failed and why.

	**Ownership is checked in BOTH directions.** A tank the master says belongs to someone
	else is not this booking's to move, inbound or outbound; the booking itself refuses it
	on save (``_validate_row_principal``), and catching it here means the operator gets a
	named, skipped row instead of a wall at save time. A blank owner passes — that tank is
	adopted by this booking's Principal.

	The rest is outbound-only: an inbound tank is by definition not in the depot yet, so
	presence and branch say nothing about it. A blank ``depot`` on the master passes too:
	legacy tanks were never stamped with one (the stamp is written at gate-in), and
	dropping them would hide tanks the depot really is holding.
	"""
	from container_depot.container_depot.container_status import PRESENT

	if principal and master.principal and master.principal != principal:
		return _("{0}: milik principal lain ({1}) — dilewati").format(
			master.name, master.principal
		)
	if direction != "Tank Out":
		return None
	if master.status not in PRESENT:
		return _("{0}: tidak ada di depo (status {1}) — dilewati").format(
			master.name, master.status or "-"
		)
	if allowed_depots and master.depot and master.depot not in allowed_depots:
		return _("{0}: ada di depo {1}, di luar Branch booking — dilewati").format(
			master.name, master.depot
		)
	return None


@frappe.whitelist()
def parse_container_xlsx(
	file_url: str,
	direction: str | None = None,
	principal: str | None = None,
	branch: str | None = None,
) -> dict:
	"""Parse an uploaded .xlsx into container rows for the booking grid's "Import Excel".

	Columns by position: Container, Condition, Last Cargo. A header row whose first cell is
	container / kontainer is skipped. Pure read — it resolves an existing Container master
	to its link when present (so the grid shows it at once) but never creates one, so it is
	safe on an unsaved form; a Tank In booking's new tanks are born on save. Duplicate
	container numbers within the file are collapsed. An unknown condition is reported in
	``errors`` and the row skipped; a blank condition defaults to EMPTY CLEAN.

	Last Cargo is optional and matched case-insensitively against the Cargo master; a name
	that matches nothing is reported in ``errors`` but does NOT drop the row — the cargo is
	simply left blank for the operator to pick, which beats losing the container. When the
	column is blank and the Container master already knows a last cargo, that one is used.

	A container number the master does not know is handled by ``direction`` — the booking's
	own, passed in by the form:

	* **Tank In** — REGISTERED here and now (:func:`_create_imported_container`), owned by
	  the booking's ``principal`` and left at the Container default ``Gate_Out`` (outside
	  the depot), and the row comes back flagged ``is_new``. A tank arriving for the first
	  time HAS no master yet; that is the normal case for an inbound notice, and refusing
	  it would mean hand-registering twenty tanks before the file can be imported. It is
	  created at import rather than left for save because the row's Container link is
	  MANDATORY: the Desk's own client-side check refuses to save a grid row without one,
	  so a row carrying just a number could never be saved, submitted, or gated. Every
	  number created is named back in ``created`` so a typo that just minted a master is
	  caught while it is still one click from deletion.
	* **Tank Out** (and an unknown direction) — SKIPPED and listed in ``unknown``. A tank
	  that was never in the depot cannot leave it, so an unrecognised number there is a
	  typo, not a new tank.

	A number the master DOES know is checked the same way the Desk picker narrows itself
	(see :func:`booking_container_query` and :func:`_import_block`): it must be owned by
	the booking's Principal — in BOTH directions — and, for a Tank Out, be physically
	present (In_Depot / Available) in a depot of the booking's ``branch``. A file is the
	one way into the grid that bypasses that picker, so without this a booking could be
	filled with another principal's tanks, or with tanks that are already gone, and only
	find out at submit — twenty rows later.

	Returns ``{rows: [{container_no, condition, container, cargo, is_new}], errors: [...],
	unknown: [...], created: [...]}``.
	"""
	from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file

	if not file_url:
		frappe.throw(_("No file provided."))
	raw_rows = read_xlsx_file_from_attached_file(file_url=file_url) or []
	if direction == "Tank In":
		# A Container master cannot exist without an owner, and guessing one is not on the
		# table — the form carries it, so say so once instead of failing row by row.
		if not principal:
			frappe.throw(_("Isi Principal (Tank Owner) dulu sebelum import file Tank In."))
		frappe.has_permission("Container", "create", throw=True)

	# Depots of the booking's branch — the outbound scope check below. Empty when the form
	# carries no branch yet, in which case the check simply does not apply.
	out_depots = (
		frappe.get_all("Depot", filters={"branch": branch}, pluck="name")
		if branch and direction == "Tank Out"
		else []
	)

	rows, errors, unknown, created, seen = [], [], [], [], set()
	for cells in raw_rows:
		if not cells:
			continue
		cno = str(cells[0]).strip().upper() if cells[0] is not None else ""
		if not cno:
			continue
		if cno.lower() in ("container", "container no", "kontainer", "no kontainer"):
			continue  # header
		if cno in seen:
			continue
		raw_cond = str(cells[1]).strip().upper() if len(cells) > 1 and cells[1] is not None else ""
		if not raw_cond:
			condition = CONTAINER_CONDITIONS[0]
		elif raw_cond in CONTAINER_CONDITIONS:
			condition = raw_cond
		else:
			errors.append(_("{0}: kondisi {1} tidak dikenal — dilewati").format(cno, raw_cond))
			continue
		raw_cargo = str(cells[2]).strip() if len(cells) > 2 and cells[2] is not None else ""
		master = frappe.db.get_value(
			"Container",
			{"container_no": cno},
			["name", "last_cargo", "is_active", "status", "depot", "principal"],
			as_dict=True,
		)
		container = master.name if master else None
		last_cargo = master.last_cargo if master else None
		# A retired tank is out of the fleet: named and dropped rather than quietly booked,
		# and never re-registered under the same number — the master is still there.
		if container and not master.is_active:
			seen.add(cno)
			errors.append(_("{0}: container non-aktif — dilewati").format(cno))
			continue
		if container:
			blocked = _import_block(master, direction, principal, out_depots)
			if blocked:
				seen.add(cno)
				errors.append(blocked)
				continue
		is_new = 0
		if not container:
			if direction != "Tank In":
				seen.add(cno)  # before the skip, so a repeat of it is not reported twice
				unknown.append(cno)
				continue
			container = _create_imported_container(cno, principal)
			created.append(cno)
			is_new = 1
		if raw_cargo:
			cargo = frappe.db.get_value("Cargo", {"cargo_name": raw_cargo})
			if not cargo:
				errors.append(_("{0}: cargo {1} tidak dikenal — dikosongkan").format(cno, raw_cargo))
		else:
			cargo = last_cargo
		seen.add(cno)
		rows.append({
			"container_no": cno,
			"condition": condition,
			"container": container,
			"cargo": cargo,
			"is_new": is_new,
		})
	return {"rows": rows, "errors": errors, "unknown": unknown, "created": created}


# ---------------------------------------------------------------------------
# Work-per-container panel on the booking form
# ---------------------------------------------------------------------------
# What the depot actually asks a booking: "what happened to these tanks?" The Connections
# tab answers it as four flat lists, which is the wrong shape once a booking carries more
# than one container — you cannot tell which EIR belongs to which tank without opening it.
# This groups the same data the way the operator thinks about it: per container, in time
# order.
#
# (doctype, date field, extra field shown after the doctype label)
_WORK_SOURCES = (
	("Inspection", "eir_date", "inspection_type"),
	("Cleaning Order", "order_created", None),
	("Repair Order", "order_created", None),
	("Periodic Test Order", "order_created", None),
)


@frappe.whitelist()
def orders_by_container(booking: str):
	"""Work raised under ``booking``, grouped by the container it was done on.

	Returns one entry per container ROW of the booking — including containers with no work
	at all, because "nothing happened to this tank yet" is an answer the operator needs
	just as much as a list.

	``unlinked`` counts orders on that container that belong to no booking at all. They are
	counted, never merged in: attributing them is a human decision (see
	``container_depot.booking_link``), and quietly folding them into this booking would be
	exactly the guess the whole design refuses to make. The count is what tells an operator
	there is something here worth attributing.
	"""
	frappe.has_permission("Container Booking", "read", doc=booking, throw=True)

	rows = frappe.get_all(
		"Container Booking Item",
		filters={"parent": booking, "parenttype": "Container Booking"},
		fields=["container", "container_no"],
		order_by="idx asc",
	)

	out = []
	for row in rows:
		if not row.container:
			# A booking may name a tank that has no Container master yet (pre-arrival).
			out.append({
				"container": None, "container_no": row.container_no, "orders": [], "unlinked": 0,
			})
			continue
		out.append({
			"container": row.container,
			"container_no": row.container_no,
			"orders": _work_for(booking, row.container),
			"unlinked": _unlinked_count(row.container),
		})
	return out


def _work_for(booking: str, container: str) -> list:
	orders = []
	for doctype, date_field, extra_field in _WORK_SOURCES:
		fields = ["name", "status", date_field]
		if extra_field:
			fields.append(extra_field)
		for doc in frappe.get_all(
			doctype,
			filters={"container_booking": booking, "container": container},
			fields=fields,
			order_by=f"{date_field} asc",
		):
			orders.append({
				"doctype": doctype,
				"name": doc.name,
				"label": doc.get(extra_field) if extra_field else doctype,
				"status": doc.status,
				"date": doc.get(date_field),
			})
	# One timeline per tank rather than four per-doctype lists — an EIR followed by the
	# cleaning it triggered reads as a sequence, which is how the work actually happened.
	#
	# Coerce before comparing: Inspection dates a Date and the work orders a Datetime, and
	# Python refuses to order the two against each other. Undated rows sort last rather
	# than blowing up the panel.
	orders.sort(key=lambda o: (o["date"] is None, get_datetime(o["date"]) if o["date"] else None))
	return orders


def _unlinked_count(container: str) -> int:
	"""Orders on this container attributed to no booking — candidates, not members."""
	return sum(
		frappe.db.count(doctype, {"container": container, "container_booking": ("is", "not set")})
		for doctype, _date, _extra in _WORK_SOURCES
	)
