"""Render guard for the four SPK (crew work sheet) print formats.

Rendered from unsaved documents (``frappe.get_print(doc=...)``), so nothing is written and
nothing needs cleaning up. Pins the logic the templates carry: Instruksi Cleaning becomes
one step per line, the Repair Order sheet turns into the Periodic Test sheet by job_type,
an owner-rejected line never reaches the technician, and the survey lists its live tanks.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase


def _render(doc, fmt):
	return frappe.get_print(doc.doctype, doc.name, print_format=fmt, doc=doc)


class TestSpkPrint(FrappeTestCase):
	def test_cleaning_instructions_become_steps(self):
		doc = frappe.new_doc("Cleaning Order")
		doc.container_no = "SPKU0000001"
		doc.cleaning_instructions = "Semprot air panas 80c 1.5 jam\n\nKuras tank, saluran dan pompa"
		doc.append("cleaning_services", {"line_type": "Jasa", "item_name": "Standard Clean"})
		html = _render(doc, "SPK Cleaning")
		self.assertIn("Cara Pencucian", html)
		self.assertIn("Status Tank : Acceptable / Rework", html)
		self.assertIn("Semprot air panas 80c 1.5 jam", html)
		self.assertIn("Kuras tank, saluran dan pompa", html)
		self.assertIn("#. L.E.L", html)
		self.assertIn("PERINTAH CUCI TANK CONTAINER", html)

	def test_cleaning_without_instructions_lists_its_services(self):
		doc = frappe.new_doc("Cleaning Order")
		doc.append("cleaning_services", {"line_type": "Jasa", "item_name": "Steam Cleaning / Wash"})
		self.assertIn("Steam Cleaning / Wash", _render(doc, "SPK Cleaning"))

	def test_repair_order_sheet_follows_job_type(self):
		doc = frappe.new_doc("Repair Order")
		doc.job_type = "Repair"
		doc.append("used_items", {"line_type": "Jasa", "item_name": "Weld Shell Patch", "quantity": 1})
		doc.append("used_items", {"line_type": "Part", "item_name": "Rejected Gasket", "decision": "Rejected"})
		html = _render(doc, "SPK Repair Order")
		self.assertIn("PERINTAH PERBAIKAN TANK CONTAINER", html)
		self.assertIn("Weld Shell Patch", html)
		self.assertNotIn("Rejected Gasket", html)

		doc.job_type = "Periodic Test"
		html = _render(doc, "SPK Repair Order")
		self.assertIn("PERINTAH PERIODIC TEST TANK CONTAINER", html)
		self.assertIn("Test Pressure", html)

	def test_leak_check_and_survey_render(self):
		leak = frappe.new_doc("Leak Check")
		leak.container_no = "SPKU0000002"
		self.assertIn("Titik Pemeriksaan", _render(leak, "SPK Leak Check"))

		survey = frappe.new_doc("Survey Order")
		survey.append("tanks", {"container_no": "SPKU0000003", "status": "Waiting Lowering"})
		survey.append("tanks", {"container_no": "SPKU0000004", "status": "Cancelled"})
		html = _render(survey, "SPK Survey")
		self.assertIn("SPKU0000003", html)
		self.assertNotIn("SPKU0000004", html)

	def test_signature_fields_override_the_automatic_names(self):
		"""Tanda Tangan SPK: a filled field wins, an empty one keeps the automatic name."""
		doc = frappe.new_doc("Cleaning Order")
		html = _render(doc, "SPK Cleaning")
		self.assertIn("Supervisor Operasional", html)

		doc.spk_crew_name = "Andi Crew"
		doc.spk_qc_name = "Budi QC"
		doc.spk_signer_name = "Citra Spv"
		doc.spk_signer_title = "Kepala Depo"
		html = _render(doc, "SPK Cleaning")
		for text in ("Andi Crew", "Budi QC", "Citra Spv", "Kepala Depo"):
			self.assertIn(text, html)
		self.assertNotIn("Supervisor Operasional", html)

		for doctype, fmt in (("Repair Order", "SPK Repair Order"), ("Survey Order", "SPK Survey"), ("Leak Check", "SPK Leak Check")):
			other = frappe.new_doc(doctype)
			if doctype == "Repair Order":
				other.job_type = "Repair"
			other.spk_qc_name = "Dodi QC"
			other.spk_signer_title = "Manajer Operasional"
			html = _render(other, fmt)
			self.assertIn("Dodi QC", html, fmt)
			self.assertIn("Manajer Operasional", html, fmt)
