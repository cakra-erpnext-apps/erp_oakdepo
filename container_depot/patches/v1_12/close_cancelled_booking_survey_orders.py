"""Survey Orders of a cancelled booking used to be marked Cancelled but left a draft.

Close them the way a booking cancel does now (docstatus 2, draft EIR-Outs with them)."""

import frappe

from container_depot.container_depot.tank_survey import close_survey_order_with_booking


def execute():
	for name in frappe.db.sql_list(
		"""SELECT so.name FROM `tabSurvey Order` so
		JOIN `tabContainer Booking` b ON b.name = so.booking
		WHERE so.docstatus = 0 AND b.booking_status = 'Cancelled'"""
	):
		close_survey_order_with_booking(name)
