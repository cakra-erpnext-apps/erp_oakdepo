"""Cleaning Register — semua Cleaning Order dalam satu daftar, apa pun jenisnya.

Ketiga register cuci (Steam / PP / Methanol) hanya memuat jenisnya sendiri, jadi order
Standard Cleaning dan Other tidak muncul di register mana pun. Isinya dibangun
container_depot.container_depot.wash_register tanpa jenis.
"""

from __future__ import annotations

from container_depot.container_depot import wash_register


def execute(filters=None):
	return wash_register.execute(
		filters, wash_type=None, item_code=None, date_label="Tanggal Selesai"
	)
