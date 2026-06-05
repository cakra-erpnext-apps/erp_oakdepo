import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

from container_depot.operations.doctype.order_bongkar.order_bongkar import (
	_compute_amount,
	_fill_qr_image,
	_invoice_order,
	_validate_booking_code,
)


class OrderMuat(Document):
	def validate(self):
		_validate_booking_code(self, "Tank Out")
		self._validate_cleaning_cert()
		_fill_qr_image(self)
		_compute_amount(self)

	def on_submit(self):
		_invoice_order(self)

	def _validate_cleaning_cert(self):
		if not self.cleaning_certificate:
			frappe.throw(_("Cleaning Certificate is required for an Order Muat."))
		cert = frappe.db.get_value(
			"Cleaning Certificate",
			self.cleaning_certificate,
			["container", "valid_until", "docstatus"],
			as_dict=True,
		)
		if not cert:
			frappe.throw(_("Cleaning Certificate {0} not found.").format(self.cleaning_certificate))
		if cert.docstatus != 1:
			frappe.throw(_("Cleaning Certificate {0} is not submitted.").format(self.cleaning_certificate))
		if self.container and cert.container and cert.container != self.container:
			frappe.throw(
				_("Cleaning Certificate is for container {0}, not {1}.").format(
					cert.container, self.container
				)
			)
		if cert.valid_until and getdate(cert.valid_until) < getdate(today()):
			frappe.throw(
				_("Cleaning Certificate {0} expired on {1}.").format(
					self.cleaning_certificate, cert.valid_until
				)
			)
