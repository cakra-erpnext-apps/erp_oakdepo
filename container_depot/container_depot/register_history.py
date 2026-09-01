"""Riwayat satu tank di balik keempat register.

Sebuah baris register menjawab "order ini bagaimana". Yang ditanyakan berikutnya hampir
selalu "tank ini SEBELUMNYA bagaimana" — sudah berapa kali di-steam bulan ini, uji
berkalanya kapan terakhir, dan yang mana yang sudah ditagih. Di sheet, jawabannya adalah
menggulung ratusan baris mencari nomor tank yang sama.

Datanya diambil dari report registernya sendiri, dengan filter container — bukan query
baru. Jadi dialog riwayat tidak akan pernah menyatakan sesuatu yang berbeda dari tabel
yang sedang dibaca orang: aturan "order mana milik jenis ini" cuma ada di satu tempat.
"""

from __future__ import annotations

import frappe
from frappe import _

# Nama register -> cara membacanya. Nama ini yang dikirim tombol di tiap report.
_WASH = {
	"Steam Wash": ("INT-STEAM", "Steam Wash Date"),
	"PP Wash": ("INT-PP-WASH", "PP Wash Date"),
	"Methanol Rinse": ("INT-METHANOL", "Methanol Rinse Date"),
}

# Kolom yang tidak berguna di dialog riwayat: nomor tank sudah jadi judulnya, dan
# principal tidak berubah dari baris ke baris untuk tank yang sama.
_DROP = {"tank_no", "principal"}


@frappe.whitelist()
def tank_history(container: str, register: str) -> dict:
	"""Semua order tank ini di register tersebut, terbaru di atas."""
	if register in _WASH:
		frappe.has_permission("Cleaning Order", throw=True)
		from container_depot.container_depot import wash_register

		item_code, date_label = _WASH[register]
		columns, rows, *_rest = wash_register.execute(
			{"container": container}, wash_type=register, item_code=item_code,
			date_label=date_label,
		)
	elif register == "Periodic Test":
		frappe.has_permission("Repair Order", throw=True)
		from container_depot.container_depot.report.periodic_test_register import (
			periodic_test_register,
		)

		columns, rows, *_rest = periodic_test_register.execute({"container": container})
	else:
		frappe.throw(_("Register tidak dikenal: {0}").format(register))

	return {
		"container": container,
		"register": register,
		"columns": [c for c in columns if c["fieldname"] not in _DROP],
		# Terbaru di atas: yang dicari orang saat membuka riwayat adalah kejadian terakhir,
		# kebalikan dari registernya sendiri yang kronologis seperti sheet aslinya.
		"rows": list(reversed(rows)),
	}
