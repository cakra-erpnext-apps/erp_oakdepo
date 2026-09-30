"""Invoice labour flips from hours-per-line × header tariff to tariff-per-line × header hours
(user, 2026-09-29).

Before: line ``manhour`` = hours, header ``manhour_hour`` = the hourly tariff (invoice
currency), ``total_manhour`` = Σ hours. Now: line ``manhour`` = the labour tariff per hour
(line currency), ``manhour_hour`` = the hours worked ("Total Jam"), ``total_manhour`` = Σ
tariffs (invoice currency).

Every existing invoice keeps its Biaya Manhour to the cent: a line's new tariff is what its
labour cost (its hours × the old tariff, into the line's own currency) and Total Jam is 1.
A draft without labour gets the new default of 4 hours. Tagih Manhour (new, off by default)
is ticked wherever labour was charged, so a later save keeps it. ``manhour_amount`` and the
ledger are not touched.
"""

import frappe
from frappe.utils import flt


def execute():
	# after_migrate creates custom fields, after the patches: Tagih Manhour must exist now.
	from container_depot.install import setup_custom_fields

	setup_custom_fields()
	frappe.db.sql("UPDATE `tabSales Invoice` SET depot_bill_manhour = 1 WHERE manhour_amount <> 0")
	for si in frappe.get_all("Sales Invoice", fields=["name", "docstatus", "manhour_hour", "conversion_rate"]):
		lines = frappe.get_all(
			"Sales Invoice Item",
			filters={"parent": si.name, "parenttype": "Sales Invoice"},
			fields=["name", "manhour", "depot_kurs"],
		)
		hours = sum(flt(ln.manhour) for ln in lines)
		if not hours:
			if si.docstatus == 0:
				frappe.db.set_value("Sales Invoice", si.name, "manhour_hour", 4, update_modified=False)
			continue
		tariff, conv = flt(si.manhour_hour), flt(si.conversion_rate) or 1
		for ln in lines:
			if flt(ln.manhour):
				frappe.db.set_value(
					"Sales Invoice Item", ln.name,
					"manhour", flt(ln.manhour) * tariff * conv / (flt(ln.depot_kurs) or conv),
					update_modified=False,
				)
		frappe.db.set_value(
			"Sales Invoice", si.name, {"total_manhour": hours * tariff, "manhour_hour": 1}, update_modified=False
		)
