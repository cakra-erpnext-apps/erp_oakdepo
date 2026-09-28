"""Draft EIR-Outs raised by a survey before their bon carry no EMKL, so the print shows
"Received by —". Fill them from the tank's Container Booking row (same source new ones use)."""

import frappe


def execute():
	from container_depot.container_depot.eir import booking_party_for_eir_out

	for eir in frappe.get_all(
		"Inspection",
		filters={
			"inspection_type": "EIR-Out",
			"docstatus": 0,
			"emkl": ["is", "not set"],
			"referred_voucher": ["is", "not set"],
			"survey_order": ["is", "set"],
		},
		fields=["name", "survey_order", "container"],
	):
		party = booking_party_for_eir_out(eir.survey_order, eir.container)
		if party:
			frappe.db.set_value("Inspection", eir.name, party, update_modified=False)
