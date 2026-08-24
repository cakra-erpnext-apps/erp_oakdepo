"""Foto PWA harus bisa dilihat rekan sedepot, bukan cuma yang mengunggah.

File privat yang tidak menempel ke dokumen mana pun hanya boleh dibuka pemiliknya —
itulah 403 yang muncul di PWA. container_depot/files.py menempelkannya saat dokumennya
disimpan; dua tes ini menjaga penempelan itu dan akibatnya pada izin baca.
"""

from __future__ import annotations

import base64

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.files import attach_to_document
from container_depot.tests.test_api import ensure_test_customer


# PNG 1x1 sungguhan: Frappe mengoptimalkan gambar saat File disimpan, jadi isinya harus
# benar-benar gambar — bukan sekadar nama berakhiran .png.
ONE_PIXEL_PNG = base64.b64decode(
	"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _orphan_file(name: str) -> "frappe.Document":
	"""File privat tanpa tuan — persis yang dihasilkan upload_file dari PWA."""
	return frappe.get_doc({
		"doctype": "File",
		"file_name": name,
		"is_private": 1,
		"content": ONE_PIXEL_PNG,
	}).insert(ignore_permissions=True)


class TestAttachPwaFiles(FrappeTestCase):
	def setUp(self):
		self.container = frappe.get_doc({
			"doctype": "Container",
			"container_no": "FILE2000001",
			"container_type": "ISO Tank",
			"status": "In_Depot",
			"principal": ensure_test_customer("File Attach Test Principal"),
		}).insert(ignore_permissions=True).name

	def _eir(self, *photo_urls):
		doc = frappe.new_doc("Inspection")
		doc.inspection_type = "EIR-In"
		doc.container = self.container
		doc.inspector = "Administrator"
		doc.tank_status = "Empty Clean"
		for url in photo_urls:
			doc.append("item_photos", {"checklist_item": "01", "photo": url})
		return doc.insert(ignore_permissions=True)

	def test_saving_a_document_adopts_the_files_it_points_at(self):
		photo = _orphan_file("pwa-photo.png")
		signature = _orphan_file("pwa-signature.png")
		doc = self._eir(photo.file_url)
		doc.inspector_signature = signature.file_url
		doc.save(ignore_permissions=True)

		for f in (photo, signature):
			f.reload()
			self.assertEqual(f.attached_to_doctype, "Inspection")
			self.assertEqual(f.attached_to_name, doc.name)

	def test_an_unreferenced_file_is_left_alone(self):
		stray = _orphan_file("bukan-milik-eir.png")
		doc = self._eir()
		attach_to_document(doc)

		stray.reload()
		self.assertFalse(stray.attached_to_doctype)

	def tearDown(self):
		frappe.db.rollback()
