"""Prioritas worklist pindah ke tanggal survey — isi stempelnya untuk booking yang sudah ada.

Sampai sekarang satu-satunya tenggat yang dikenal depot adalah ``plan_date`` (rencana pickup),
dan itulah yang mengurutkan semua worklist. Padahal persiapannya — cleaning, M&R, menurunkan
tank, EIR-Out — harus selesai di hari **survey**, bukan di hari truknya datang. Booking sudah
lama membawa kedua tanggal itu; yang belum ada cuma jalur agar tanggal survey ikut menempel ke
tank dan ke order yang masih memegangnya (lihat ``lift_on.push_to_open_orders``).

Patch ini menjalankan ulang stempel itu untuk setiap booking keluar yang masih hidup, sehingga
data lama tidak menunggu booking-nya disentuh dulu baru punya prioritas yang benar. Idempoten:
yang ditulis persis sama dengan yang ditulis kode berjalan.

Tank yang sudah tidak dipegang booking hidup mana pun tidak disentuh — stempelnya memang sudah
dilepas ``clear_target`` waktu booking-nya batal atau tank-nya keluar gerbang.
"""

from __future__ import annotations

import frappe


def execute():
	for dt in ("container", "inspection", "cleaning_order", "repair_order", "survey_order_tank"):
		frappe.reload_doc("container_depot", "doctype", dt)

	from container_depot.container_depot.lift_on import sync_booking_targets

	bookings = frappe.get_all(
		"Container Booking",
		filters={"direction": "Tank Out", "docstatus": ["!=", 2], "booking_status": ["!=", "Cancelled"]},
		pluck="name",
	)
	for name in bookings:
		# Lewat dokumennya, bukan SQL: `sync_booking_targets` juga yang melepas stempel milik
		# baris yang sudah tidak ada lagi, jadi satu panggilan ini sekaligus merapikan sisa.
		sync_booking_targets(frappe.get_doc("Container Booking", name))
