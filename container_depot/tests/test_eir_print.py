"""Render guard for the EIR print format (container_depot/print_format/eir).

The template is pure Jinja with master-driven legends + a 50-row grid joined to
damage_log; this test catches template breakage and confirms the derived ISO 6346
prefix, the code legend and the checklist grid all render for a Desk- or PWA-built
Inspection (both share the same checklist_item linkage).
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.tests.test_api import ensure_test_customer


def _make_container(cno):
	return frappe.get_doc({
		"doctype": "Container",
		"container_no": cno,
		"container_type": "ISO Tank",
		"status": "In_Depot",
		"principal": ensure_test_customer("EIR Print Test Principal"),
	}).insert(ignore_permissions=True).name


class TestEirPrintFormat(FrappeTestCase):
	def test_eir_format_renders(self):
		c = _make_container("EIRP2000003")
		doc = frappe.new_doc("Inspection")
		doc.inspection_type = "EIR-In"
		doc.container = c
		doc.inspector = "Administrator"
		doc.tank_status = "Empty Dirty"
		doc.vessel = "MV TEST"
		# A retired checklist item: still happened to this tank, so it prints in its own
		# "kerusakan lain" table rather than in the grid.
		doc.append("damage_log", {
			"checklist_item": "01",
			"component": "1. Underside",
			"area": "UNDERSIDE",
			"damage_type": "11",
			"damage_description": "dent on underside",
			"severity": "Minor",
		})
		# An ACTIVE part — its codes land in the grid and its words under CATATAN TEMUAN.
		doc.append("damage_log", {
			"checklist_item": "A01",
			"component": "Front Top Rail",
			"area": "Front",
			"damage_type": "11",
			"repair_code": "30",
			"damage_description": "penyok 12cm sisi kiri",
			"severity": "Minor",
		})
		# Kelengkapan tank — the printed sheet's fill-in boxes, not defects.
		doc.append("fittings", {
			"fitting_item": "BDC-09-IN",
			"compartment": "Bottom Discharge",
			"printed_no": "9",
			"item_label": "Steam Pipe",
			"slot_label": "IN",
			"value": "3",
			"uom": "inch",
		})
		doc.insert(ignore_permissions=True)

		html = frappe.get_print("Inspection", doc.name, print_format="EIR Format")

		self.assertIn("EQUIPMENT INTERCHANGE RECEIPT", html)  # kop
		self.assertIn("EIRP", html)                            # ISO 6346 prefix derived
		# The legend headings are lower-cased in the template and upper-cased by CSS.
		self.assertIn("Damage codes", html)                    # legend from master
		self.assertIn("Repair codes", html)
		self.assertIn("Underside", html)                       # 50-row checklist grid
		self.assertIn("dent on underside", html)               # damage_log joined by checklist_item
		self.assertIn("KELENGKAPAN TANK", html)                # fittings block
		self.assertIn("Steam Pipe", html)
		# Header block mirrors the OAK paper form's field grid.
		for caption in ("Date of Inspection", "Tank No", "Max Gross Weight", "Inspect Location",
						"Shipper / Consignee", "EMKL", "Reference No.", "Seal"):
			self.assertIn(caption, html)
		self.assertIn("EIR fill / inspect by", html)           # sign-off per the paper form
		# The words behind a code live under CATATAN TEMUAN, not in a grid column that would
		# be blank for 130 of 138 parts.
		self.assertIn("CATATAN TEMUAN", html)
		self.assertIn("penyok 12cm sisi kiri", html)
		self.assertNotIn("KETERANGAN", html)
