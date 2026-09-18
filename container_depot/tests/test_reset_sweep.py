"""Reset harus membuang SETIAP riwayat yang dokumennya sudah tidak ada.

Aturan lamanya adalah sebuah daftar: `_sweep_orphans` hanya membuang jejak milik doctype
yang reset ini hapus, dan daftar itu cuma memuat doctype transaksi. Akibatnya satu reset
``masters=1`` meninggalkan 252 `Notification Log` milik Depot Contract yang sudah hilang
(ditemukan 2026-09-18), dan daftar berikutnya akan ketinggalan doctype berikutnya.

Aturannya sekarang per BARIS, bukan per doctype: riwayat tanpa dokumen adalah sampah. Yang
dipatok di sini justru sisi yang berbahaya — riwayat dokumen yang MASIH ADA tidak boleh
ikut terbawa, karena sapuan yang kelewat rajin menghapus komentar orang.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.reset_data import ORPHAN_TRAILS, _sweep_orphans

GHOST = "RSW-doc-yang-tidak-pernah-ada"


def _notif(document_name: str) -> str:
	return frappe.get_doc({
		"doctype": "Notification Log",
		"subject": "reset sweep probe",
		"for_user": "Administrator",
		"type": "Alert",
		"document_type": "Depot",
		"document_name": document_name,
	}).insert(ignore_permissions=True).name


class TestResetSweepsEveryOrphan(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		# Dokumen hidup untuk sisi "jangan disentuh". Depot dipilih karena seeder selalu
		# menyediakannya dan ia bukan submittable, jadi probe-nya murah.
		cls.live = frappe.get_all("Depot", limit=1, pluck="name")
		cls.skip = not cls.live

	def test_a_trail_pointing_at_a_missing_document_is_swept(self):
		name = _notif(GHOST)
		_sweep_orphans()
		self.assertFalse(frappe.db.exists("Notification Log", name))

	def test_a_trail_pointing_at_a_living_document_survives(self):
		if self.skip:
			self.skipTest("site tanpa Depot — tidak ada dokumen hidup untuk diuji")
		name = _notif(self.live[0])
		try:
			_sweep_orphans()
			self.assertTrue(frappe.db.exists("Notification Log", name))
		finally:
			frappe.delete_doc("Notification Log", name, ignore_permissions=True, force=True)
			frappe.db.commit()

	def test_every_trail_names_the_column_holding_the_document_name(self):
		"""Sapuannya mem-``LEFT JOIN`` lewat kolom ini; salah nama = query mati saat reset."""
		for trail, dt_col, name_col in ORPHAN_TRAILS:
			with self.subTest(trail=trail):
				columns = {c.get("Field") for c in frappe.db.sql(f"desc `tab{trail}`", as_dict=True)}
				self.assertIn(dt_col, columns)
				self.assertIn(name_col, columns)
