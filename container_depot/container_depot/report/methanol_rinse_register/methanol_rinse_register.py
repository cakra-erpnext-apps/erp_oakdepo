"""Methanol Rinse Register — pengganti sheet "Methanol Rinse Date" di Tank Inventory at KIM.

Isinya dibangun container_depot.container_depot.wash_register, yang dipakai
bersama ketiga register cuci: bentuk ketiga sheet itu identik, dan yang membedakan
hanya jenis + item service yang menandainya. Alasan register ini menampilkan order
yang belum selesai (bukan hanya yang sudah) ada di docstring modul tersebut.
"""

from __future__ import annotations

from container_depot.container_depot import wash_register


def execute(filters=None):
	return wash_register.execute(
		filters, wash_type="Methanol Rinse", item_code="INT-METHANOL", date_label="Methanol Rinse Date"
	)
