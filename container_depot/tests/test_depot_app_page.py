"""Halaman bagikan APK (``/depot-app``) selalu menunjuk APK publik TERBARU.

Itu satu-satunya kontrak halaman ini: rilis berikutnya cukup di-upload, tanpa deploy.
Kalau urutannya salah, orang memasang versi lama tanpa sadar.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.install import hide_apk_shortcut
from container_depot.www.depot_app import get_apk, get_context


def _apk(name, is_private=0):
	return frappe.get_doc(
		{
			"doctype": "File",
			"file_name": name,
			"is_private": is_private,
			"content": "dummy",
		}
	).insert(ignore_permissions=True)


class TestDepotAppPage(FrappeTestCase):
	def setUp(self):
		self.files = []

	def tearDown(self):
		for f in self.files:
			frappe.delete_doc("File", f.name, force=True, ignore_permissions=True)

	def test_picks_the_newest_public_apk(self):
		old = _apk("depot-oak-test-1.0.0.apk")
		new = _apk("depot-oak-test-1.1.0.apk")
		# `creation` tie-breaks to the second row only if it is genuinely later.
		frappe.db.set_value("File", old.name, "creation", "2020-01-01 00:00:00", update_modified=False)
		self.files = [old, new]

		self.assertEqual(get_apk().file_name, "depot-oak-test-1.1.0.apk")

	def test_file_url_is_url_encoded(self):
		# Upload lewat Desk sering menghasilkan nama bersspasi; spasi mentah di href
		# bikin unduhan gagal di HP.
		self.files = [_apk("Depot OAK test.apk")]

		self.assertEqual(get_apk().file_url, "/files/Depot%20OAK%20test.apk")

	def test_private_apk_is_not_offered(self):
		# Private files need a session to download — useless as a share link.
		self.files = [_apk("depot-oak-test-private.apk", is_private=1)]

		# Tidak assertIsNone: site bisa saja sudah punya APK publik asli.
		found = get_apk()
		self.assertNotEqual(found and found.file_name, "depot-oak-test-private.apk")

	def test_a_site_can_hide_the_page(self):
		# Staging: URL target TWA dipatri ke dalam APK, jadi APK dari staging tetap
		# membuka produksi. Halaman + shortcut-nya disembunyikan, bukan dibuat APK kedua.
		frappe.conf.hide_apk_page = 1
		self.addCleanup(frappe.conf.pop, "hide_apk_page", None)

		with self.assertRaises(frappe.PageDoesNotExistError):
			get_context(frappe._dict())

	def test_hiding_the_page_drops_the_workspace_card(self):
		shortcut = {"parent": "Container Depot", "url": "/depot-app"}
		if not frappe.db.exists("Workspace Shortcut", shortcut):
			self.skipTest("workspace not imported on this site")
		frappe.conf.hide_apk_page = 1
		self.addCleanup(frappe.conf.pop, "hide_apk_page", None)

		hide_apk_shortcut()

		self.assertFalse(frappe.db.exists("Workspace Shortcut", shortcut))
