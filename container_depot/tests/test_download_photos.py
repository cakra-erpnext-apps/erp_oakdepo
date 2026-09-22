"""Tests for photo download and timestamp functionality."""

from __future__ import annotations

import base64
import io
import zipfile

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.api import download_doc_photos
from container_depot.tests.test_api import ensure_test_customer

ONE_PIXEL_PNG = base64.b64decode(
	"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _create_test_file(name: str) -> "frappe.Document":
	return frappe.get_doc({
		"doctype": "File",
		"file_name": name,
		"is_private": 1,
		"content": ONE_PIXEL_PNG,
	}).insert(ignore_permissions=True)


class TestDownloadPhotos(FrappeTestCase):
	def setUp(self):
		self.principal = ensure_test_customer("Download Test Customer")
		self.container = frappe.get_doc({
			"doctype": "Container",
			"container_no": "DLTD2000001",
			"container_type": "ISO Tank",
			"status": "In_Depot",
			"principal": self.principal,
		}).insert(ignore_permissions=True).name

	def tearDown(self):
		frappe.db.rollback()

	def test_eir_download_photos_zip(self):
		file1 = _create_test_file("eir-test-1.png")
		doc = frappe.new_doc("Inspection")
		doc.inspection_type = "EIR-In"
		doc.container = self.container
		doc.inspector = "Administrator"
		doc.tank_status = "Empty Clean"
		doc.append("exterior_photos", {
			"photo_view": "Front",
			"photo_url": file1.file_url,
		})
		doc.insert(ignore_permissions=True)

		# Verify timestamp was populated
		self.assertTrue(bool(doc.exterior_photos[0].timestamp))

		# Execute download
		download_doc_photos("Inspection", doc.name)
		self.assertEqual(frappe.response.get("type"), "download")
		self.assertTrue(frappe.response.get("filename").endswith(".zip"))
		content = frappe.response.get("filecontent")
		self.assertTrue(len(content) > 0)

		# Verify zip contents
		with zipfile.ZipFile(io.BytesIO(content)) as zf:
			names = zf.namelist()
			self.assertEqual(len(names), 1)
			self.assertTrue("exterior" in names[0].lower())

	def test_cleaning_order_photos_and_timestamp(self):
		file1 = _create_test_file("qc-test-1.png")
		co = frappe.new_doc("Cleaning Order")
		co.container = self.container
		co.container_principal = self.principal
		co.cleaning_type = "Standard Cleaning"
		co.append("qc_photos", {
			"photo": file1.file_url,
			"caption": "Tank Bersih",
		})
		co.insert(ignore_permissions=True)

		# Verify timestamp was stamped
		self.assertTrue(bool(co.qc_photos[0].timestamp))

		download_doc_photos("Cleaning Order", co.name)
		self.assertEqual(frappe.response.get("type"), "download")
		content = frappe.response.get("filecontent")
		with zipfile.ZipFile(io.BytesIO(content)) as zf:
			self.assertEqual(len(zf.namelist()), 1)

	def test_repair_order_photos_and_timestamp(self):
		file1 = _create_test_file("ro-test-1.png")
		ro = frappe.new_doc("Repair Order")
		ro.container = self.container
		ro.principal = self.principal
		ro.append("used_items", {
			"item": "Test Service Item",
			"line_type": "Jasa",
			"qty": 1,
		})
		ro.append("work_photos", {
			"photo": file1.file_url,
			"item": "Test Service Item",
			"caption": "Pekerjaan Selesai",
		})
		# Insert without stock validations for test
		ro.flags.ignore_validate = True
		ro.flags.ignore_links = True
		ro.insert(ignore_permissions=True)

		download_doc_photos("Repair Order", ro.name)
		self.assertEqual(frappe.response.get("type"), "download")
		content = frappe.response.get("filecontent")
		with zipfile.ZipFile(io.BytesIO(content)) as zf:
			self.assertEqual(len(zf.namelist()), 1)

