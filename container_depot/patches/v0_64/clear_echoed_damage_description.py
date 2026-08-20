import frappe


def execute():
	"""Kosongkan keterangan kerusakan yang sebenarnya cuma gema kode / nama item.

	Field ``damage_description`` dulu wajib, dan pengisi otomatisnya memakai deskripsi kode
	kerusakan ("Acceptable") lalu nama item checklist ("Front Top Rail") supaya validasi
	lolos. Hasilnya kolom Ket di EIR terbaca seperti catatan petugas padahal tidak ada yang
	menulisnya. Sekarang field-nya boleh kosong dan hanya diisi manusia — sisa gema itu
	dibersihkan.

	Hanya yang PERSIS sama dengan salah satu dari dua sumber otomatis itu yang dikosongkan,
	jadi catatan asli yang kebetulan pendek tetap aman. Aman diulang.
	"""
	frappe.db.sql(
		"""UPDATE `tabInspection Damage Entry` d
		   LEFT JOIN `tabInspection Damage Code` c ON c.name = d.damage_type
		   LEFT JOIN `tabInspection Checklist Item` i ON i.item_code = d.checklist_item
		   SET d.damage_description = ''
		   WHERE IFNULL(d.damage_description, '') <> ''
		     AND (d.damage_description = c.description OR d.damage_description = i.item_name)"""
	)
