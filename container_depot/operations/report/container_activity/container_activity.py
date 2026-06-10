"""Container Activity — the unified action-history feed.

One row per logged business action (Booking, Gate, EIR, Cleaning, Certificate,
Repair, Release, Orders, Periodic Test) against a container, newest first. Each
row links back to its source document. Reads the append-only Container Activity
ledger written by ``operations.container_activity.log_container_activity``.
"""

from __future__ import annotations

import frappe


def execute(filters=None):
	filters = filters or {}
	return _columns(), _data(filters)


def _columns():
	return [
		{"fieldname": "activity_time", "label": "Time", "fieldtype": "Datetime", "width": 160},
		{"fieldname": "container", "label": "Container", "fieldtype": "Link", "options": "Container", "width": 140},
		{"fieldname": "activity_type", "label": "Activity", "fieldtype": "Data", "width": 130},
		{"fieldname": "from_status", "label": "From", "fieldtype": "Data", "width": 130},
		{"fieldname": "to_status", "label": "To", "fieldtype": "Data", "width": 150},
		{"fieldname": "summary", "label": "Summary", "fieldtype": "Data", "width": 240},
		{"fieldname": "reference_doctype", "label": "Ref Type", "fieldtype": "Data", "width": 130},
		{"fieldname": "reference_name", "label": "Reference", "fieldtype": "Dynamic Link", "options": "reference_doctype", "width": 160},
		{"fieldname": "principal", "label": "Principal", "fieldtype": "Link", "options": "Customer", "width": 140},
		{"fieldname": "performed_by", "label": "By", "fieldtype": "Link", "options": "User", "width": 140},
	]


def _data(filters):
	where = []
	params = {}
	for field in ("container", "activity_type", "principal", "depot"):
		if filters.get(field):
			where.append(f"`{field}` = %({field})s")
			params[field] = filters[field]
	if filters.get("from_date"):
		where.append("activity_time >= %(from_date)s")
		params["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		where.append("activity_time <= %(to_date)s")
		params["to_date"] = filters["to_date"]

	clause = (" WHERE " + " AND ".join(where)) if where else ""
	return frappe.db.sql(
		f"""
		SELECT activity_time, container, activity_type, from_status, to_status,
		       summary, reference_doctype, reference_name, principal, performed_by
		FROM `tabContainer Activity`{clause}
		ORDER BY activity_time DESC, creation DESC
		""",
		params,
		as_dict=True,
	)
