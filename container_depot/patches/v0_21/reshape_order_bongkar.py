"""Reshape Order Bongkar to reuse the Container Booking Item child.

Order Bongkar now carries its containers in the booking's own Container Booking Item
child (truck / driver / R-O / condition / cargo / Tgl. Bongkar per row) instead of the
separate Order Container Item. This:

* drops the now-redundant singular header columns (these moved per-row), and
* clears the old Order Container Item rows that belonged to Order Bongkar — Order Muat
  (Tank Out) keeps its own Order Container Item rows, so the table itself stays.

Runs pre_model_sync so the column drops happen before the schema reconcile. Idempotent
(DROP COLUMN IF EXISTS; the row delete is a no-op once clear).
"""

import frappe

PARENT = "tabOrder Bongkar"
HEADER_DROP = ("ro", "tanggal_bongkar", "truck_plate", "angkutan", "driver_name", "driver_phone")


def execute():
	if frappe.db.table_exists("Order Container Item"):
		# Order Bongkar no longer uses Order Container Item — drop its orphaned rows.
		frappe.db.delete("Order Container Item", {"parenttype": "Order Bongkar"})
	if frappe.db.table_exists("Order Bongkar"):
		for col in HEADER_DROP:
			frappe.db.sql_ddl(f"ALTER TABLE `{PARENT}` DROP COLUMN IF EXISTS `{col}`")
	frappe.db.commit()
