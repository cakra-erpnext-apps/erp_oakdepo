"""Atomic core for issuing a bon/voucher (Order Bongkar / Order Muat) from a
booking.

One shared entry point for BOTH the SST kiosk (``api.sst_issue_order``) and the
DMS desktop button (``api.generate_order_from_booking``), so the locking and
validation rules live in exactly one place (PRO-OPS-08: "dua entry point, satu
logika").

Rules enforced here:
- **the booking's payment must allow it** (:func:`assert_payment_allows_bon`).
- 1..3 containers per bon (``MAX_CONTAINERS_PER_ORDER``).
- every selected Booking Code must belong to ``booking``, be ``Active``, and share
  one direction (a bon is single-direction).
- code selection + order creation + flipping codes to ``Used`` happen in a single
  transaction with the codes row-locked (``SELECT ... FOR UPDATE``) so two
  concurrent issues — or the hourly expiry job — can't double-spend a code.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import now_datetime, today

MAX_CONTAINERS_PER_ORDER = 2

# ---------------------------------------------------------------------------
# Payment — may this booking issue a bon at all?
# ---------------------------------------------------------------------------
# Which payment states let a bon out, per payment type. The two types mean different things
# and so get different bars:
#
#   Cash — the customer pays before they collect. Nothing but `Paid` will do, which is the
#          rule the gate has always applied.
#   TOP  — term of payment: paying later IS the arrangement, so demanding `Paid` would stop
#          every credit customer at the gate. What must have happened is that the booking has
#          been BILLED — an un-invoiced booking is one nobody has priced or committed to, and
#          letting the tank leave against it is how a movement ends up with no receivable
#          behind it at all.
#
# `Cancelled` is in neither list on purpose: it is what a cancelled invoice leaves behind, and
# a booking whose invoice was voided is back to owing nothing to anyone.
BON_ALLOWED_PAYMENT = {
	"Cash": ("Paid",),
	"TOP": ("Invoiced", "Paid"),
}

BLOCK_MESSAGES = {
	"cash_unpaid": "Booking Cash belum dibayar — bayar ke kasir dulu sebelum generate bon.",
	"not_invoiced": "Booking TOP ini belum ditagih — terbitkan invoice dulu sebelum generate bon.",
}


def payment_block_reason(booking) -> str | None:
	"""Why ``booking`` may not issue a bon yet, as a machine key — or ``None`` when it may.

	A key rather than a sentence because four surfaces need the same answer in four shapes:
	:func:`assert_payment_allows_bon` turns it into a refusal, the Gate PWA turns it into a
	red panel with the invoice number on it, the Desk turns it into the reason the "Generate
	Bon / Order" button is not there, and the gate turns it into a truck that is not let in.

	APPLIES WITH FINANCE OFF TOO, and that is a deliberate reversal. The carve-out used to
	return None whenever invoicing was off, on the reasoning that with no Sales Invoice there
	is no payment state worth holding a tank over. That stopped being true the moment
	``container_booking.set_payment_status`` gave an admin a manual Paid / Unpaid switch for
	exactly that mode: the field is no longer derived-or-meaningless, it is somebody's
	deliberate statement that the money did or did not arrive. Ignoring it would be ignoring
	the one answer the depot has.

	The two modes need no special-casing, because the rule collapses on its own: with finance
	off only Paid and Unpaid are reachable (``set_payment_status`` refuses the other two), so
	TOP's ``Invoiced`` simply never occurs and both types end up requiring Paid. A booking left
	at ``Invoiced`` from before the switch was turned off keeps its pass — it really was billed.
	"""
	b = frappe.db.get_value(
		"Container Booking", booking, ["payment_type", "payment_status"], as_dict=True
	)
	if not b:
		return None  # a booking that does not exist is somebody else's error to raise
	ptype = b.payment_type or "Cash"
	status = b.payment_status or "Unpaid"
	# An unrecognised payment type falls back to the STRICTER rule. A new type added in the
	# doctype without being considered here must not silently become a way past the gate.
	allowed = BON_ALLOWED_PAYMENT.get(ptype, BON_ALLOWED_PAYMENT["Cash"])
	if status in allowed:
		return None
	# The reason names the bar that was actually applied, not the type. Reading it off the
	# type would tell someone on an unknown type to "terbitkan invoice dulu" while the rule
	# holding them is the Cash one — sending them to the wrong desk.
	return "not_invoiced" if allowed is BON_ALLOWED_PAYMENT["TOP"] else "cash_unpaid"


def assert_payment_allows_bon(booking) -> None:
	"""Refuse to issue a bon for a booking whose payment does not allow one.

	Called from :func:`make_order`, which is the single place a bon is born — so this covers
	the Desk dialog, the Gate PWA and the SST kiosk with one rule instead of three copies that
	drift. It used to live only in ``api.gate_generate_order``, which meant the Desk's
	"Generate Bon / Order" button issued a submitted bon for an unpaid booking without asking
	anybody anything.
	"""
	reason = payment_block_reason(booking)
	if reason:
		frappe.throw(_(BLOCK_MESSAGES[reason]))

# Booking-line detail carried per container on an Order Bongkar row (it reuses the
# Container Booking Item child) and written back onto the booking's line when a bon is
# generated, so the voucher and the booking stay in step.
BONGKAR_ROW_DETAIL = (
	"condition", "cargo", "truck_plate", "driver", "driver_phone", "ro", "remarks",
)


def _build_bongkar_rows(order, booking, codes, by_name, vehicle_data):
	"""Append one Container Booking Item row per selected container to an Order Bongkar,
	carrying the booking line's detail with the voucher's dialog input overriding — and
	write that detail back onto the booking line."""
	for c in codes:
		r = by_name[c]
		item = frappe.db.get_value(
			"Container Booking Item",
			{"parent": booking, "container_no": r.container_no},
			["name", "container", *BONGKAR_ROW_DETAIL],
			as_dict=True,
		) or frappe._dict()
		detail = {f: (vehicle_data.get(f) or item.get(f)) for f in BONGKAR_ROW_DETAIL}
		# Per-row EMKL: the booking line's own shipper wins, the bon dialog's Shipper is
		# only the fallback. Reversed from the fields above because that dialog value is a
		# single header input — letting it win would flatten a booking deliberately split
		# across several transporters back onto one.
		detail["shipper"] = item.get("shipper") or vehicle_data.get("shipper")
		container = (
			r.container
			or item.get("container")
			or (frappe.db.get_value("Container", {"container_no": r.container_no}) if r.container_no else None)
		)
		order.append("containers", {
			"booking_code": r.name,
			"container": container,
			"container_no": r.container_no,
			**detail,
		})
		if item.get("name"):
			# Skip empties so a required booking-line field is never blanked.
			writeback = {f: v for f, v in detail.items() if v not in (None, "")}
			if writeback:
				frappe.db.set_value("Container Booking Item", item.name, writeback, update_modified=False)


def _as_code_list(value):
	if value is None:
		return []
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except json.JSONDecodeError:
			frappe.throw(_("selected_codes must be a JSON array of Booking Code names."))
	if isinstance(value, (list, tuple)):
		return [str(v).strip() for v in value if v and str(v).strip()]
	frappe.throw(_("selected_codes must be a list of Booking Code names."))


def make_order(booking, selected_codes, vehicle_data=None, sst=None, submit=False):
	"""Create ONE Order (Bongkar/Muat) holding 1..3 containers from
	``selected_codes`` and flip each used Booking Code ``Active``->``Used``,
	atomically. Returns the new order's name.

	``vehicle_data`` (optional dict): ``truck_plate``, ``driver_name``,
	``driver_phone``, ``transporter``, ``ex_vessel`` (Tank In),
	``destination`` (Tank Out).

	``submit``: when true (the user-facing "generate" actions), the bon is
	submitted in the same transaction so it goes live immediately — its
	``on_submit`` logs a Container Activity per container. Leave false for the
	atomic primitive (drafts used in tests / staged flows).
	"""
	codes = _as_code_list(selected_codes)
	if not (1 <= len(codes) <= MAX_CONTAINERS_PER_ORDER):
		frappe.throw(_("Select between 1 and {0} containers.").format(MAX_CONTAINERS_PER_ORDER))
	if len(set(codes)) != len(codes):
		frappe.throw(_("The same container was selected more than once."))
	if not booking or not frappe.db.exists("Container Booking", booking):
		frappe.throw(_("Booking {0} not found.").format(booking))
	# Before the row locks and before a single code is spent: a refusal that happens after the
	# transaction has started is a rollback the operator watches, and one that happens after
	# the codes are flipped is a bug.
	assert_payment_allows_bon(booking)

	vehicle_data = vehicle_data or {}

	frappe.db.savepoint("make_order")
	try:
		# Row-lock the candidate codes for the whole transaction.
		locked = frappe.db.sql(
			"""
			SELECT name, state, direction, booking, container, container_no
			FROM `tabBooking Code`
			WHERE name IN %(codes)s
			FOR UPDATE
			""",
			{"codes": tuple(codes)},
			as_dict=True,
		)
		by_name = {r.name: r for r in locked}
		missing = [c for c in codes if c not in by_name]
		if missing:
			frappe.throw(_("Booking Code(s) not found: {0}").format(", ".join(missing)))

		directions = {by_name[c].direction for c in codes}
		if len(directions) != 1:
			frappe.throw(_("All containers on one bon must share the same direction."))
		direction = directions.pop()
		order_doctype = "Order Bongkar" if direction == "Tank In" else "Order Muat"

		for c in codes:
			r = by_name[c]
			label = r.container_no or r.name
			if r.booking != booking:
				frappe.throw(_("Container {0} is not on booking {1}.").format(label, booking))
			if r.state != "Active":
				frappe.throw(
					_("Container {0} is no longer pending (state {1}).").format(label, r.state)
				)

		head = frappe.db.get_value(
			"Container Booking", booking, ["customer", "principal", "plan_date"], as_dict=True
		) or frappe._dict()
		customer = head.customer
		order = frappe.new_doc(order_doctype)
		order.booking = booking
		order.order_status = "Issued"
		order.sst = sst
		order.gate_in_time = now_datetime()
		order.shipper = _resolve_shipper(vehicle_data, customer)

		if direction == "Tank In":
			order.principal = head.principal
			order.ex_vessel = vehicle_data.get("ex_vessel")
			# Actual unload date for the bon: what the gate typed, else the day the booking
			# planned, else today. Read off the HEADER now — the booking line holds the
			# realisation, which is the date this very bon is about to write there.
			order.tanggal_bongkar = (
				vehicle_data.get("tanggal_bongkar_actual")
				or head.plan_date
				or today()
			)
			_build_bongkar_rows(order, booking, codes, by_name, vehicle_data)
		else:
			# A remark may arrive per container (``{code: text}``, the Desk dialog) or as one
			# note for the whole bon (a plain string, which the PWA gate sends). The string
			# form used to be dropped silently — the operator typed a note at the gate and it
			# reached nothing.
			remarks = vehicle_data.get("remarks") or {}
			if isinstance(remarks, str):
				remarks = {c: remarks for c in codes}
			order.truck_plate = vehicle_data.get("truck_plate")
			order.driver_name = vehicle_data.get("driver_name")
			order.driver_phone = vehicle_data.get("driver_phone")
			order.ro = vehicle_data.get("ro")
			order.destination = vehicle_data.get("destination")
			# The bon's load date: what the dialog / gate typed, else the booking's own Plan
			# Date. Falling straight through to today was how an outbound bon prepared a week
			# ahead came out stamped with the day it was printed — so today is the last
			# resort, not the second one.
			order.tanggal_muat = (
				vehicle_data.get("tanggal_muat")
				or vehicle_data.get("tanggal")
				or head.plan_date
				or today()
			)
			for c in codes:
				r = by_name[c]
				order.append("containers", {
					"booking_code": r.name,
					"container": r.container,
					"container_no": r.container_no,
					"remarks": remarks.get(r.name) if isinstance(remarks, dict) else None,
				})
		# validate() re-runs the Active/direction/scoping/count checks (and, for Muat,
		# the finished-Cleaning-Order gate) as defense in depth.
		order.insert(ignore_permissions=True)

		# Single-use: consume each code so later scans/selections are rejected.
		for c in codes:
			frappe.db.set_value("Booking Code", c, "state", "Used", update_modified=False)

		# The "generate" actions (SST kiosk / DMS / Gate) issue a FINAL bon — submit
		# it in the same transaction so it goes live immediately and logs a Container
		# Activity per container. Use Cancel (→ draft) to edit, or Void to soft-delete.
		if submit:
			order.flags.ignore_permissions = True
			order.submit()
	except Exception:
		frappe.db.rollback(save_point="make_order")
		raise

	return order.name


def _resolve_shipper(vehicle_data, fallback):
	"""The hauling party for a bon — one field under three names.

	The yard calls it *angkutan*, the customer calls it *EMKL*, the document says *shipper*.
	Order Muat used to carry ``angkutan`` as free text ALONGSIDE the ``shipper`` link, so the
	same company could be typed into one and looked up in the other with nothing tying them
	together. There is now only ``shipper``, and the old key is still accepted so an older
	caller (or a cached PWA build) does not silently lose what the operator typed — but only
	when it names a real Customer, since the field is a Link.
	"""
	direct = vehicle_data.get("shipper")
	if direct:
		return direct
	for alias in ("angkutan", "transporter"):
		value = vehicle_data.get(alias)
		if value and frappe.db.exists("Customer", value):
			return value
	return fallback


def _order_child_doctype(doc):
	"""The container child-table doctype for an order (Container Booking Item for
	Order Bongkar, Order Container Item for Order Muat)."""
	return doc.meta.get_field("containers").options


@frappe.whitelist()
def void_order(name, doctype="Order Bongkar"):
	"""Void (soft-delete) an Order Bongkar/Muat: release its Booking Codes back to
	``Active`` and mark the bon Cancelled (docstatus 2). The record is RETAINED —
	``on_trash`` blocks real deletion — and voided bons drop out of the active
	(docstatus=1) views.

	Works on a draft (release codes, set Cancelled directly on parent + child rows)
	and on a submitted bon (``doc.cancel()`` → ``on_cancel`` releases the codes)."""
	if doctype not in ("Order Bongkar", "Order Muat"):
		frappe.throw(_("Unsupported order doctype: {0}").format(doctype))
	from container_depot.container_depot.doctype.order_bongkar.order_bongkar import _release_codes

	doc = frappe.get_doc(doctype, name)
	# Voiding IS cancelling — it lands the bon on docstatus 2 — so it needs the cancel
	# permission, exactly like the native Cancel it replaces. Without this line the
	# whitelist alone was the gate: `frappe.get_doc` checks nothing, and the draft branch
	# below writes docstatus through db.sql, which bypasses the ORM check as well. A
	# read-only Finance account could void a bon. §8.1 withholds cancel from the field
	# roles on purpose (undoing a mis-submitted bon escalates to Admin Ops) and that
	# intent only means something if it is enforced here.
	doc.check_permission("cancel")
	if doc.docstatus == 2:
		frappe.throw(_("Order {0} is already voided.").format(doc.name))
	if doc.docstatus == 1:
		doc.cancel()  # submitted: on_cancel releases the codes
		return doc.name
	# Draft: free the codes, then mark Cancelled directly (parent + child rows).
	_release_codes(doc)
	child = _order_child_doctype(doc)
	frappe.db.set_value(doctype, doc.name, "docstatus", 2, update_modified=False)
	frappe.db.sql(
		f"UPDATE `tab{child}` SET docstatus = 2 WHERE parent = %s AND parenttype = %s",
		(doc.name, doctype),
	)
	return doc.name


@frappe.whitelist()
def revert_order_to_draft(name, doctype="Order Bongkar"):
	"""Cancel → Draft: return a SUBMITTED Order Bongkar/Muat to an editable draft
	(docstatus 1 → 0) so it can be corrected and re-submitted. The bon keeps its
	containers and their Booking Codes (still ``Used``). Use ``void_order`` to
	soft-delete instead."""
	if doctype not in ("Order Bongkar", "Order Muat"):
		frappe.throw(_("Unsupported order doctype: {0}").format(doctype))
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("cancel")
	if doc.docstatus != 1:
		frappe.throw(_("Only a submitted order can be returned to draft."))
	child = _order_child_doctype(doc)
	frappe.db.set_value(doctype, doc.name, {"docstatus": 0, "order_status": "Issued"})
	frappe.db.sql(
		f"UPDATE `tab{child}` SET docstatus = 0 WHERE parent = %s AND parenttype = %s",
		(doc.name, doctype),
	)
	return doc.name
