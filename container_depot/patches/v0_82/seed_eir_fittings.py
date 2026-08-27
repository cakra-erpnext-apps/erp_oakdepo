"""Seed the EIR "kelengkapan tank" master — the fill-in boxes on the printed EIR sheet.

Sumber: ``container_depot.container_depot.eir_fitting_data``. Idempotent: kode yang sudah
ada di-refresh, tidak diduplikasi. Baris yang tidak lagi ada di sumber dinonaktifkan
(``is_active = 0``) alih-alih dihapus, supaya EIR lama yang menautnya tetap bisa dibuka.
"""

import frappe

from container_depot.container_depot.eir_fitting_data import FITTINGS


def execute():
	frappe.reload_doc("container_depot", "doctype", "inspection_fitting_item")
	frappe.reload_doc("container_depot", "doctype", "inspection_fitting")
	frappe.reload_doc("container_depot", "doctype", "inspection")

	seeded = set()
	for code, compartment, printed_no, item_label, slot_label, value_type, options, uom, sequence in FITTINGS:
		exists = frappe.db.exists("Inspection Fitting Item", code)
		doc = (
			frappe.get_doc("Inspection Fitting Item", code)
			if exists
			else frappe.new_doc("Inspection Fitting Item")
		)
		doc.fitting_code = code
		doc.compartment = compartment
		doc.printed_no = printed_no
		doc.item_label = item_label
		doc.slot_label = slot_label or None
		doc.value_type = value_type
		doc.options = options or None
		doc.uom = uom or None
		doc.sequence = sequence
		doc.is_active = 1
		doc.save(ignore_permissions=True) if exists else doc.insert(ignore_permissions=True)
		seeded.add(code)

	stale = [
		r.name
		for r in frappe.get_all("Inspection Fitting Item", filters={"is_active": 1}, fields=["name"])
		if r.name not in seeded
	]
	for name in stale:
		frappe.db.set_value("Inspection Fitting Item", name, "is_active", 0)
