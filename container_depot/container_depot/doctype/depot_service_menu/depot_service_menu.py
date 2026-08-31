import frappe
from frappe import _
from frappe.model.document import Document


class DepotServiceMenu(Document):
	def validate(self):
		self._dedupe_child_rows()

	def _dedupe_child_rows(self):
		"""Drop duplicate group / item rows so the menu stays a clean set."""
		seen_groups = set()
		kept_groups = []
		for row in self.get("item_groups") or []:
			if row.item_group and row.item_group not in seen_groups:
				seen_groups.add(row.item_group)
				kept_groups.append(row)
		self.set("item_groups", kept_groups)

		seen_items = set()
		kept_items = []
		for row in self.get("extra_items") or []:
			if row.item and row.item not in seen_items:
				seen_items.add(row.item)
				kept_items.append(row)
		self.set("extra_items", kept_items)


@frappe.whitelist()
def unmapped_menu_count() -> dict:
	"""Berapa menu AKTIF yang belum dibatasi apa pun. Isi Number Card "Menu Belum Dipetakan".

	Menu yang tidak punya satu pun Item Group maupun extra item tidak memfilter apa pun
	(``service_menu.is_real_menu``): pickernya tetap menampilkan seluruh katalog. Itu
	fallback yang disengaja — lebih baik picker terbuka daripada kosong melompong di
	install baru — tapi konsekuensinya kegagalannya SENYAP. Menu yang dikirim kosong oleh
	patch (v0_85 mengirim "Periodic Test" begitu, dan itu memang kontraknya) akan terus
	terlihat "ada" di daftar sementara tidak mengerjakan apa-apa, sampai ada yang sadar.
	Kartu inilah yang membuatnya terlihat.

	Dihitung di Python, bukan lewat filter kartu biasa: "tidak punya baris anak sama
	sekali" tidak bisa dinyatakan sebagai filter list Frappe — join hanya menemukan menu
	yang PUNYA baris cocok, bukan yang tidak punya.
	"""
	from container_depot.container_depot.service_menu import is_real_menu

	frappe.has_permission("Depot Service Menu", throw=True)
	names = frappe.get_all("Depot Service Menu", filters={"is_active": 1}, pluck="name")
	return {
		"value": len([n for n in names if not is_real_menu(n)]),
		"fieldtype": "Int",
		# Klik kartu -> daftar menunya. Daftar tidak bisa ikut disaring ke yang kosong saja
		# (alasan yang sama seperti di atas), jadi yang dibuka daftar menu aktif.
		"route": ["List", "Depot Service Menu"],
		"route_options": {"is_active": 1},
	}
