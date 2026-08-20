"""Depot event notifications.

One feed for both surfaces: a Notification Log row is exactly what Frappe's Desk
bell shows AND what the PWA bell reads (``ess.notifications.list_notifications``),
so creating one here lights up both at once — no second channel to keep in sync.

A recipient must clear two filters: their branch scope must cover the document (an
unrestricted/HQ user sees everything), and they must hold one of the roles the event is
routed to. The acting user is skipped — they already got the in-app toast.

WHY ROUTING IS DATA AND THE MENU IS NOT
---------------------------------------
Who receives which event lives in the ``Depot Notification Rule`` doctype, not in a dict
here. Changing a recipient is pure routing — zero code — and it is the single thing most
often tuned in the first months live ("kok saya tidak dapat notif jadwal survey", "saya
kebanjiran notif M&R"). If every such complaint needed a deploy, routing would never get
tidied and the bell would end up ignored.

This is deliberately the opposite call from the PWA menu (``ess.context._MENU``), which
stays hardcoded: a new menu always needs a new Vue page, so a config doctype there would
save nothing. Do not "make them consistent".
"""

from __future__ import annotations

import frappe

from container_depot.container_depot.user_branch import _SKIP_USERS, get_user_branches

_RULE_CACHE_KEY = "depot_notification_rules"


def clear_rule_cache():
	"""Drop the cached routing table. Called from both notification doctypes' on_update."""
	frappe.cache().delete_value(_RULE_CACHE_KEY)


def _rules() -> dict:
	"""``{event_key: {"enabled": bool, "roles": [...]}}`` plus the settings, cached.

	:func:`notify` runs on every submit, so reading two doctypes per event would put a
	pair of queries on the hot path of routine operations. The cache is invalidated from
	``DepotNotificationRule.on_update`` / ``DepotNotificationSettings.on_update``, so an
	admin's edit takes effect on the next event, not the next restart.
	"""
	cached = frappe.cache().get_value(_RULE_CACHE_KEY)
	if cached is not None:
		return cached

	table = {"_enabled": True, "_fallback": [], "_events": {}}
	try:
		settings = frappe.get_cached_doc("Depot Notification Settings")
		table["_enabled"] = bool(settings.notifications_enabled)
		table["_fallback"] = [r.role for r in (settings.fallback_roles or [])]
		for rule in frappe.get_all(
			"Depot Notification Rule", fields=["name", "enabled"], limit_page_length=0
		):
			doc = frappe.get_cached_doc("Depot Notification Rule", rule.name)
			table["_events"][doc.event_key] = {
				"enabled": bool(doc.enabled),
				"roles": [r.role for r in (doc.roles or [])],
			}
	except Exception:
		# Doctypes not migrated yet, or unreadable. Fall through with an empty table:
		# every event then takes the "rule missing" path below, which logs and routes to
		# the fallback — noisy in the log, but never a silent broadcast.
		frappe.log_error(title="Depot notification rules unreadable", message=frappe.get_traceback())

	frappe.cache().set_value(_RULE_CACHE_KEY, table)
	return table


def _event_roles(event_key):
	"""Roles that should receive ``event_key``.

	Returns ``None`` when the event must not be sent at all (master switch off, or the
	rule is disabled), otherwise a list of role names.
	"""
	table = _rules()
	if not table["_enabled"]:
		return None
	rule = table["_events"].get(event_key)
	if rule is None:
		# An event with no rule is a seeding gap, not a licence to notify everyone.
		# Broadcasting on the quiet is exactly the behaviour this redesign removes.
		frappe.log_error(
			title="Depot notification rule hilang",
			message=f"event_key tidak ditemukan: {event_key}",
		)
		return table["_fallback"]
	if not rule["enabled"]:
		return None
	return rule["roles"]


def _recipients(branch, roles=None):
	"""Enabled users whose branch scope includes ``branch`` and who hold one of ``roles``.

	``branch`` None means "don't branch-filter" (global event). A user whose branch scope
	is unrestricted (``get_user_branches`` → None) always qualifies on branch.

	``roles=None`` means "no role filter" and is reserved for genuinely global events;
	an empty list means nobody qualifies, which is what an unroutable event should do.
	"""
	if roles is not None and not roles:
		return []
	role_set = set(roles) if roles is not None else None
	users = frappe.get_all("User", filters={"enabled": 1}, pluck="name")
	out, seen = [], set()
	for u in users:
		if u in seen or u in _SKIP_USERS:
			continue
		seen.add(u)
		allowed = get_user_branches(u)  # None = all branches
		if branch and allowed is not None and branch not in allowed:
			continue
		if role_set is not None and not (role_set & set(frappe.get_roles(u))):
			continue
		out.append(u)
	return out


def notify(*, doctype, name, subject, branch=None, event_key=None, notification_type="Alert"):
	"""Create a Notification Log for every in-scope recipient. Returns the count.

	``event_key`` selects the routing rule. Passing none keeps the old branch-only
	behaviour, which no caller in this module does — every event is routed.

	Best-effort: never let a notification failure abort the submit that triggered it.
	"""
	try:
		roles = None
		if event_key is not None:
			roles = _event_roles(event_key)
			if roles is None:
				return 0  # event disabled, or notifications switched off entirely
		actor = frappe.session.user
		created = 0
		reached = []
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
				# Stamped so a tap on the bell can be routed exactly rather than guessed from
				# the doctype — see ess/notification_routes.py for why that is not enough.
				"depot_event": event_key,
				"subject": subject,
			}).insert(ignore_permissions=True)
			created += 1
			reached.append(u)
		# Same recipients, second surface: the bell needs someone to be looking, push
		# reaches the phone in a pocket. Recipients are resolved once, here — push must
		# never re-decide who gets told, or a routing change lands on one surface only.
		_push(reached, subject, doctype, name, event_key)
		return created
	except Exception:
		frappe.log_error(title="Depot notify failed", message=frappe.get_traceback())
		return 0


def _push(users, subject, doctype=None, name=None, event_key=None):
	"""Hand the recipient list to Web Push. Never lets a push problem reach the caller.

	Wrapped and imported lazily because push is optional: a site with no VAPID keys (or
	without ``pywebpush`` installed) must keep writing bell notifications exactly as
	before, not lose them to an ImportError raised mid-submit.

	The tag is the document, so a second event about the SAME order replaces its earlier
	banner instead of stacking a near-duplicate — while two different orders still queue
	up separately, the way any other app behaves.

	The banner opens the screen the notification is about, not the home page. One payload
	goes to every recipient, so the URL is the same for all of them — which is fine, because
	the route says nothing about permission: the PWA router guard and the ESS endpoint both
	re-check on arrival, and a recipient who may not open it lands on Beranda.
	"""
	if not users:
		return
	try:
		from container_depot.ess import push
		from container_depot.ess.notification_routes import route_for

		tag = f"{doctype}:{name}" if doctype and name else "depot"
		# The PWA runs on history mode with base `/depot`, so its routes are served under it.
		route = route_for(doctype, name, event_key)
		url = f"/depot{route}" if route else "/depot"
		push.push_to_users(users, title="Depot OAK", body=subject, url=url, tag=tag)
	except Exception:
		frappe.log_error(title="Depot push dispatch failed", message=frappe.get_traceback())


# Doctypes whose feed entries are revoked when the document is voided. There is now a
# single source of Alert rows for these documents — ``notify`` below. The built-in
# Notification rules that used to duplicate it were removed in v0_51.
REVOCABLE_DOCTYPES = (
	"Depot Contract",
	"Container Booking",
	"Order Bongkar",
	"Order Muat",
	"Sales Invoice",
	"Inspection",
	"Cleaning Order",
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
	subject = f"{inspection.inspection_type} • {container.container_no}"
	notify(
		doctype="Inspection",
		name=inspection.name,
		subject=subject,
		branch=_depot_branch(container.get("depot")),
		event_key="eir_submitted",
	)


def notify_eir_pending_review(inspection):
	"""Fire when a field operator sends an EIR for review (Pending Review, still a draft).

	Tells Admin Ops (+ ops oversight) a tank inspection is waiting for their check and
	final Desk Submit. Reviewers only — the field crew already finished their part."""
	who = frappe.session.user
	cno = inspection.container_no or inspection.container
	subject = f"{inspection.inspection_type} • {cno} — menunggu review Admin Ops (oleh {who})"
	notify(
		doctype="Inspection",
		name=inspection.name,
		subject=subject,
		branch=_depot_branch(inspection.get("depot")),
		event_key="eir_pending_review",
	)


def notify_cleaning_pending_review(cleaning_order):
	"""Fire when the cleaning team finishes in the PWA and sends the order for review
	(Pending Review, still a draft).

	Tells Admin Ops (+ ops oversight) that a wash is done and waiting for their check and
	final Desk Submit — the crew notification only comes later, when that Submit lands."""
	who = frappe.session.user
	cno = cleaning_order.container_no or cleaning_order.container
	subject = f"Cleaning • {cno} — menunggu review Admin Ops (oleh {who})"
	notify(
		doctype="Cleaning Order",
		name=cleaning_order.name,
		subject=subject,
		branch=_depot_branch(cleaning_order.get("depot")),
		event_key="cleaning_pending_review",
	)


def notify_cleaning_order_created(cleaning_order):
	"""Fire when a Cleaning Order is auto-created from an Empty-Dirty EIR — tells the
	cleaning team a tank is queued for cleaning so they can pick it up."""
	co = frappe.db.get_value(
		"Cleaning Order", cleaning_order,
		["name", "container", "container_no", "depot"], as_dict=True,
	)
	if not co:
		return
	subject = f"Cleaning Order • {co.container_no or co.container} — siap dikerjakan"
	notify(
		doctype="Cleaning Order",
		name=co.name,
		subject=subject,
		branch=_depot_branch(co.depot),
		event_key="cleaning_order_created",
	)


def notify_repair_order_created(repair_order):
	"""Fire when a Draft M&R is auto-created from an EIR with damage — tells the M&R
	team a tank needs repair so they can pick parts and start work."""
	ro = frappe.db.get_value(
		"Repair Order", repair_order,
		["name", "container", "container_no", "depot"], as_dict=True,
	)
	if not ro:
		return
	subject = f"M&R • {ro.container_no or ro.container} — perlu perbaikan"
	notify(
		doctype="Repair Order",
		name=ro.name,
		subject=subject,
		branch=_depot_branch(ro.depot),
		event_key="repair_order_created",
	)


def notify_repair_order_service_setup(repair_order):
	"""Fire when the workshop hands an estimate to Admin Ops (-> Service Setup) — it is
	NOT on the customer web yet and sits there until Admin Ops publishes it, so this is
	the prompt that stops it being forgotten."""
	ro = frappe.db.get_value(
		"Repair Order", repair_order,
		["name", "container", "container_no", "depot", "total_cost"], as_dict=True,
	)
	if not ro:
		return
	subject = (
		f"M&R • {ro.container_no or ro.container} — "
		f"perlu ditata Admin Ops sebelum tampil ke customer (est. {ro.total_cost or 0})"
	)
	notify(
		doctype="Repair Order",
		name=ro.name,
		subject=subject,
		branch=_depot_branch(ro.depot),
		event_key="repair_order_service_setup",
	)


def notify_repair_order_pending_approval(repair_order):
	"""Fire when an M&R estimate is submitted to the owner — tells the team a decision
	is awaited (and, once owner self-service is live, the owner). Carries the cost."""
	ro = frappe.db.get_value(
		"Repair Order", repair_order,
		["name", "container", "container_no", "depot", "total_cost"], as_dict=True,
	)
	if not ro:
		return
	subject = (
		f"M&R • {ro.container_no or ro.container} — "
		f"menunggu persetujuan owner (est. {ro.total_cost or 0})"
	)
	notify(
		doctype="Repair Order",
		name=ro.name,
		subject=subject,
		branch=_depot_branch(ro.depot),
		event_key="repair_order_pending_approval",
	)


def notify_repair_order_decided(repair_order):
	"""Fire when the owner's decision is recorded — tells the M&R team the outcome
	(Approved / Rejected / Revision Requested) so they can start work or revise."""
	ro = frappe.db.get_value(
		"Repair Order", repair_order,
		["name", "container", "container_no", "depot", "status"], as_dict=True,
	)
	if not ro:
		return
	subject = f"M&R • {ro.container_no or ro.container} — owner: {ro.status}"
	notify(
		doctype="Repair Order",
		name=ro.name,
		subject=subject,
		branch=_depot_branch(ro.depot),
		event_key="repair_order_decided",
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
	subject = f"{gate} • {', '.join(nos)} • {bon} — siap print"
	# One function, two events: inbound and outbound bons go to different people (Team
	# Kalmar cares about the outbound one, nobody needs both), so they route separately.
	notify(
		doctype=order.doctype,
		name=order.name,
		subject=subject,
		branch=order.get("branch"),
		event_key="order_gate_in" if direction == "in" else "order_gate_out",
	)


def notify_order_muat_survey(order):
	"""Fire when an Order Muat is submitted — tells the surveyor (+ ops) an EIR-Out is due
	before the tank can load (Fase G.1). The EIR-Out drafts are auto-provisioned; this is
	the signal to go work them from the EIR-Out worklist."""
	rows = order.get("containers") or []
	nos = [r.get("container_no") or r.get("container") for r in rows if (r.get("container_no") or r.get("container"))]
	if not nos:
		return
	subject = f"EIR-Out • {', '.join(nos)} — siap survey keluar"
	notify(
		doctype=order.doctype,
		name=order.name,
		subject=subject,
		branch=order.get("branch"),
		event_key="order_muat_survey",
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
		event_key="eir_out_hold",
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
		event_key="gate_out",
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
		event_key="booking_created",
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
		event_key="booking_submitted",
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
	notify(doctype="Depot Contract", name=contract.name, subject=subject, event_key="contract_created")


def notify_contract_activated(contract):
	"""Fire when a Depot Contract goes Active — its tariff is now live, so bookings
	can price off it."""
	subject = (
		f"Kontrak aktif {contract.name} • {_customer_name(contract.get('customer'))} • "
		f"berlaku s/d {contract.get('valid_to') or '-'}"
	)
	notify(doctype="Depot Contract", name=contract.name, subject=subject, event_key="contract_activated")


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
		event_key="invoice_submitted",
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
	notify(doctype="Survey Order", name=order.name, subject=subject, event_key="survey_order_submitted")
