"""Kelengkapan tank (EIR fittings) — the fill-in boxes of the printed EIR sheet.

Not defects: these record what the tank CARRIES (steam pipe bore, manlid seal type, how
many straps), on BOTH gates, so what came in can be compared with what left.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot import eir
from container_depot.tests.test_api import ensure_test_customer


def _make_container(cno, **kw):
	kw.setdefault("principal", ensure_test_customer("EIR Fitting Principal"))
	kw.setdefault("status", "In_Depot")
	return frappe.get_doc({
		"doctype": "Container",
		"container_no": cno,
		"container_type": "ISO Tank",
		**kw,
	}).insert(ignore_permissions=True).name


class TestEirFittingMasters(FrappeTestCase):
	def test_masters_expose_every_printed_box(self):
		"""One master row per INPUT BOX, in printed order — Airline Valve alone owns four."""
		m = eir.get_eir_masters()
		fittings = m["fittings"]
		self.assertEqual(len(fittings), 24)
		self.assertEqual([fittings[0]["sequence"], fittings[-1]["sequence"]], [1, 24])
		self.assertEqual(
			[f["compartment"] for f in fittings][:1] + [fittings[-1]["compartment"]],
			["Bottom Discharge", "Side"],
		)
		airline = [f for f in fittings if f["item_label"] == "Airline Valve"]
		self.assertEqual(len(airline), 4)
		self.assertEqual(
			sorted(f["slot_label"] or "" for f in airline), ["", "Cap", "Tipe", "Ukuran"]
		)

	def test_choice_options_arrive_as_a_list(self):
		"""The PWA renders a picker, so options travel split — never as one newline blob."""
		by_code = {f["fitting_item"]: f for f in eir.get_eir_masters()["fittings"]}
		seal = by_code["MLC-09-TYPE"]
		self.assertEqual(seal["value_type"], "Choice")
		self.assertEqual(seal["options"], ["PTFE", "SWR", "Supertanktyt", "Other"])
		# A Number box carries its unit instead, and no options at all.
		steam = by_code["BDC-09-IN"]
		self.assertEqual([steam["value_type"], steam["uom"], steam["options"]], ["Number", "inch", []])


class TestEirFittingSave(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.container = _make_container("EIRF1000001")

	def tearDown(self):
		frappe.db.delete("Inspection", {"container": self.container})
		frappe.db.delete("Container", {"name": self.container})
		frappe.db.commit()
		super().tearDown()

	def _draft(self, inspection_type="EIR-In"):
		name = eir.create_eir(inspection_type=inspection_type, container=self.container, submit=False)["name"]
		eir.start_eir(name)  # editing a draft requires an explicit Mulai first
		return name

	def test_only_filled_boxes_are_stored_and_labels_are_denormalised(self):
		name = self._draft()
		eir.save_draft(
			inspection=name,
			fittings=[
				{"fitting_item": "BDC-09-IN", "value": "3"},
				{"fitting_item": "SID-03-PCS", "value": "2"},
				{"fitting_item": "SID-04-LONG", "value": "   "},   # blank -> not recorded
				{"fitting_item": "NOT-A-SLOT", "value": "9"},      # unknown -> ignored
			],
		)
		rows = frappe.get_doc("Inspection", name).fittings
		self.assertEqual([r.fitting_item for r in rows], ["BDC-09-IN", "SID-03-PCS"])
		steam = rows[0]
		# Labels ride along so a later master edit cannot rewrite a submitted EIR.
		self.assertEqual(
			[steam.compartment, steam.item_label, steam.slot_label, steam.uom, steam.value],
			["Bottom Discharge", "Steam Pipe", "IN", "inch", "3"],
		)

	def test_a_blank_box_is_not_recorded_as_zero(self):
		"""Kosong ≠ nol: a slot nobody filled must read back as absent, not as 0."""
		name = self._draft()
		eir.save_draft(inspection=name, fittings=[{"fitting_item": "SID-03-PCS", "value": "2"}])
		eir.save_draft(inspection=name, fittings=[{"fitting_item": "SID-03-PCS", "value": ""}])
		self.assertEqual(frappe.get_doc("Inspection", name).fittings, [])

	def test_omitting_the_key_leaves_the_list_alone(self):
		"""A client that knows nothing about fittings must not wipe a Desk-entered list."""
		name = self._draft()
		eir.save_draft(inspection=name, fittings=[{"fitting_item": "SID-03-PCS", "value": "2"}])
		eir.save_draft(inspection=name, remarks="tanpa kelengkapan")
		self.assertEqual([r.fitting_item for r in frappe.get_doc("Inspection", name).fittings], ["SID-03-PCS"])

	def test_reopening_a_draft_returns_what_was_saved(self):
		name = self._draft()
		eir.save_draft(inspection=name, fittings=[{"fitting_item": "MLC-09-TYPE", "value": "PTFE"}])
		payload = eir.open_draft_by_name(name)
		self.assertEqual(
			payload["fittings"], [{"fitting_item": "MLC-09-TYPE", "value": "PTFE", "baseline": ""}]
		)

	def test_the_pwa_wire_format_is_accepted(self):
		"""The PWA posts one JSON blob, not a list — the same shape `tank` travels in."""
		name = self._draft()
		eir.save_draft(inspection=name, fittings='[{"fitting_item": "SID-03-PCS", "value": "2"}]')
		self.assertEqual([r.value for r in frappe.get_doc("Inspection", name).fittings], ["2"])

	def test_a_write_in_value_outside_the_options_is_kept(self):
		"""The paper form says "Flange / BSP / Other ..." — the write-in has to survive."""
		name = self._draft()
		eir.save_draft(inspection=name, fittings=[{"fitting_item": "BDC-07-TYPE", "value": "Camlock 3in"}])
		self.assertEqual(frappe.get_doc("Inspection", name).fittings[0].value, "Camlock 3in")


class TestEirFittingBaseline(FrappeTestCase):
	"""EIR-Out is where the numbers pay off: it starts from what the tank arrived with."""

	def setUp(self):
		super().setUp()
		self.container = _make_container("EIRF1000002")
		self.eir_in = eir.create_eir(
			inspection_type="EIR-In",
			container=self.container,
			tank_status="Empty Dirty",
			fittings=[
				{"fitting_item": "SID-03-PCS", "value": "2"},
				{"fitting_item": "MLC-09-TYPE", "value": "PTFE"},
			],
			submit=False,
		)["name"]
		frappe.db.set_value("Inspection", self.eir_in, "docstatus", 1, update_modified=False)

	def tearDown(self):
		frappe.db.delete("Inspection", {"container": self.container})
		frappe.db.delete("Container", {"name": self.container})
		frappe.db.commit()
		super().tearDown()

	def _eir_out(self):
		name = eir.create_eir(inspection_type="EIR-Out", container=self.container, submit=False)["name"]
		frappe.db.set_value("Inspection", name, "reference_eir_in", self.eir_in, update_modified=False)
		eir.start_eir(name)
		return name

	def test_an_untouched_eir_out_prefills_from_the_eir_in(self):
		payload = eir.open_draft_by_name(self._eir_out())
		by_code = {f["fitting_item"]: f for f in payload["fittings"]}
		self.assertEqual(by_code["SID-03-PCS"], {"fitting_item": "SID-03-PCS", "value": "2", "baseline": "2"})
		self.assertEqual(by_code["MLC-09-TYPE"]["value"], "PTFE")

	def test_the_baseline_stays_visible_after_the_surveyor_corrects_it(self):
		"""Masuk 2 strap, keluar 1: the difference is the whole point of recording both."""
		name = self._eir_out()
		eir.save_draft(inspection=name, fittings=[{"fitting_item": "SID-03-PCS", "value": "1"}])
		by_code = {f["fitting_item"]: f for f in eir.open_draft_by_name(name)["fittings"]}
		self.assertEqual(by_code["SID-03-PCS"], {"fitting_item": "SID-03-PCS", "value": "1", "baseline": "2"})

	def test_a_box_the_surveyor_cleared_does_not_come_back(self):
		"""Prefill is all-or-nothing: once the draft owns values, the baseline stops filling."""
		name = self._eir_out()
		eir.save_draft(inspection=name, fittings=[{"fitting_item": "SID-03-PCS", "value": "1"}])
		by_code = {f["fitting_item"]: f for f in eir.open_draft_by_name(name)["fittings"]}
		self.assertEqual(by_code["MLC-09-TYPE"]["value"], "")
		self.assertEqual(by_code["MLC-09-TYPE"]["baseline"], "PTFE")

	def test_an_eir_in_never_prefills_itself(self):
		name = eir.create_eir(inspection_type="EIR-In", container=self.container, submit=False)["name"]
		self.assertEqual(eir.open_draft_by_name(name)["fittings"], [])
