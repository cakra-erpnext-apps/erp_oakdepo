import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

from container_depot.operations.doctype.order_bongkar.order_bongkar import (
	_log_order_activity,
	_order_rows,
	_reconcile_codes,
	_release_codes,
	_sync_booking,
	_validate_booking_code,
)


class OrderMuat(Document):
	def validate(self):
		_sync_booking(self)
		_validate_booking_code(self, "Tank Out")
		self._validate_cleaning_cert()

	def on_update(self):
		_reconcile_codes(self)

	def on_submit(self):
		_log_order_activity(self, "Order Muat")

	def on_cancel(self):
		_release_codes(self)

	def _validate_cleaning_cert(self):
		"""Each container row needs a submitted, in-date Cleaning Certificate that
		matches that row's container (PRO-OPS-08 §8.2)."""
		for row in _order_rows(self):
			if not row.get("cleaning_certificate"):
				frappe.throw(
					_("Row {0} ({1}): Cleaning Certificate is required for an Order Muat.").format(
						row.idx, row.get("container_no") or ""
					)
				)
			cert = frappe.db.get_value(
				"Cleaning Certificate",
				row.cleaning_certificate,
				["container", "valid_until", "docstatus"],
				as_dict=True,
			)
			if not cert:
				frappe.throw(_("Cleaning Certificate {0} not found.").format(row.cleaning_certificate))
			if cert.docstatus != 1:
				frappe.throw(_("Cleaning Certificate {0} is not submitted.").format(row.cleaning_certificate))
			if row.get("container") and cert.container and cert.container != row.container:
				frappe.throw(
					_("Cleaning Certificate {0} is for container {1}, not {2}.").format(
						row.cleaning_certificate, cert.container, row.container
					)
				)
			if cert.valid_until and getdate(cert.valid_until) < getdate(today()):
				frappe.throw(
					_("Cleaning Certificate {0} expired on {1}.").format(
						row.cleaning_certificate, cert.valid_until
					)
				)
