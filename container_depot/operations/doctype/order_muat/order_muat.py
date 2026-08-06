import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

from container_depot.operations.doctype.order_bongkar.order_bongkar import (
	_ensure_order_qr,
	_log_order_activity,
	_order_rows,
	_reconcile_codes,
	_release_codes,
	_release_eirs,
	_sync_booking,
	_validate_booking_code,
)


class OrderMuat(Document):
	def validate(self):
		_sync_booking(self)
		_validate_booking_code(self, "Tank Out")
		self._validate_no_open_work()

	def on_update(self):
		_reconcile_codes(self)

	def on_submit(self):
		_log_order_activity(self, "Order Muat")
		_ensure_order_qr(self)
		from container_depot.operations.notify import notify_order_gate, notify_order_muat_survey
		notify_order_gate(self, "out")
		# Fase G: auto-create one DRAFT EIR-Out per container (referencing the latest EIR-In)
		# and tell the surveyor. Best-effort — an EIR-Out hiccup never blocks the bon submit.
		try:
			from container_depot.operations.eir import provision_eir_out_for_order_muat
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
		nothing is still in progress, so the check is now the open orders themselves (the
		same source the Tank Out booking and the gate use), and it names them.
		"""
		from container_depot.operations.container_status import container_open_orders

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
