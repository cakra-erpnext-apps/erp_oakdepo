import frappe
from frappe import _
from frappe.model.document import Document


class OrderBongkar(Document):
	def validate(self):
		_validate_booking_code(self, "Tank In")
		_fill_qr_image(self)


def _validate_booking_code(doc: Document, expected_direction: str):
	"""Ensure the linked Booking Code is Active and matches the order direction."""
	if not doc.booking_code:
		return
	bc = frappe.db.get_value(
		"Booking Code",
		doc.booking_code,
		["state", "direction", "container", "container_no", "expires_at"],
		as_dict=True,
	)
	if not bc:
		frappe.throw(_("Booking Code {0} not found.").format(doc.booking_code))
	if bc.direction != expected_direction:
		frappe.throw(
			_("Booking Code {0} is for {1}, not {2}.").format(
				doc.booking_code, bc.direction, expected_direction
			)
		)
	if bc.state != "Active":
		frappe.throw(_("Booking Code {0} state is {1}; must be Active.").format(doc.booking_code, bc.state))
	# Auto-populate container fields if blank.
	if not doc.container and bc.container:
		doc.container = bc.container
	if not doc.container_no and bc.container_no:
		doc.container_no = bc.container_no


def _fill_qr_image(doc: Document):
	if doc.qr_code or not doc.booking_code:
		return
	qr = frappe.db.get_value("Booking Code", doc.booking_code, "qr_image")
	if qr:
		doc.qr_code = qr
