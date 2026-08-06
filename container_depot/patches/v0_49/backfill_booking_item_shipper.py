import frappe


def execute():
	"""Populate the new per-container ``shipper`` (EMKL) on existing booking lines.

	The field defaults to the booking's ``customer``, but that default only fires on save —
	rows written before the field existed carry a blank EMKL and a submitted booking is
	never re-saved. Copy the parent's customer down once; new/edited rows default
	themselves (see ``ContainerBooking._default_row_shipper``).
	"""
	if not (
		frappe.db.table_exists("Container Booking Item")
		and frappe.db.table_exists("Container Booking")
	):
		return
	if not frappe.db.has_column("Container Booking Item", "shipper"):
		return
	frappe.db.sql(
		"""UPDATE `tabContainer Booking Item` i
		   JOIN `tabContainer Booking` b ON b.name = i.parent
		   SET i.shipper = b.customer
		   WHERE (i.shipper IS NULL OR i.shipper = '')
		     AND b.customer IS NOT NULL AND b.customer != ''"""
	)
