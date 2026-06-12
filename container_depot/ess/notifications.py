"""ESS PWA notification endpoints — the in-app bell reads the caller's own
Notification Log (the same per-user feed Frappe's Desk bell uses). Thin
``@frappe.whitelist`` wrappers; everything is scoped to ``frappe.session.user`` so
no extra DocPerm is needed.
"""

from __future__ import annotations

import frappe
from frappe import _

from container_depot.api import _require_authenticated_user
from container_depot.operations.user_branch import get_user_branches

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


@frappe.whitelist(methods=["GET"])
def list_notifications(limit=20):
	"""GET /api/method/…list_notifications — the caller's notifications (newest
	first) plus the unread count for the bell badge.

	Branch-scoped: a notification whose source document belongs to another branch
	is hidden, and the unread badge counts only in-branch unread logs. Users with no
	Branch restriction (HQ/admin) see everything."""
	_require_authenticated_user()
	user = frappe.session.user
	limit = min(max(int(limit or 20), 1), 50)
	items = frappe.get_all(
		"Notification Log",
		filters={"for_user": user},
		fields=["name", "subject", "document_type", "document_name", "read", "type", "creation"],
		order_by="creation desc",
		limit=limit,
	)

	allowed = get_user_branches(user)
	if allowed is None:  # all branches -> no filtering
		unread = frappe.db.count("Notification Log", {"for_user": user, "read": 0})
		return {"items": items, "unread": unread}

	allowed = set(allowed)
	items = [it for it in items if _in_allowed_branch(it, allowed)]
	# Recompute unread off the branch-filtered set so the badge matches the feed.
	unread_logs = frappe.get_all(
		"Notification Log",
		filters={"for_user": user, "read": 0},
		fields=["name", "document_type", "document_name"],
	)
	unread = sum(1 for it in unread_logs if _in_allowed_branch(it, allowed))
	return {"items": items, "unread": unread}


@frappe.whitelist(methods=["POST"])
def mark_read(name):
	"""POST — mark one of the caller's own notifications as read."""
	_require_authenticated_user()
	if frappe.db.get_value("Notification Log", name, "for_user") != frappe.session.user:
		frappe.throw(_("Not your notification."), frappe.PermissionError)
	frappe.db.set_value("Notification Log", name, "read", 1, update_modified=False)
	return {"name": name, "read": 1}


@frappe.whitelist(methods=["POST"])
def mark_all_read():
	"""POST — mark all of the caller's unread notifications as read."""
	_require_authenticated_user()
	frappe.db.set_value(
		"Notification Log",
		{"for_user": frappe.session.user, "read": 0},
		"read",
		1,
		update_modified=False,
	)
	return {"unread": 0}
