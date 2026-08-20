"""Shared writer for the Container Activity timeline.

Every business action against a container (gate, EIR, cleaning, certificate,
repair, release, orders, booking) calls
:func:`log_container_activity` from its finalize hook (usually ``on_submit``).
The rich source doctype keeps the detail; this writes one thin, append-only
row that links back to it — giving monitoring a single chronological feed.

Kept dependency-light (only ``frappe``) because ~10 controllers import it, and
deliberately resilient: a logging failure is swallowed (logged to the Error Log)
so it can never break the primary action it is recording.
"""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime


def log_container_activity(
	container,
	activity_type,
	*,
	reference_doctype=None,
	reference_name=None,
	from_status=None,
	to_status=None,
	summary=None,
	performed_by=None,
	activity_time=None,
):
	"""Append one Container Activity row. Never raises — best-effort audit.

	``principal`` / ``depot`` are denormalized from the Container so the feed can
	be filtered by owner / depot without a join.
	"""
	if not container:
		return None
	try:
		principal, depot = frappe.db.get_value("Container", container, ["principal", "depot"]) or (None, None)
		doc = frappe.get_doc({
			"doctype": "Container Activity",
			"container": container,
			"activity_time": activity_time or now_datetime(),
			"activity_type": activity_type,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"from_status": from_status,
			"to_status": to_status,
			"summary": summary,
			"performed_by": performed_by or frappe.session.user,
			"principal": principal,
			"depot": depot,
		})
		doc.insert(ignore_permissions=True)
		return doc.name
	except Exception:
		# Audit logging must never break the action it records.
		frappe.log_error(frappe.get_traceback(), "container_depot Container Activity log failed")
		return None


def log_doc_note(doctype, name, message) -> None:
	"""Append one timeline comment to a document — best-effort, never raises.

	Companion to :func:`log_container_activity` for the deliberate raw-write paths
	(``db_set`` / ``frappe.db.set_value``) that bypass the document layer: those leave no
	``Version`` row, so without this the change is invisible on the order's own timeline.
	Prefer ``doc.save()`` where it is safe — reach for this only when saving is impossible
	(docstatus flips, non-``allow_on_submit`` fields on a submitted doc).
	"""
	try:
		frappe.get_doc({
			"doctype": "Comment",
			"comment_type": "Comment",
			"comment_email": frappe.session.user,
			"reference_doctype": doctype,
			"reference_name": name,
			"content": message,
		}).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"container_depot timeline note failed: {doctype} {name}")


# ---------------------------------------------------------------------------
# Riwayat (history): read the Container Activity timeline.
# ---------------------------------------------------------------------------
def list_activity_history(start=0, page_length=10, search=None) -> dict:
	"""Container Activity timeline (Gate / EIR / Cleaning / Repair / Status… events) — the
	PWA Monitor "Riwayat" feed, newest first, paginated + searchable, depot-scoped to the
	caller's branch. (``Container.name == container_no``, so search matches the number.)"""
	from frappe.utils import cint
	from container_depot.container_depot.user_branch import get_user_depots

	filters = {}
	depots = get_user_depots()
	if depots is not None:
		filters["depot"] = ["in", depots or [""]]
	or_filters = None
	search = (search or "").strip()
	if search and search.lower() not in ("undefined", "null", "none"):
		or_filters = {"container": ["like", f"%{search}%"], "summary": ["like", f"%{search}%"]}
	items = frappe.get_all(
		"Container Activity", filters=filters, or_filters=or_filters,
		fields=["name", "container", "activity_type", "from_status", "to_status",
			"reference_doctype", "reference_name", "performed_by", "summary",
			"activity_time", "depot", "principal"],
		order_by="activity_time desc",
		limit_start=cint(start), limit_page_length=cint(page_length),
	)
	return {"items": items, "total": frappe.db.count("Container Activity", filters)}


def get_activity_detail(name) -> dict:
	"""One Container Activity record (the action + its source-doc link), branch-guarded."""
	from container_depot.container_depot.user_branch import assert_in_user_branch

	if not name:
		frappe.throw("name is required.")
	a = frappe.get_doc("Container Activity", name)
	assert_in_user_branch(depot=a.depot)
	return {
		"name": a.name,
		"container": a.container,
		"activity_type": a.activity_type,
		"from_status": a.from_status,
		"to_status": a.to_status,
		"reference_doctype": a.reference_doctype,
		"reference_name": a.reference_name,
		"performed_by": a.performed_by,
		"summary": a.summary,
		"activity_time": str(a.activity_time) if a.activity_time else None,
		"depot": a.depot,
		"principal": a.principal,
	}
