"""Steam Wash Register — pengganti sheet "Steam Wash Date" di Tank Inventory at KIM.

Isinya dibangun container_depot.container_depot.wash_register, yang dipakai
bersama ketiga register cuci: bentuk ketiga sheet itu identik, dan yang membedakan
hanya jenis + item service yang menandainya. Alasan register ini menampilkan order
yang belum selesai (bukan hanya yang sudah) ada di docstring modul tersebut.
"""

from __future__ import annotations

from container_depot.container_depot import wash_register


def execute(filters=None):
	return wash_register.execute(
		filters, wash_type="Steam Wash", item_code="INT-STEAM", date_label="Steam Wash Date"
	)
