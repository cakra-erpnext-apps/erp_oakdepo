from frappe.model.document import Document


class ContainerBookingCharge(Document):
	"""One priced service line on a Container Booking.

	Rates and totals are computed by the parent (``ContainerBooking._price_charges``) —
	this class only exists so the child doctype has a controller.
	"""

	pass
