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
		self._validate_cleaning_done()

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

	def _validate_cleaning_done(self):
		"""Each container row needs a finished cleaning before it may be loaded out
		(PRO-OPS-08 §8.2). The Cleaning Order itself is the proof — it carries the whole
		cleanliness record (checklist, gas free, seals, surveyor signature), so a submitted
		Completed order for that container is what the gate checks."""
		for row in _order_rows(self):
			container = row.get("container")
			if not container:
				continue
			if not frappe.db.exists(
				"Cleaning Order", {"container": container, "status": "Completed", "docstatus": 1}
			):
				frappe.throw(
					_("Row {0} ({1}): belum ada Cleaning Order yang selesai untuk container ini.").format(
						row.idx, row.get("container_no") or container
					)
				)
