from container_depot.patches.v0_64.clear_echoed_damage_description import execute as _sweep


def execute():
	"""Sapu ulang gema kode kerusakan di ``damage_description``.

	v0_64 sudah membersihkan sekali, tapi trigger Desk (``Inspection Damage Entry
	.damage_type``) masih menyalin deskripsi kode ke Description tiap kali kode dipilih —
	jadi gema itu tumbuh lagi sesudah patch pertama jalan. Triggernya sudah dibuang; ini
	membersihkan baris yang terlanjur terisi. Logikanya sama persis, aman diulang.
	"""
	_sweep()
