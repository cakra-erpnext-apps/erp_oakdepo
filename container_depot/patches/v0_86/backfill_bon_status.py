"""Isi ``Container Booking.bon_status`` / ``bon_summary`` untuk booking yang sudah ada.

Kedua field ini baru: sebelumnya "booking ini bon-nya sudah terbit semua belum?" hanya bisa
dijawab dengan membuka booking-nya satu per satu, karena bon (Order Bongkar / Order Muat)
hidup di doctype lain dan hanya nyambung lewat Booking Code. Nilainya dihitung ulang dari
Booking Code — sumber yang sama yang dipakai runtime — jadi patch ini tidak menebak apa pun,
hanya menuliskan jawaban yang selama ini harus dihitung manual.

Hanya booking yang punya Booking Code hidup (``Active`` / ``Used``) yang disentuh: draft
belum menerbitkan kode, dan booking yang sudah dibatalkan kodenya sudah di-void — keduanya
memang tidak menunggu bon apa pun, dan nilai kosong itulah yang benar untuk mereka.

Idempoten: ``refresh_bon_status`` menghitung dari keadaan sekarang, jadi run kedua menulis
nilai yang sama. Pakai ``update_modified=False`` (di dalam helper-nya) supaya koreksi data
ini tidak membuat ratusan booking lama tampak baru saja disunting.
"""

from __future__ import annotations

import frappe

from container_depot.container_depot.doctype.container_booking.container_booking import (
	refresh_bon_status,
)


def execute():
	bookings = frappe.get_all(
		"Booking Code",
		filters={"state": ["in", ("Active", "Used")], "booking": ["is", "set"]},
		distinct=True,
		pluck="booking",
	)
	for booking in bookings:
		refresh_bon_status(booking)
	frappe.db.commit()
