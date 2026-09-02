"""Baris booking: ``estimation_date`` (rencana) → ``realisation_date`` (kenyataan).

Dua field ini bernama mirip tapi menjawab pertanyaan yang berbeda, dan itulah sebabnya yang
lama dibuang alih-alih diganti nama. ``estimation_date`` adalah RENCANA per baris — turunan
dari Plan Date di header, dengan default hari ini. ``realisation_date`` adalah KENYATAAN:
tanggal bon container itu benar-benar terbit, yang tidak diketik siapa pun dan dihitung
ulang dari bon-nya (``container_booking.refresh_line_realisation``).

Karena itu isinya TIDAK dipindahkan: menyalin rencana ke kolom kenyataan akan membuat setiap
baris lama mengaku sudah dibon padahal belum. Yang dipindahkan justru ke arah sebaliknya —
ke header:

1. ``Container Booking.plan_date`` diisi dari tanggal baris paling awal untuk booking yang
   header-nya masih kosong. Ini yang menyelamatkan rencana booking lama, sekaligus menjaga
   prioritas lift-on: sejak sekarang ``lift_on.sync_booking_targets`` membaca plan_date, dan
   tanpa langkah ini setiap booking Tank Out lama kehilangan deadline-nya. Diambil yang
   PALING AWAL karena itu hari yard harus siap.
2. Kolom lamanya dibuang.
3. ``realisation_date`` dihitung dari bon yang memang sudah terbit.
4. Stempel ``target_lift_on`` di container disinkronkan ulang untuk booking keluar yang masih
   hidup — baris yang dulu boleh punya tanggal sendiri-sendiri sekarang ikut satu plan_date.

Idempoten: langkah 1-2 dijaga keberadaan kolom lama, 3-4 menghitung ulang dari keadaan
sekarang.
"""

from __future__ import annotations

import frappe

OLD = "estimation_date"
TABLE = "Container Booking Item"


def execute():
	if OLD in frappe.db.get_table_columns(TABLE):
		frappe.db.sql(
			"""
			UPDATE `tabContainer Booking` b
			JOIN (
				SELECT parent, MIN(estimation_date) AS planned
				FROM `tabContainer Booking Item`
				WHERE parenttype = 'Container Booking' AND estimation_date IS NOT NULL
				GROUP BY parent
			) i ON i.parent = b.name
			SET b.plan_date = i.planned
			WHERE b.plan_date IS NULL
			"""
		)
		frappe.db.sql_ddl("ALTER TABLE `tabContainer Booking Item` DROP COLUMN `estimation_date`")
		frappe.db.commit()

	from container_depot.container_depot import lift_on
	from container_depot.container_depot.doctype.container_booking.container_booking import (
		refresh_line_realisation,
	)

	# Only bookings that ever had a bon can carry a realisation date.
	issued = frappe.get_all(
		"Booking Code", filters={"state": "Used"}, pluck="booking", distinct=True
	)
	for booking in {b for b in issued if b}:
		refresh_line_realisation(booking)

	for name in frappe.get_all(
		"Container Booking",
		filters={"direction": "Tank Out", "docstatus": ["<", 2]},
		pluck="name",
	):
		doc = frappe.get_doc("Container Booking", name)
		if doc.get("booking_status") != "Cancelled":
			lift_on.sync_booking_targets(doc)
	frappe.db.commit()
