"""Depot event notifications.

One feed for both surfaces: a Notification Log row is exactly what Frappe's Desk
bell shows AND what the PWA bell reads (``ess.notifications.list_notifications``),
so creating one here lights up both at once — no second channel to keep in sync.

Recipients are resolved by *who can act on the event*: users holding one of the
event's menu roles whose branch scope includes the document's branch (an
unrestricted/HQ user sees everything; an empty-branch user counts as all). The
acting user is skipped — they already got the in-app toast.
"""

from __future__ import annotations

import frappe

from container_depot.operations.user_branch import _SKIP_USERS, get_user_branches

# Roles that can use each PWA menu → who gets that menu's notifications. "Depot PWA"
# is the blanket PWA-access role (it can open every menu), so it is always included;
# the granular Phase-6 roles target users who only hold one function.
PWA_ROLE = "Depot PWA"
EIR_ROLES = {PWA_ROLE, "Surveyor", "Operator Kalmar", "Admin Ops", "Ops Supervisor", "Management"}
GATE_ROLES = {PWA_ROLE, "Security", "Admin Ops", "Ops Supervisor", "Management"}
# Bookings are commercial/admin work; the Cashier is included so a Cash booking's
# payment is collected promptly.
BOOKING_ROLES = {PWA_ROLE, "Commercial", "Admin Ops", "Ops Supervisor", "Management", "Cashier"}
# Cleaning work — the yard/cleaning crew (Operator Kalmar) plus ops oversight. "Depot
# PWA" is the blanket PWA role real cleaning users actually hold, so it is included.
CLEANING_ROLES = {PWA_ROLE, "Operator Kalmar", "Admin Ops", "Ops Supervisor", "Management"}
# M&R (Maintenance & Repair) — the workshop/surveyor crew who pick parts and repair,
# plus ops oversight.
MR_ROLES = {PWA_ROLE, "Surveyor", "Operator Kalmar", "Admin Ops", "Ops Supervisor", "Management"}
# Contracts are commercial paperwork — no yard crew. Every booking prices off one, so
# admin/ops need to know when one lands or goes live.
CONTRACT_ROLES = {PWA_ROLE, "Commercial", "Admin Ops", "Ops Supervisor", "Management"}
# Money: the Cashier collects, Commercial owns the customer, admin/management watch.
BILLING_ROLES = {PWA_ROLE, "Cashier", "Commercial", "Admin Ops", "Management"}
# Third-party survey charges — the Surveyor raises them, the Cashier collects on Cash.
SURVEY_ROLES = {PWA_ROLE, "Surveyor", "Cashier", "Admin Ops", "Ops Supervisor", "Management"}

def _recipients(branch, roles):
	"""Enabled users holding any of ``roles`` whose branch scope includes ``branch``.

	``branch`` None means "don't branch-filter" (global event). A user whose branch
	scope is unrestricted (``get_user_branches`` → None) always qualifies.
	"""
	if not roles:
		return []
	users = frappe.get_all(
		"Has Role",
		filters={"role": ["in", list(roles)], "parenttype": "User"},
		pluck="parent",
		distinct=True,
	)
	out, seen = [], set()
	for u in users:
		if u in seen or u in _SKIP_USERS:
			continue
		seen.add(u)
		if not frappe.db.get_value("User", u, "enabled"):
			continue
		allowed = get_user_branches(u)  # None = all branches
		if branch and allowed is not None and branch not in allowed:
			continue
		out.append(u)
	return out


def notify(*, doctype, name, subject, branch=None, roles=None, notification_type="Alert"):
	"""Create a Notification Log for every in-scope recipient. Returns the count.

	Best-effort: never let a notification failure abort the submit that triggered it.
	"""
	try:
		actor = frappe.session.user
		created = 0
		for u in _recipients(branch, roles):
			if u == actor:
				continue  # the actor already saw the toast
			frappe.get_doc({
				"doctype": "Notification Log",
				"for_user": u,
				"from_user": actor,
				"type": notification_type,
				"document_type": doctype,
				"document_name": name,
				"subject": subject,
			}).insert(ignore_permissions=True)
			created += 1
		return created
	except Exception:
		frappe.log_error(title="Depot notify failed", message=frappe.get_traceback())
		return 0


# Doctypes whose feed entries are revoked when the document is voided. Covers both
# sources of Alert rows for these documents: ``notify`` below, and the built-in
# Notification rules seeded by ``install.setup_document_notifications``.
REVOCABLE_DOCTYPES = (
	"Depot Contract",
	"Container Booking",
	"Order Bongkar",
	"Order Muat",
	"Sales Invoice",
	"Inspection",
	"Cleaning Order",
	"Cleaning Certificate",
	"Repair Order",
	"Survey Order",
	"Gate Entry",
)


def revoke(doctype, name):
	"""Drop every event notification raised for a document. Returns the count.

	A notification here is a *call to act* ("siap print", "siap dikerjakan"), never an
	archive — once the document is void the prompt is dead, and leaving it behind only
	buries the live work in everyone's bell. The audit trail lives on the cancelled
	document itself, not in the feed.

	Only ``Alert`` rows go. Assignment / Mention / Share rows are Frappe's own and have
	their own lifecycle (ToDo, DocShare), so they are left alone.

	Best-effort, like ``notify``: a feed hiccup must never abort the cancel it follows.
	"""
	if not (doctype and name):
		return 0
	try:
		filters = {"document_type": doctype, "document_name": name, "type": "Alert"}
		count = frappe.db.count("Notification Log", filters)
		if count:
			frappe.db.delete("Notification Log", filters)
		return count
	except Exception:
		frappe.log_error(title="Depot notify revoke failed", message=frappe.get_traceback())
		return 0


def revoke_on_cancel(doc, method=None):
	"""``doc_events`` hook — cancelling or deleting a document clears its feed."""
	revoke(doc.doctype, doc.name)


def sweep_stale_notifications() -> int:
	"""Drop every notification whose source document is cancelled or gone. Returns the
	count.

	``revoke_on_cancel`` covers the ordinary paths, but doc_events only fire through the
	ORM: a raw ``frappe.db.delete``, a bulk maintenance script or a test tear-down
	removes the document and leaves its feed rows behind, pointing at nothing. Those
	dead entries bury the live work in the bell and 404 when tapped, so this reconciles
	daily rather than trusting every caller to go through the ORM.

	Idempotent, and a no-op once the feed is clean.
	"""
	removed = 0
	for doctype in REVOCABLE_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		flagged = [
			n for n in frappe.get_all(
				"Notification Log",
				filters={"document_type": doctype, "type": "Alert"},
				pluck="document_name",
				distinct=True,
			) if n
		]
		if not flagged:
			continue
		live = set(frappe.get_all(
			doctype, filters={"name": ("in", flagged), "docstatus": ("<", 2)}, pluck="name"
		))
		stale = [n for n in flagged if n not in live]
		if stale:
			frappe.db.delete(
				"Notification Log",
				{"document_type": doctype, "document_name": ("in", stale), "type": "Alert"},
			)
			removed += len(stale)
	return removed


def _depot_branch(depot):
	return frappe.db.get_value("Depot", depot, "branch") if depot else None


def notify_eir_submitted(inspection, container):
	"""Fire when an EIR (EIR-In / EIR-Out) is submitted — tells the crew a tank was
	inspected so cleaning / M&R can pick it up."""
	code = inspection.get("inspection_id") or inspection.name
	subject = f"EIR {code} • {container.container_no} • {inspection.inspection_type}"
	notify(
		doctype="Inspection",
		name=inspection.name,
		subject=subject,
		branch=_depot_branch(container.get("depot")),
		roles=EIR_ROLES,
	)


def notify_cleaning_order_created(cleaning_order):
	"""Fire when a Cleaning Order is auto-created from an Empty-Dirty EIR — tells the
	cleaning team a tank is queued for cleaning so they can pick it up."""
	co = frappe.db.get_value(
		"Cleaning Order", cleaning_order,
		["name", "container", "container_no", "depot", "order_id"], as_dict=True,
	)
	if not co:
		return
	subject = f"Cleaning Order {co.order_id or co.name} • {co.container_no or co.container} — siap dikerjakan"
	notify(
		doctype="Cleaning Order",
		name=co.name,
		subject=subject,
		branch=_depot_branch(co.depot),
		roles=CLEANING_ROLES,
	)


def notify_repair_order_created(repair_order):
	"""Fire when a Draft M&R is auto-created from an EIR with damage — tells the M&R
	team a tank needs repair so they can pick parts and start work."""
	ro = frappe.db.get_value(
		"Repair Order", repair_order,
		["name", "container", "container_no", "depot", "repair_order_id"], as_dict=True,
	)
	if not ro:
		return
	subject = f"M&R {ro.repair_order_id or ro.name} • {ro.container_no or ro.container} — perlu perbaikan"
	notify(
		doctype="Repair Order",
		name=ro.name,
		subject=subject,
		branch=_depot_branch(ro.depot),
		roles=MR_ROLES,
	)


def notify_repair_order_pending_approval(repair_order):
	"""Fire when an M&R estimate is submitted to the owner — tells the team a decision
	is awaited (and, once owner self-service is live, the owner). Carries the cost."""
	ro = frappe.db.get_value(
		"Repair Order", repair_order,
		["name", "container", "container_no", "depot", "repair_order_id", "total_cost"], as_dict=True,
	)
	if not ro:
		return
	subject = (
		f"M&R {ro.repair_order_id or ro.name} • {ro.container_no or ro.container} — "
		f"menunggu persetujuan owner (est. {ro.total_cost or 0})"
	)
	notify(
		doctype="Repair Order",
		name=ro.name,
		subject=subject,
		branch=_depot_branch(ro.depot),
		roles=MR_ROLES,
	)


def notify_repair_order_decided(repair_order):
	"""Fire when the owner's decision is recorded — tells the M&R team the outcome
	(Approved / Rejected / Revision Requested) so they can start work or revise."""
	ro = frappe.db.get_value(
		"Repair Order", repair_order,
		["name", "container", "container_no", "depot", "repair_order_id", "status"], as_dict=True,
	)
	if not ro:
		return
	subject = f"M&R {ro.repair_order_id or ro.name} • {ro.container_no or ro.container} — owner: {ro.status}"
	notify(
		doctype="Repair Order",
		name=ro.name,
		subject=subject,
		branch=_depot_branch(ro.depot),
		roles=MR_ROLES,
	)


def notify_order_gate(order, direction):
	"""Fire when an Order Bongkar (Gate In) / Order Muat (Gate Out) is submitted.

	Reaches the gate/admin roles so the bon can be printed straight from the
	notification (clicking it opens the order)."""
	rows = order.get("containers") or []
	nos = [r.get("container_no") or r.get("container") for r in rows if (r.get("container_no") or r.get("container"))]
	if not nos:
		return
	gate = "Gate In" if direction == "in" else "Gate Out"
	bon = "Bongkar" if direction == "in" else "Muat"
	subject = f"{gate} • {', '.join(nos)} • {bon} {order.name} — siap print"
	notify(
		doctype=order.doctype,
		name=order.name,
		subject=subject,
		branch=order.get("branch"),
		roles=GATE_ROLES,
	)


def notify_order_muat_survey(order):
	"""Fire when an Order Muat is submitted — tells the surveyor (+ ops) an EIR-Out is due
	before the tank can load (Fase G.1). The EIR-Out drafts are auto-provisioned; this is
	the signal to go work them from the EIR-Out worklist."""
	rows = order.get("containers") or []
	nos = [r.get("container_no") or r.get("container") for r in rows if (r.get("container_no") or r.get("container"))]
	if not nos:
		return
	subject = f"EIR-Out • {', '.join(nos)} • Order Muat {order.name} — siap survey keluar"
	notify(
		doctype=order.doctype,
		name=order.name,
		subject=subject,
		branch=order.get("branch"),
		roles={PWA_ROLE, "Surveyor", "Ops Supervisor", "Admin Ops"},
	)


def notify_ready_to_load(container_no, order_muat=None, *, depot=None):
	"""Fire when an EIR-Out is submitted clean — signals Operator Kalmar (+ ops) that the
	tank is READY TO LOAD (Fase G.3)."""
	if not container_no:
		return
	tail = f" • {order_muat}" if order_muat else ""
	subject = f"READY TO LOAD • {container_no}{tail} — siap dimuat"
	notify(
		doctype="Order Muat" if order_muat else "Container",
		name=order_muat or container_no,
		subject=subject,
		branch=_depot_branch(depot) if depot else None,
		roles={PWA_ROLE, "Operator Kalmar", "Admin Ops", "Ops Supervisor"},
	)


def notify_eir_out_hold(container_no, order_muat=None, reason=None, *, depot=None):
	"""Fire when an EIR-Out finds an issue — puts the tank on HOLD and asks the Ops
	Supervisor (+ admin) to clear it (Fase G.4)."""
	if not container_no:
		return
	tail = f" • {reason}" if reason else ""
	subject = f"HOLD • {container_no}{tail} — perlu clearance Supervisor"
	notify(
		doctype="Order Muat" if order_muat else "Container",
		name=order_muat or container_no,
		subject=subject,
		branch=_depot_branch(depot) if depot else None,
		roles={PWA_ROLE, "Ops Supervisor", "Admin Ops"},
	)


def notify_gate_out(container_no, *, gate_entry=None, depot=None, when=None):
	"""Fire when a tank completes gate-out / load-complete (keluar depo). Reaches the
	gate/ops roles (same surface as the order-gate notification)."""
	if not container_no:
		return
	ts = frappe.utils.format_datetime(when) if when else ""
	subject = f"Gate Out • {container_no} • isotank keluar depo {ts}".strip()
	notify(
		doctype="Gate Entry",
		name=gate_entry,
		subject=subject,
		branch=_depot_branch(depot) if depot else None,
		roles=GATE_ROLES,
	)


def notify_booking_created(booking):
	"""Fire when a Container Booking is first created (draft) — lets Commercial /
	admin / Cashier know a new booking (and, for Cash, a payment to collect) exists."""
	customer = frappe.db.get_value("Customer", booking.customer, "customer_name") if booking.get("customer") else None
	pay = booking.get("payment_type") or "Cash"
	tail = " • bayar di kasir" if pay == "Cash" else ""
	subject = f"Booking baru {booking.name} • {customer or booking.get('customer') or '-'} • {booking.get('direction') or 'Tank In'} • {pay}{tail}"
	notify(
		doctype="Container Booking",
		name=booking.name,
		subject=subject,
		branch=booking.get("branch"),
		roles=BOOKING_ROLES,
	)


def notify_booking_submitted(booking):
	"""Fire when a Container Booking is confirmed (submitted)."""
	customer = frappe.db.get_value("Customer", booking.customer, "customer_name") if booking.get("customer") else None
	subject = f"Booking dikonfirmasi {booking.name} • {customer or booking.get('customer') or '-'} • {booking.get('direction') or 'Tank In'}"
	notify(
		doctype="Container Booking",
		name=booking.name,
		subject=subject,
		branch=booking.get("branch"),
		roles=BOOKING_ROLES,
	)


def _customer_name(customer):
	"""Display name for a Customer link, falling back to the id (then a dash)."""
	if not customer:
		return "-"
	return frappe.db.get_value("Customer", customer, "customer_name") or customer


def notify_contract_created(contract):
	"""Fire when a Depot Contract is drafted — Commercial/admin see a contract is
	waiting to be activated (nothing can be priced or booked until it is)."""
	# A contract seeded straight to Active (patches, data import) is already live, so
	# only a real Draft gets the "waiting" call to action.
	tail = " — menunggu aktivasi" if contract.get("status") == "Draft" else ""
	subject = (
		f"Kontrak baru {contract.name} • {_customer_name(contract.get('customer'))} • "
		f"{contract.get('payment_type') or '-'}{tail}"
	)
	# Contracts carry no branch or depot: they are per-customer commercial paperwork
	# that applies depot-wide, so this is a global event.
	notify(doctype="Depot Contract", name=contract.name, subject=subject, roles=CONTRACT_ROLES)


def notify_contract_activated(contract):
	"""Fire when a Depot Contract goes Active — its tariff is now live, so bookings
	can price off it."""
	subject = (
		f"Kontrak aktif {contract.name} • {_customer_name(contract.get('customer'))} • "
		f"berlaku s/d {contract.get('valid_to') or '-'}"
	)
	notify(doctype="Depot Contract", name=contract.name, subject=subject, roles=CONTRACT_ROLES)


def notify_invoice_submitted(invoice, method=None):
	"""``doc_events`` hook — fire when a Sales Invoice is issued, so the Cashier knows
	there is money to collect and Commercial sees the customer was billed.

	Carries the outstanding amount rather than the total: a Cash booking's invoice is
	already settled at submit, and "sisa 0" is the signal that nothing is owed.
	"""
	outstanding = frappe.utils.flt(invoice.get("outstanding_amount"))
	money = frappe.utils.fmt_money(outstanding, currency=invoice.get("currency"))
	tail = "lunas" if outstanding <= 0 else f"sisa {money} • jatuh tempo {invoice.get('due_date') or '-'}"
	subject = f"Invoice {invoice.name} • {_customer_name(invoice.get('customer'))} • {tail}"
	notify(
		doctype="Sales Invoice",
		name=invoice.name,
		subject=subject,
		branch=invoice.get("branch"),
		roles=BILLING_ROLES,
	)


def notify_cleaning_certificate_issued(cert):
	"""Fire when a Cleaning Certificate is submitted — the tank is certified clean, which
	is what an Order Muat requires before it can load."""
	container = cert.get("container_no") or cert.get("container") or "-"
	# A statement-minted cert has no expiry (validity is anchored per EIR), so say so
	# rather than printing an empty date.
	validity = f"berlaku s/d {cert.get('valid_until')}" if cert.get("valid_until") else "tanpa masa berlaku"
	subject = f"Cleaning Certificate {cert.name} • {container} • {validity}"
	notify(
		doctype="Cleaning Certificate",
		name=cert.name,
		subject=subject,
		branch=_depot_branch(frappe.db.get_value("Container", cert.get("container"), "depot"))
		if cert.get("container")
		else None,
		roles=CLEANING_ROLES,
	)


def notify_survey_order_submitted(order):
	"""Fire when a Survey Order is submitted — third-party survey charges billed to the
	Paid To. Cash raises a draft invoice to review and collect, so the Cashier is told."""
	money = frappe.utils.fmt_money(frappe.utils.flt(order.get("total")), currency=order.get("currency"))
	pay = order.get("payment_type") or "Cash"
	tail = " • bayar di kasir" if pay == "Cash" else ""
	subject = f"Survey Order {order.name} • {_customer_name(order.get('paid_to'))} • {money} • {pay}{tail}"
	# Survey Order carries no branch/depot of its own; its charge rows may each name a
	# different container, so there is no single branch to scope to.
	notify(doctype="Survey Order", name=order.name, subject=subject, roles=SURVEY_ROLES)
