"""Rename Isotank Booking Item ``truck`` → ``truck_plate``.

The booking-item vehicle field was relabelled "Truck Number" → "Truck Plate" to
match the depot's paperwork and the existing ``truck_plate`` vocabulary used at
Gate Entry / SST (see ``api.register_gate_entry`` / ``api.sst_issue_order``).

After the model sync the doctype already carries the new ``truck_plate`` column;
the old ``truck`` column lingers with any legacy values. Copy those across so no
data is lost, then leave the orphan column for Frappe to ignore. Idempotent and
safe on fresh installs (where ``truck`` never existed).
"""

from __future__ import annotations

import frappe


def execute():
	cols = frappe.db.get_table_columns("Isotank Booking Item")
	if "truck" not in cols or "truck_plate" not in cols:
		return
	frappe.db.sql(
		"""
		UPDATE `tabIsotank Booking Item`
		SET truck_plate = truck
		WHERE truck IS NOT NULL AND truck != ''
		  AND (truck_plate IS NULL OR truck_plate = '')
		"""
	)
	frappe.db.commit()
