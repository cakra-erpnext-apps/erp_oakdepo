import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

from container_depot.container_depot import last_orders
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
		# EMKL / Shipper on the Container master — recomputed from the bons (``last_orders``)
		# so a cancel falls back to the bon before. See Order Bongkar.on_submit.
		last_orders.refresh_for_doc(self)
		_ensure_order_qr(self)
		from container_depot.container_depot.notify import notify_order_gate, notify_order_muat_survey
		notify_order_gate(self, "out")
		self._attach_eir_out()
		notify_order_muat_survey(self)

	def _attach_eir_out(self):
		"""Point each tank's EIR-Out at this bon and stamp the truck / driver / EMKL / shipper onto it.

		The bon no longer CREATES an EIR-Out. Since 2026-09-03 the EIR-Out is raised when the
		tank's position survey is closed, days earlier, so everything typed on this screen
		lands on that document instead of on a second one beside it — and the reference is
		what finally makes it submittable (``Inspection.before_submit``).

		A tank whose survey has not been closed has nothing to attach to yet, and that passes
		in silence. It used to raise a popup here, and the popup was wrong twice over: it did
		not refuse anything (the bon submits either way), and it landed on a screen that
		already carries the readiness dossier and the open-order refusal — a third notice
		about a fourth document is what turns a working screen into a wall of text nobody
		reads. The fact is not lost: the survey is on the calendar, the surveyor is notified
		an EIR-Out is due (``notify_order_muat_survey``, fired right after this), the bon
		adopts the EIR on the next pass once the survey closes, and the gate refuses the tank
		outright without a submitted one (``gate.mark_gate_out``). That last refusal is where
		"no EIR-Out" actually has to stop somebody.

		Best-effort: an EIR hiccup never blocks the bon submit.
		"""
		try:
			from container_depot.container_depot.eir import attach_order_muat_to_eirs
			attach_order_muat_to_eirs(self.name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"attach EIR-Out for {self.name}")

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
