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

from container_depot.reset_data import (
	MASTER_DOCTYPES,
	ORPHAN_TRAILS,
	PARTY_DOCTYPES,
	_sweep_orphans,
	_wipe_parties,
)

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


class TestPartiesWipeLeavesTheItemCatalogue(FrappeTestCase):
	"""``parties=1`` membuang pihak + rate card, dan berhenti di situ.

	Gunanya persis itu: site produksi yang sudah dipakai uji coba mau Customer, kontrak
	dan tarifnya nol sementara katalog Item yang dikurasi tangan bertahan apa adanya.
	Satu doctype katalog yang bocor ke ``PARTY_DOCTYPES`` menghapus pekerjaan itu tanpa
	suara, jadi yang dipatok di sini sisi "tidak boleh ikut".

	Tidak ada ``commit`` di dalam ``_wipe_parties``; ``rollback`` di akhir mengembalikan
	site ke keadaan semula.
	"""

	def test_parties_go_and_the_catalogue_stays(self):
		before = {dt: frappe.db.count(dt) for dt in ("Item", "Branch", "Depot", "Cargo")}
		try:
			_wipe_parties()
			for dt in PARTY_DOCTYPES:
				with self.subTest(dt=dt):
					self.assertEqual(frappe.db.count(dt), 0)
			self.assertEqual(frappe.db.count("Item Price"), 0)
			for dt, n in before.items():
				with self.subTest(dt=dt):
					self.assertEqual(frappe.db.count(dt), n)
		finally:
			frappe.db.rollback()

	def test_the_two_lists_do_not_overlap(self):
		"""``_wipe_masters`` menjalankan keduanya — nama ganda = hapus dua kali, diam-diam."""
		self.assertEqual(set(PARTY_DOCTYPES) & set(MASTER_DOCTYPES), set())
