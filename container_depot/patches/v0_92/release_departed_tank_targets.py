"""Lepas stempel tenggat dari tank yang sudah tidak ditunggu booking mana pun.

``v0_91`` menstempel ulang setiap booking Tank Out yang belum dibatalkan — termasuk yang
``booking_status`` -nya sudah **Completed**, yang artinya semua tanknya sudah lewat gerbang dan
stempelnya sudah dilepas satu per satu oleh ``lift_on.release_on_gate_out``. Akibatnya tank yang
sudah keluar depot memegang lagi ``target_survey_on`` / ``target_lift_on``, dan sejak daftar
Letak Tank memimpin dengan hari terdekat, tank yang paling tidak relevan justru berdiri paling
atas dan tidak pernah turun.

Aturannya sudah diperbaiki di ``lift_on._booking_is_live``; patch ini membereskan sisanya.
Idempoten, dan tidak menyentuh tank yang stempelnya sah.
"""

from __future__ import annotations

import frappe

from container_depot.container_depot.lift_on import CONTAINER_FIELD, clear_target


def execute():
	rows = frappe.get_all(
		"Container",
		filters={CONTAINER_FIELD: ["is", "set"]},
		fields=["name", CONTAINER_FIELD],
	)
	for row in rows:
		booking = row.get(CONTAINER_FIELD)
		status, docstatus = frappe.db.get_value(
			"Container Booking", booking, ["booking_status", "docstatus"]
		) or (None, None)
		# Booking-nya lenyap, dibatalkan, atau sudah selesai: tidak ada lagi yang menunggu tank
		# ini, jadi tenggatnya dilepas — beserta salinannya di order yang masih terbuka.
		if status is None or status in ("Cancelled", "Completed") or docstatus == 2:
			clear_target(row.name, booking)
