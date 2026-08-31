"""Jenis Cleaning di header ``Cleaning Order`` — dari mana nilainya datang.

Tiga register cuci yang selama ini hidup di Google Sheet (Methanol Rinse / PP Wash /
Steam Wash) hanya bisa pindah ke sistem kalau header order bisa menjawab "ini cuci jenis
apa" tanpa membuka tabel servicenya. Yang dikunci di sini adalah aturan pengisiannya:

* SETIAP order lahir sebagai ``Standard Cleaning`` — lewat EIR-In tank kotor maupun
  dibuat manual. Wash khusus adalah keputusan Admin Ops di tahap Service Setup, bukan
  sesuatu yang disimpulkan sistem dari isi tabel service,
* dokumen lama yang kolomnya masih kosong menyimpulkan jenisnya dari item service saat
  disimpan ulang (aturan yang sama dengan patch v0_84),
* pilihan manusia TIDAK PERNAH ditimpa,
* dan patch v0_84 merapikan data lama tanpa memblokir penyimpanan order lama.

Fixture dihapus di ``tearDown`` sehingga site kembali ke keadaan sebelum test.
"""

from __future__ import annotations

from unittest.mock import patch as mock_patch

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot import eir
from container_depot.patches.v0_84.backfill_cleaning_type import execute as backfill
from container_depot.tests.test_api import ensure_test_customer

_PRINCIPAL = "Cleaning Type Test Principal"
_PREFIX = "CTYPE"


def ensure_item(code: str, item_name: str, uom: str = "Nos") -> str:
	"""Item service cuci yang dipakai test. Idempoten; item yang sudah ada (dev site
	di-seed seed_dev) dipakai apa adanya dan tidak dihapus di tearDown."""
	if not frappe.db.exists("Item", code):
		frappe.get_doc({
			"doctype": "Item", "item_code": code, "item_name": item_name,
			"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups",
			"stock_uom": uom, "is_stock_item": 0, "is_sales_item": 1,
		}).insert(ignore_permissions=True)
	return code


class TestCleaningType(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.principal = ensure_test_customer(_PRINCIPAL)
		self._containers = []
		self._inspections = []

	def tearDown(self):
		for c in self._containers:
			orders = frappe.get_all("Cleaning Order", filters={"container": c}, pluck="name")
			if orders:
				frappe.db.delete("Cleaning Order Service", {"parent": ["in", orders]})
			frappe.db.delete("Cleaning Order", {"container": c})
			frappe.db.delete("Container Activity", {"container": c})
			frappe.db.delete("Container Movement", {"container": c})
			frappe.db.delete("Container", {"name": c})
		for ins in self._inspections:
			frappe.db.delete("Inspection", {"name": ins})
		frappe.db.commit()
		super().tearDown()

	# --- fixtures ---------------------------------------------------------------
	def _container(self, cno):
		name = frappe.get_doc({
			"doctype": "Container", "container_no": cno, "container_type": "ISO Tank",
			"status": "In_Depot", "principal": self.principal,
		}).insert(ignore_permissions=True).name
		self._containers.append(name)
		return name

	def _order(self, container, *, services=(), cleaning_type=None):
		doc = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "Service Setup",
			"cleaning_services": [{"cleaning_item": i} for i in services],
		})
		if cleaning_type:
			doc.cleaning_type = cleaning_type
		return doc.insert(ignore_permissions=True)

	# --- order dari EIR-In ------------------------------------------------------
	def test_eir_in_dirty_stamps_standard_cleaning(self):
		c = self._container(f"{_PREFIX}001")
		res = eir.create_eir(inspection_type="EIR-In", container=c, tank_status="Empty Dirty", submit=True)
		self._inspections.append(res["name"])
		orders = frappe.get_all("Cleaning Order", filters={"container": c}, fields=["name", "cleaning_type"])
		self.assertEqual(len(orders), 1)
		self.assertEqual(orders[0].cleaning_type, "Standard Cleaning")

	# --- order baru: SELALU Standard Cleaning -----------------------------------
	def test_new_order_is_standard_cleaning_even_with_a_special_wash_service(self):
		"""Memilih service Steam Wash TIDAK mengubah jenis di header.

		Jenis Cleaning adalah pernyataan Admin Ops tentang pekerjaan apa ini, bukan
		cerminan otomatis dari isi tabel service — satu order boleh memuat beberapa
		service sekaligus, jadi menyimpulkannya dari sana hanya akan menebak.
		"""
		ensure_item("INT-STEAM", "Steam Cleaning / Wash", uom="Hour")
		co = self._order(self._container(f"{_PREFIX}002"), services=["INT-STEAM"])
		self.assertEqual(co.cleaning_type, "Standard Cleaning")

	def test_new_order_without_any_wash_service_is_standard_cleaning(self):
		ensure_item("CLN-STANDARD", "Standard Clean")
		co = self._order(self._container(f"{_PREFIX}003"), services=["CLN-STANDARD"])
		self.assertEqual(co.cleaning_type, "Standard Cleaning")

	def test_legacy_blank_order_derives_its_type_on_resave(self):
		"""Jaring pengaman untuk dokumen lama saja: kolom yang kosong (field ini sempat
		dipensiunkan) diisi dari item service saat order disimpan ulang."""
		ensure_item("INT-STEAM", "Steam Cleaning / Wash", uom="Hour")
		co = self._order(self._container(f"{_PREFIX}008"), services=["INT-STEAM"])
		frappe.db.set_value("Cleaning Order", co.name, "cleaning_type", "", update_modified=False)
		co.reload()
		co.save(ignore_permissions=True)
		self.assertEqual(co.cleaning_type, "Steam Wash")

	# --- pilihan manusia menang --------------------------------------------------
	def test_manual_choice_is_never_overwritten(self):
		ensure_item("CLN-STANDARD", "Standard Clean")
		co = self._order(
			self._container(f"{_PREFIX}004"), services=["CLN-STANDARD"], cleaning_type="Steam Wash"
		)
		self.assertEqual(co.cleaning_type, "Steam Wash")
		co.save(ignore_permissions=True)  # simpan ulang: tetap pilihan manusia
		self.assertEqual(co.cleaning_type, "Steam Wash")

	# --- patch v0_84 atas data lama ---------------------------------------------
	def test_patch_maps_retired_values_and_derives_blanks(self):
		ensure_item("INT-PP-WASH", "P&P Wash")
		ensure_item("CLN-STANDARD", "Standard Clean")
		# Order lama dengan opsi yang sudah dipensiunkan (AC-4). Ditulis lewat db.set_value
		# karena "Chemical" memang bukan nilai valid lagi — persis keadaan data produksi.
		retired = self._order(self._container(f"{_PREFIX}005"), services=["CLN-STANDARD"])
		frappe.db.set_value("Cleaning Order", retired.name, "cleaning_type", "Chemical", update_modified=False)
		# Order lama tanpa jenis, tapi jelas memilih PP Wash (AC-5).
		derived = self._order(self._container(f"{_PREFIX}006"), services=["INT-PP-WASH"])
		frappe.db.set_value("Cleaning Order", derived.name, "cleaning_type", "", update_modified=False)
		# Order lama tanpa jenis dan tanpa service wash khusus → Standard Cleaning.
		plain = self._order(self._container(f"{_PREFIX}007"), services=["CLN-STANDARD"])
		frappe.db.set_value("Cleaning Order", plain.name, "cleaning_type", "", update_modified=False)
		stamps = {
			n: frappe.db.get_value("Cleaning Order", n, "modified")
			for n in (retired.name, derived.name, plain.name)
		}

		with mock_patch.object(frappe.db, "commit"):
			backfill()

		self.assertEqual(frappe.db.get_value("Cleaning Order", retired.name, "cleaning_type"), "Other")
		self.assertEqual(frappe.db.get_value("Cleaning Order", derived.name, "cleaning_type"), "PP Wash")
		self.assertEqual(
			frappe.db.get_value("Cleaning Order", plain.name, "cleaning_type"), "Standard Cleaning"
		)
		# Koreksi data, bukan perubahan bisnis: jejak audit tidak digeser.
		for name, before in stamps.items():
			self.assertEqual(frappe.db.get_value("Cleaning Order", name, "modified"), before)

		# AC-7 — run kedua tidak mengubah apa pun.
		with mock_patch.object(frappe.db, "commit"):
			backfill()
		self.assertEqual(frappe.db.get_value("Cleaning Order", retired.name, "cleaning_type"), "Other")
		self.assertEqual(frappe.db.get_value("Cleaning Order", derived.name, "cleaning_type"), "PP Wash")

		# AC-8 — order lama dibuka dan disimpan ulang tanpa perubahan: tidak ada error
		# validasi ("not a valid value") karena nilainya sudah dipetakan ke opsi yang ada.
		frappe.get_doc("Cleaning Order", retired.name).save(ignore_permissions=True)
