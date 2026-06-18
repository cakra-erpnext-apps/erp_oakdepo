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

# Yard Zone category → short Indonesian label used in the EIR notification subject.
CATEGORY_LABEL = {
	"Workshop": "Workshop (Repair)",
	"Empty Dirty Queue": "Antrean Cuci",
	"Cleaning Bay": "Cleaning Bay",
	"Survey": "Survey (Inspecting)",
	"Empty Clean": "Empty Clean",
	"Ready": "Ready",
	"Gate": "Gate",
}


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


def _depot_branch(depot):
	return frappe.db.get_value("Depot", depot, "branch") if depot else None


def notify_eir_submitted(inspection, container, target_category):
	"""Fire when an EIR (EIR-In / EIR-Out) is submitted — subject carries the
	placement target category so the yard operator knows where the tank goes."""
	code = inspection.get("inspection_id") or inspection.name
	cat = CATEGORY_LABEL.get(target_category, target_category)
	tail = f" → {cat}" if cat else ""
	subject = f"EIR {code} • {container.container_no} • {inspection.inspection_type}{tail}"
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
