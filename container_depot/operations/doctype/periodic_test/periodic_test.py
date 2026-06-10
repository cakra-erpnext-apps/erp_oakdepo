"""Periodic Test — container pressure-test cycle (PRD v0.2 §4).

Tracks the 2,5Y / 5Y periodic test flow: order/periodic dates, the prior test,
the computed Due Date, and who is billed. The latest Due Date is denormalised
onto ``Container.next_pt_due`` so TANK OUT gating (see Container Booking) can block
a tank whose test has lapsed.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import add_to_date, getdate, today

# Periodic-test interval, in months, keyed by test type.
PT_INTERVAL_MONTHS = {
	"2,5Y": 30,
	"5Y": 60,
}


class PeriodicTest(Document):
	def validate(self):
		self._compute_due_date()
		self._sync_status()

	def on_submit(self):
		self._push_due_to_container()
		from container_depot.operations.container_activity import log_container_activity

		log_container_activity(
			self.container, "Periodic Test",
			reference_doctype=self.doctype, reference_name=self.name,
			activity_time=self.get("periodic_date"),
			summary=f"{self.get('test_type') or 'Periodic'} test, due {self.get('due_date')}",
		)

	def on_cancel(self):
		self._push_due_to_container()

	def _compute_due_date(self):
		"""Derive Due Date from Periodic Date + interval when not set manually."""
		if self.due_date or not self.periodic_date:
			return
		months = PT_INTERVAL_MONTHS.get(self.test_type)
		if months:
			self.due_date = add_to_date(getdate(self.periodic_date), months=months)

	def _sync_status(self):
		"""Flag Overdue when the due date has passed and the test isn't done."""
		if self.status in {"Completed", "Cancelled"}:
			return
		if self.due_date and getdate(self.due_date) < getdate(today()):
			self.status = "Overdue"

	def _push_due_to_container(self):
		"""Maintain Container.next_pt_due = earliest open (non-cancelled) due date."""
		if not self.container:
			return
		earliest = frappe.db.sql(
			"""
			SELECT MIN(due_date)
			FROM `tabPeriodic Test`
			WHERE container = %s
			  AND docstatus < 2
			  AND status != 'Cancelled'
			  AND due_date IS NOT NULL
			""",
			(self.container,),
		)[0][0]
		frappe.db.set_value("Container", self.container, "next_pt_due", earliest, update_modified=False)
