"""Booking Charge Template — Container Booking's own list of ready-to-copy services.

Kept apart from ``Charge Template`` on purpose: a booking bills lifts and fees to the
customer, M&R and Cleaning price work on a tank, and neither list should offer the other's
lines. A template belongs to one Customer (Bill To) and one direction, and carries no
price: the copy ("Ambil Charges", see ``charge_template.py``) prices every line from the
target booking's own Customer (Bill To) contract.
"""

from frappe.model.document import Document


class BookingChargeTemplate(Document):
	pass
