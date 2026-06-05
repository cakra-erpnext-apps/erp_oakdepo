"""Scheduled jobs registered via :mod:`container_depot.hooks.scheduler_events`."""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, getdate, now_datetime, today


SST_STALE_AFTER_MINUTES = 15

# How far ahead a periodic test is flagged for a due-date reminder.
PT_REMINDER_DAYS = 30


def generate_monthly_invoices() -> int:
	"""Monthly (1st of month): build prior-month categorized invoices for every
	Tank Owner. Thin wrapper so the heavy logic stays in monthly_invoicing."""
	from container_depot.monthly_invoicing import generate_monthly_invoices as _run

	return _run()


def _portal_users(customer) -> list[str]:
	"""Active Customer Portal User logins for a customer."""
	if not customer:
		return []
	return frappe.get_all(
		"Customer Portal User",
		filters={"customer": customer, "approval_status": "Active"},
		pluck="user",
	)


def _open_todo(reference_type, reference_name, user, description, priority="Medium") -> bool:
	"""Create one Open ToDo per (reference, user); returns True if created."""
	if frappe.db.exists(
		"ToDo",
		{"reference_type": reference_type, "reference_name": reference_name, "allocated_to": user, "status": "Open"},
	):
		return False
	frappe.get_doc({
		"doctype": "ToDo",
		"description": description,
		"reference_type": reference_type,
		"reference_name": reference_name,
		"allocated_to": user,
		"priority": priority,
		"status": "Open",
	}).insert(ignore_permissions=True)
	return True


def notify_customers() -> int:
	"""Daily: nudge customer portal users about items needing their attention —
	M&R repair orders awaiting approval and overdue Sales Invoices.

	Returns the count of ToDos created. Idempotent (one Open ToDo per reference).
	"""
	created = 0

	# 1. Repair Orders awaiting Tank Owner approval.
	for ro in frappe.get_all(
		"Repair Order",
		filters={"status": "Pending Approval"},
		fields=["name", "principal", "container"],
	):
		for user in _portal_users(ro.principal):
			if _open_todo(
				"Repair Order", ro.name, user,
				f"M&R {ro.name} for {ro.container} awaits your approval.", "High",
			):
				created += 1

	# 2. Overdue Sales Invoices.
	for si in frappe.get_all(
		"Sales Invoice",
		filters={"status": "Overdue", "docstatus": 1},
		fields=["name", "customer"],
	):
		for user in _portal_users(si.customer):
			if _open_todo("Sales Invoice", si.name, user, f"Invoice {si.name} is overdue."):
				created += 1

	if created:
		frappe.db.commit()
	return created


def expire_booking_codes() -> int:
	"""Flip Active Booking Codes whose ``expires_at`` is in the past to Expired.

	Runs hourly. Returns the count of rows transitioned (useful for tests).
	"""
	stale = frappe.get_all(
		"Booking Code",
		filters={"state": "Active", "expires_at": ("<", now_datetime())},
		fields=["name"],
		limit_page_length=0,
	)
	for row in stale:
		frappe.db.set_value(
			"Booking Code", row.name, "state", "Expired", update_modified=False
		)
	if stale:
		frappe.db.commit()
	return len(stale)


def mark_stale_sst_heartbeats() -> int:
	"""Flag SST terminals that have not heartbeated within the threshold.

	Runs every 5 minutes. Side-effects:
	- Sets ``printer_status='Stale'`` (if currently OK/Warning).
	- Opens one ToDo per stale terminal, addressed to anyone holding the
	  Ops Supervisor role.

	Returns the count of newly-stale terminals.
	"""
	threshold = add_to_date(now_datetime(), minutes=-SST_STALE_AFTER_MINUTES)
	rows = frappe.get_all(
		"Self Service Terminal",
		filters={"last_heartbeat": ("<", threshold), "printer_status": ("in", ["OK", "Warning"])},
		fields=["name", "terminal_id", "gate_location"],
	)
	if not rows:
		return 0

	supervisors = frappe.get_all(
		"Has Role",
		filters={"role": "Ops Supervisor", "parenttype": "User"},
		fields=["parent"],
		pluck="parent",
	)
	for row in rows:
		frappe.db.set_value(
			"Self Service Terminal", row.name, "printer_status", "Stale", update_modified=False
		)
		# Skip duplicate ToDo (one open per terminal).
		for user in supervisors:
			already = frappe.db.exists(
				"ToDo",
				{
					"reference_type": "Self Service Terminal",
					"reference_name": row.name,
					"allocated_to": user,
					"status": "Open",
				},
			)
			if already:
				continue
			frappe.get_doc({
				"doctype": "ToDo",
				"description": f"SST {row.terminal_id} ({row.gate_location or '-'}) has not heartbeated in {SST_STALE_AFTER_MINUTES}+ minutes.",
				"reference_type": "Self Service Terminal",
				"reference_name": row.name,
				"allocated_to": user,
				"priority": "High",
				"status": "Open",
			}).insert(ignore_permissions=True)
	frappe.db.commit()
	return len(rows)


def remind_periodic_test_due() -> int:
	"""Flag periodic tests due within the reminder horizon (PRD v0.2 §4).

	Runs daily. Side-effects:
	- Flips lapsed open tests to ``Overdue``.
	- Opens one ToDo per due/overdue test, addressed to Commercial + Ops
	  Supervisor role holders.

	Returns the count of tests in the due/overdue window.
	"""
	horizon = add_to_date(getdate(today()), days=PT_REMINDER_DAYS)
	rows = frappe.get_all(
		"Periodic Test",
		filters={
			"status": ("not in", ["Completed", "Cancelled"]),
			"docstatus": ("<", 2),
			"due_date": ("is", "set"),
		},
		fields=["name", "container_no", "due_date", "test_type"],
	)
	due = [r for r in rows if r.due_date and getdate(r.due_date) <= horizon]
	if not due:
		return 0

	today_d = getdate(today())
	recipients = frappe.get_all(
		"Has Role",
		filters={"role": ("in", ["Commercial", "Ops Supervisor"]), "parenttype": "User"},
		fields=["parent"],
		pluck="parent",
	)
	recipients = sorted(set(recipients))

	for r in due:
		if getdate(r.due_date) < today_d:
			frappe.db.set_value("Periodic Test", r.name, "status", "Overdue", update_modified=False)
		for user in recipients:
			already = frappe.db.exists(
				"ToDo",
				{
					"reference_type": "Periodic Test",
					"reference_name": r.name,
					"allocated_to": user,
					"status": "Open",
				},
			)
			if already:
				continue
			frappe.get_doc({
				"doctype": "ToDo",
				"description": f"Periodic Test {r.test_type} for {r.container_no or r.name} is due on {r.due_date}.",
				"reference_type": "Periodic Test",
				"reference_name": r.name,
				"allocated_to": user,
				"priority": "High",
				"status": "Open",
			}).insert(ignore_permissions=True)
	frappe.db.commit()
	return len(due)
