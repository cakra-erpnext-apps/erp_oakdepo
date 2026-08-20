"""Connections tab on Container Booking — everything this booking's visit produced.

Two kinds of link end up here, and the grouping keeps them apart:

* **Bon & Gate** — documents that reference the booking directly and always have since the
  booking was designed: the bons raised from it, the codes it issued, the position surveys.
* **Pekerjaan Depo** — the work orders. These reference the booking through
  ``container_booking``, which is stamped from the EIR that raised them (see
  ``container_depot.booking_link``). An order raised without an EIR is standalone and will
  not appear under any booking — by design; guessing an owner from the container alone
  would file work under the wrong one of a tank's many visits.
"""


def get_data():
	return {
		"fieldname": "booking",
		"non_standard_fieldnames": {
			"Inspection": "container_booking",
			"Cleaning Order": "container_booking",
			"Repair Order": "container_booking",
		},
		"internal_links": {
			# The booking stores the invoice it raised, not the other way round, so this one
			# is read off THIS document. A bare string means "a field on the parent"; a
			# 2-list would mean [child table, fieldname] (frappe/desk/notifications.py).
			"Sales Invoice": "sales_invoice",
		},
		"transactions": [
			{
				"label": "Bon & Gate",
				"items": ["Order Bongkar", "Order Muat", "Booking Code", "Container Position Survey"],
			},
			{
				"label": "Pekerjaan Depo",
				"items": ["Inspection", "Cleaning Order", "Repair Order"],
			},
			{"label": "Billing", "items": ["Sales Invoice"]},
		],
	}
