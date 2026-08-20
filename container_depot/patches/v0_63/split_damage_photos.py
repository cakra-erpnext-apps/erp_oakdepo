import frappe

# A photo belongs to the checklist card of the same EIR when that card exists — the rule
# ``eir._split_damage_photos`` applies on every save from now on. The card's codes are not
# the test: a part recorded as "Acceptable" was still walked up to and photographed there.
_ON_A_CARD = """EXISTS (
	SELECT 1 FROM `tabInspection Damage Entry` d
	WHERE d.parent = p.parent AND d.parenttype = 'Inspection'
	  AND d.checklist_item = p.checklist_item
)"""


def execute():
	"""Pindahkan foto yang diambil di kartu checklist ke tabel Foto Kerusakan.

	Foto kartu dulu ikut menumpuk di ``item_photos`` bersama foto keliling tank, jadi daftar
	Foto Inspeksi tercampur dan satu item checklist tidak punya albumnya sendiri. Baris yang
	dipindah mempertahankan ``name`` aslinya — beda tabel, jadi tidak bentrok — sehingga
	patch ini aman diulang (INSERT IGNORE + DELETE dengan syarat sama).

	Yang tetap tinggal: foto cepat yang belum disortir (tanpa checklist item) dan foto pada
	bagian yang tidak punya baris checklist sama sekali.
	"""
	if not frappe.db.table_exists("Inspection Damage Photo"):
		return

	frappe.db.sql(
		f"""INSERT IGNORE INTO `tabInspection Damage Photo`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			 parent, parentfield, parenttype, checklist_item, area, item_name, photo)
		SELECT p.name, p.creation, p.modified, p.modified_by, p.owner, p.docstatus, p.idx,
		       p.parent, 'damage_photos', 'Inspection',
		       p.checklist_item, p.area, p.item_name, p.photo
		FROM `tabInspection Item Photo` p
		WHERE p.parenttype = 'Inspection'
		  AND IFNULL(p.checklist_item, '') <> ''
		  AND {_ON_A_CARD}""")
	frappe.db.sql(
		f"""DELETE p FROM `tabInspection Item Photo` p
		WHERE p.parenttype = 'Inspection'
		  AND IFNULL(p.checklist_item, '') <> ''
		  AND {_ON_A_CARD}""")
