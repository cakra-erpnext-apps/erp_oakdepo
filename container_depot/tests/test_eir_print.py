"""Render guard for the EIR print format (container_depot/print_format/eir).

The template is pure Jinja with master-driven legends + a checklist grid joined to
damage_log; this test catches template breakage and confirms the derived ISO 6346
prefix, the code legend and the checklist grid all render for a Desk- or PWA-built
Inspection (both share the same checklist_item linkage).

The grid is banded per area, so the assertions below also pin the two things that
banding buys and can silently regress: the band itself, and the item name printed
without the area prefix the band already carries.
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
		# Kelengkapan tank — the printed sheet's fill-in boxes, not defects. TWO slots of the
		# SAME item, so the one-row-per-item fold is actually exercised.
		for slot, value in (("IN", "3"), ("OUT", "4")):
			doc.append("fittings", {
				"fitting_item": f"BDC-09-{slot}",
				"compartment": "Bottom Discharge",
				"printed_no": "9",
				"item_label": "Steam Pipe",
				"slot_label": slot,
				"value": value,
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
		self.assertIn("BOTTOM DISCHARGE COMPARTMENT", html)    # grouped as the paper groups it
		# One row per item, both boxes on it — "Steam Pipe IN 3 inch · OUT 4 inch" is how the
		# paper reads, not two rows both captioned Steam Pipe. Counted inside the kelengkapan
		# block only: the checklist above it has four parts of its own with Steam Pipe in the
		# name (Front Steam Pipe Cap, Left/Right Side Steam Pipe, Underframe Steam Pipe), and
		# the block ends at the Remarks panel that follows it.
		block = html.split("KELENGKAPAN TANK", 1)[1].split("Remarks", 1)[0]
		self.assertEqual(block.count("Steam Pipe"), 1)
		for box in (">IN<", ">OUT<", ">3<", ">4<", ">inch<"):
			self.assertIn(box, block)
		# Header block mirrors the OAK paper form's field grid.
		for caption in ("Date of Inspection", "Tank No", "Max Gross Weight", "Inspect Location",
						"Shipper / Consignee", "EMKL", "Reference No.", "Seal"):
			self.assertIn(caption, html)
		self.assertIn("EIR fill / inspect by", html)           # sign-off per the paper form
		# The words behind a code live under CATATAN TEMUAN, not in a grid column that would
		# be blank for 130 of 138 parts.
		self.assertIn("CATATAN TEMUAN", html)
		self.assertIn("penyok 12cm sisi kiri", html)
		# ...and the words are there under a KETERANGAN heading of their own, which is the
		# ONLY place that heading may appear: a remarks column back in the checklist grid
		# would be blank for 130 of 138 parts.
		self.assertEqual(html.count("KETERANGAN"), 1)
		# A code is printed next to its meaning wherever there is room for both.
		self.assertIn("Dented", html)                          # 11, decoded under CATATAN TEMUAN

		# The code key is the reader's way into the D / R columns, so it precedes the grid.
		self.assertLess(html.index("Damage codes"), html.index("FRONT"))
		# Banded per area, and the band carries the area so the cell need not repeat it:
		# "Front Top Rail" prints as "Top Rail" under the FRONT band.
		for band in ("FRONT", "REAR", "BOTTOM DISCHARGE"):
			self.assertIn(f'class="sec" colspan="12">{band} ', html)
		grid = html.split("CATATAN TEMUAN", 1)[0]
		self.assertIn(">Top Rail</td>", grid)
		self.assertNotIn("Front Top Rail", grid)
		# The notes table has no band above it, so there the part keeps its full name.
		self.assertIn("Front Top Rail", html)
