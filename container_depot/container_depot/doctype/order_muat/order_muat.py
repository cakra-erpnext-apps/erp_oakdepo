import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

from container_depot.container_depot.doctype.order_bongkar.order_bongkar import (
	_ensure_order_qr,
	_log_order_activity,
	_order_rows,
	_reconcile_codes,
	_release_codes,
	_release_eirs,
	_sync_booking,
	_sync_container_summary,
	_validate_booking_code,
)


class OrderMuat(Document):
	def validate(self):
		_sync_booking(self)
		_validate_booking_code(self, "Tank Out")
		_sync_container_summary(self)
		self._validate_no_open_work()

	def on_update(self):
		_reconcile_codes(self)

	def on_submit(self):
		_log_order_activity(self, "Order Muat")
		_ensure_order_qr(self)
		from container_depot.container_depot.notify import notify_order_gate, notify_order_muat_survey
		notify_order_gate(self, "out")
		# Fase G: auto-create one DRAFT EIR-Out per container (referencing the latest EIR-In)
		# and tell the surveyor. Best-effort — an EIR-Out hiccup never blocks the bon submit.
		try:
			from container_depot.container_depot.eir import provision_eir_out_for_order_muat
			provision_eir_out_for_order_muat(self.name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"provision EIR-Out for {self.name}")
		notify_order_muat_survey(self)

	def on_cancel(self):
		_release_codes(self)
		# Order Muat provisions EIR-Out drafts on submit, so cancelling must unwind them
		# for the same reason Order Bongkar unwinds its EIR-In drafts.
		_release_eirs(self, "EIR-Out")

	def on_trash(self):
		# A bon is never deleted — Void it (draft or submitted) to release its
		# containers and keep the audit trail.
		frappe.throw(_("An Order Muat cannot be deleted — use Void to cancel it instead."))

	def _validate_no_open_work(self):
		"""No container may be loaded out while an order on it is still unfinished
		(PRO-OPS-08 §8.2).

		This used to demand a *Completed Cleaning Order* per container, which read the rule
		backwards: it made the absence of a cleaning a permanent blocker, so a tank that
		arrived clean and needed no work could never be loaded out at all — there was no
		order to finish and no way to produce one. What the yard actually owes is that
		nothing is still in progress, so the check is the open orders themselves, and it
		names them.

		**This is now the FIRST hard refusal on the way out.** The Tank Out booking used to
		apply the same test and no longer does — an outbound booking is how the depot learns
		a pickup is coming, so it is accepted while the yard works and the work is
		prioritised instead (:mod:`lift_on`). The bon is different: it is the paper a driver
		is handed to take the tank away, so here the answer has to be no.
		"""
		from container_depot.container_depot.container_status import container_open_orders

		for row in _order_rows(self):
			container = row.get("container")
			if not container:
				continue
			open_orders = container_open_orders(container)
			if not open_orders:
				continue
			listed = ", ".join(f"{o['label']} {o['name']} ({o.get('status') or '-'})" for o in open_orders)
			frappe.throw(
				_("Row {0} ({1}): masih ada order yang belum selesai — {2}.").format(
					row.idx, row.get("container_no") or container, listed
				)
			)
