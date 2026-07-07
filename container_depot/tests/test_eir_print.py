"""Render guard for the EIR print format (operations/print_format/eir).

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
		doc.append("damage_log", {
			"checklist_item": "01",
			"component": "1. Underside",
			"area": "UNDERSIDE",
			"damage_type": "11",
			"damage_description": "dent on underside",
			"severity": "Minor",
		})
		doc.insert(ignore_permissions=True)

		html = frappe.get_print("Inspection", doc.name, print_format="EIR Format")

		self.assertIn("EQUIPMENT INTERCHANGE RECEIPT", html)  # kop
		self.assertIn("EIRP", html)                            # ISO 6346 prefix derived
		self.assertIn("Damage Codes", html)                    # legend from master
		self.assertIn("Repair Codes", html)
		self.assertIn("Underside", html)                       # 50-row checklist grid
		self.assertIn("dent on underside", html)               # damage_log joined by checklist_item
