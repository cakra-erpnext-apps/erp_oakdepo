"""Shared writer for the Container Activity timeline.

Every business action against a container (gate, EIR, cleaning, certificate,
repair, release, orders, periodic test, booking) calls
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
