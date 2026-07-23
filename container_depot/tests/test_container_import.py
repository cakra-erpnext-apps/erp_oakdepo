"""Excel import for the Container Booking grid — parser and the two download endpoints.

The parser is pure (resolves an existing master but creates nothing), so it can run on
an unsaved form; these tests pin the normalisation, dedupe, default-condition and
invalid-condition branches, plus that the resolved link is returned when the container
already exists.
"""

from __future__ import annotations

import io

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.operations.doctype.container_booking import container_booking as cb
from container_depot.tests.test_api import ensure_test_customer

CUSTOMER = "Cont Import Co"
EXISTING = "CIMU1112223"


def _xlsx(rows: list) -> str:
	"""Build an .xlsx in memory, store it as a File, return its file_url."""
	import xlsxwriter

	buf = io.BytesIO()
	wb = xlsxwriter.Workbook(buf, {"in_memory": True})
	ws = wb.add_worksheet()
	for r, cells in enumerate(rows):
		ws.write_row(r, 0, cells)
	wb.close()
	f = frappe.get_doc({
		"doctype": "File",
		"file_name": "container_import_probe.xlsx",
		"is_private": 1,
		"content": buf.getvalue(),
	}).insert(ignore_permissions=True)
	return f.file_url


def _cleanup():
	# Frappe suffixes a duplicate file_name (…probe<hash>.xlsx), so match the prefix,
	# not the exact name, or the re-uploaded copies leak.
	frappe.db.delete("File", {"file_name": ("like", "container_import_probe%")})
	frappe.db.delete("Container Movement", {"container": EXISTING})
	frappe.db.delete("Container Activity", {"container": EXISTING})
	if frappe.db.exists("Container", EXISTING):
		frappe.db.delete("Container", {"name": EXISTING})
	if frappe.db.exists("Customer", CUSTOMER):
		frappe.db.delete("Customer", {"name": CUSTOMER})
	frappe.db.commit()


class TestContainerImport(FrappeTestCase):
	def setUp(self):
		_cleanup()
		self.customer = ensure_test_customer(CUSTOMER)

	def tearDown(self):
		# frappe.response is process-global; a download test leaves it set.
		frappe.response.clear()
		_cleanup()

	def test_parse_normalises_dedupes_defaults_and_rejects(self):
		url = _xlsx([
			["Container", "Condition"],          # header, skipped
			["cimu9990001", "empty dirty"],      # lower-case -> normalised
			["CIMU9990001", "LADEN"],            # duplicate container -> collapsed (first wins)
			["cimu9990002", ""],                 # blank condition -> default EMPTY CLEAN
			["cimu9990003", "SPARKLING"],        # unknown condition -> error, skipped
		])
		res = cb.parse_container_xlsx(url)

		self.assertEqual([r["container_no"] for r in res["rows"]], ["CIMU9990001", "CIMU9990002"])
		self.assertEqual(res["rows"][0]["condition"], "EMPTY DIRTY")
		self.assertEqual(res["rows"][1]["condition"], "EMPTY CLEAN")
		self.assertEqual(len(res["errors"]), 1)
		self.assertIn("SPARKLING", res["errors"][0])

	def test_parse_resolves_an_existing_container_link(self):
		frappe.get_doc({
			"doctype": "Container",
			"container_no": EXISTING,
			"container_type": "ISO Tank",
			"status": "Available",
			"principal": self.customer,
		}).insert(ignore_permissions=True)

		url = _xlsx([["Container", "Condition"], [EXISTING.lower(), "LADEN"]])
		res = cb.parse_container_xlsx(url)

		self.assertEqual(len(res["rows"]), 1)
		# The link is returned so the grid shows the container at once, not after Save.
		self.assertEqual(res["rows"][0]["container"], EXISTING)

	def test_parse_rejects_no_file(self):
		with self.assertRaises(frappe.ValidationError):
			cb.parse_container_xlsx(None)

	def test_template_and_master_are_downloads(self):
		cb.download_container_template()
		self.assertEqual(frappe.response.get("type"), "download")
		self.assertEqual(frappe.response.get("filename"), "container_import_template.xlsx")
		self.assertEqual(frappe.response["filecontent"][:2], b"PK")  # xlsx = zip magic

		frappe.response.clear()
		cb.download_container_master()
		self.assertEqual(frappe.response.get("type"), "download")
		self.assertEqual(frappe.response["filecontent"][:2], b"PK")
