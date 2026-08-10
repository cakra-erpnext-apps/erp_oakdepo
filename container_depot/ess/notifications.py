"""ESS PWA notification endpoints — the in-app bell reads the caller's own
Notification Log (the same per-user feed Frappe's Desk bell uses). Thin
``@frappe.whitelist`` wrappers; everything is scoped to ``frappe.session.user`` so
no extra DocPerm is needed.
"""

from __future__ import annotations

import frappe
from frappe import _

from container_depot.api import _require_authenticated_user
from container_depot.container_depot.user_branch import get_user_branches
from container_depot.ess import notification_routes

_LOG_FIELDS = ["name", "subject", "document_type", "document_name", "depot_event", "read", "type", "creation"]

# The bell is a glance at what just happened, not an archive. Notification Log is never
# pruned (it is not registered with Log Settings and implements no `clear_old_logs`), so
# every one of these numbers has to be a hard ceiling — on a yard running a year, an
# unbounded read here is the query that makes the PWA feel broken.
_DEFAULT_LIMIT = 20
_MAX_LIMIT = 50

# Past this the badge is decoration: the PWA already renders anything over 9 as "9+".
# Counting to a real total would mean scanning every unread row to render two characters.
_UNREAD_CAP = 99

# Branch scoping cannot be pushed into SQL — the branch lives on the *source document*,
# not on the log — so those rows are filtered in Python and the scan must be bounded too.
# Consequence, and it is deliberate: a user sitting on more than this many unread logs may
# see a badge lower than the truth. A wrong number above "9+" is invisible; a five-second
# bell is not.
_UNREAD_SCAN = 500


# How to find a notification source document's branch. ``("field", x)`` reads the
# branch field directly; ``("depot", x)`` reads a depot field then Depot.branch.
_BRANCH_SOURCE = {
	"Order Bongkar": ("field", "branch"),
	"Order Muat": ("field", "branch"),
	"Container Booking": ("field", "branch"),
	"Inspection": ("depot", "depot"),
	"Container": ("depot", "depot"),
}


def _doc_branch(doctype, name):
	"""Best-effort branch for a notification's source document; None if unknown."""
	src = _BRANCH_SOURCE.get(doctype)
	if not src or not name:
		return None
	kind, field = src
	val = frappe.db.get_value(doctype, name, field)
	if not val:
		return None
	return val if kind == "field" else frappe.db.get_value("Depot", val, "branch")


def _in_allowed_branch(log, allowed):
	"""True if the log's source branch is in ``allowed`` (or can't be resolved —
	unknown-branch logs are kept so system/global notifications never vanish)."""
	b = _doc_branch(log.get("document_type"), log.get("document_name"))
	return b is None or b in allowed


def _sees_all_notifications(user=None):
	"""Administrator / System Manager oversee the whole depot, so the bell shows EVERY
	user's notifications (not just their own per-user feed)."""
	user = user or frappe.session.user
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def _unread_count(filters, allowed=None):
	"""Unread total for the badge, capped at ``_UNREAD_CAP`` and never a full-table scan.

	``allowed`` is a set of branches to filter by, or None to count as-is.
	"""
	if allowed is None:
		# LIMIT beats COUNT(*) here: `read` carries no index, so a real count walks the
		# whole table to produce a number the UI throws away.
		return len(
			frappe.get_all("Notification Log", filters=filters, fields=["name"], limit=_UNREAD_CAP + 1)
		)

	rows = frappe.get_all(
		"Notification Log",
		filters=filters,
		fields=["name", "document_type", "document_name"],
		order_by="creation desc",
		limit=_UNREAD_SCAN,
	)
	count = 0
	for row in rows:
		if _in_allowed_branch(row, allowed):
			count += 1
			if count > _UNREAD_CAP:
				break
	return count


@frappe.whitelist(methods=["GET"])
def list_notifications(limit=20):
	"""GET /api/method/…list_notifications — the caller's notifications (newest
	first) plus the unread count for the bell badge.

	Branch-scoped: a notification whose source document belongs to another branch
	is hidden, and the unread badge counts only in-branch unread logs. Users with no
	Branch restriction (HQ/admin) see everything.

	Administrator / System Manager see ALL users' notifications (depot-wide oversight),
	not just their own per-user feed.

	Never returns everything. ``limit`` is clamped to ``_MAX_LIMIT`` however large a caller
	asks, and the unread badge is capped rather than counted — see the constants above."""
	_require_authenticated_user()
	user = frappe.session.user
	limit = min(max(int(limit or _DEFAULT_LIMIT), 1), _MAX_LIMIT)

	if _sees_all_notifications(user):
		items = frappe.get_all(
			"Notification Log",
			fields=_LOG_FIELDS,
			order_by="creation desc",
			limit=limit,
		)
		# The widest read in the app: every user's log, unfiltered. Capping the badge
		# matters most here.
		return {"items": _with_openable(items, user), "unread": _unread_count({"read": 0})}

	items = frappe.get_all(
		"Notification Log",
		filters={"for_user": user},
		fields=_LOG_FIELDS,
		order_by="creation desc",
		limit=limit,
	)

	allowed = get_user_branches(user)
	if allowed is None:  # all branches -> no filtering
		unread = _unread_count({"for_user": user, "read": 0})
		return {"items": _with_openable(items, user), "unread": unread}

	allowed = set(allowed)
	items = [it for it in items if _in_allowed_branch(it, allowed)]
	# Recompute unread off the branch-filtered set so the badge matches the feed.
	unread = _unread_count({"for_user": user, "read": 0}, allowed)
	return {"items": _with_openable(items, user), "unread": unread}


def _with_openable(items, user):
	"""Tag each row with whether it leads anywhere, so the bell can show it as tappable.

	Role-level only. The list is polled every minute; loading twenty documents per poll to
	decide how to style a row is not a trade worth making. The authoritative check — which
	does load the document — runs once, when the operator actually taps (``open_target``).
	"""
	for it in items:
		it["openable"] = notification_routes.looks_openable(
			it.get("document_type"), it.get("document_name"), it.get("depot_event"), user
		)
	return items


@frappe.whitelist(methods=["POST"])
def open_target(name=None):
	"""POST — where should tapping this notification take the caller?

	Mutating (it marks the notification read on the way through), hence POST. The route is
	resolved server-side rather than mapped in the PWA because the answer depends on the
	document's current state and on the caller's permissions — neither of which the handset
	can be trusted to know, and the second of which it must not be trusted to decide.

	A refusal is a normal answer, not an error: it comes back with a reason the bell can show.
	"""
	_require_authenticated_user()
	log = frappe.db.get_value(
		"Notification Log", name, ["for_user", "document_type", "document_name", "depot_event"], as_dict=True
	)
	if not log:
		frappe.throw(_("Notifikasi tidak ditemukan."), frappe.DoesNotExistError)
	if not _sees_all_notifications() and log.for_user != frappe.session.user:
		frappe.throw(_("Not your notification."), frappe.PermissionError)

	# Tapping is reading. Doing it here rather than in a second round-trip means an operator
	# on a bad link cannot end up with a notification that navigated but stayed bold.
	frappe.db.set_value("Notification Log", name, "read", 1, update_modified=False)

	result = notification_routes.resolve(log.document_type, log.document_name, log.depot_event)
	result["name"] = name
	return result


@frappe.whitelist(methods=["POST"])
def mark_read(name):
	"""POST — mark a notification as read (own; or any, for Administrator/System Manager)."""
	_require_authenticated_user()
	if not _sees_all_notifications() and frappe.db.get_value("Notification Log", name, "for_user") != frappe.session.user:
		frappe.throw(_("Not your notification."), frappe.PermissionError)
	frappe.db.set_value("Notification Log", name, "read", 1, update_modified=False)
	return {"name": name, "read": 1}


@frappe.whitelist(methods=["POST"])
def mark_all_read():
	"""POST — mark all unread notifications as read (the caller's; or everyone's, for
	Administrator/System Manager)."""
	_require_authenticated_user()
	filters = {"read": 0} if _sees_all_notifications() else {"for_user": frappe.session.user, "read": 0}
	frappe.db.set_value("Notification Log", filters, "read", 1, update_modified=False)
	return {"unread": 0}
