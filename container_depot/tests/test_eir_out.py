"""Tests for FASE G — EIR OUT Digital (surveyor load-out inspection vs last EIR-In).

Covers: latest EIR-In baseline, the EIR-Out draft being raised when a position survey is
CLOSED (with its EIR-In reference), the bon adopting that draft instead of raising a second
one, the comparison payload, the submit outcome (Ready To Load vs Hold + Order Muat status)
and the open-draft per-type separation. The departure that a clean submit triggers lives in
``test_gate_out.py``.

Since 2026-09-03 an EIR-Out is born at the survey, not at the bon — see
``tank_survey.finish_survey`` — and it cannot be SUBMITTED until a bon exists
(``Inspection.before_submit``), which is why every submit below is given one.

FrappeTestCase rolls back per test; tearDown also deletes throwaway rows by prefix.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot.container_depot import eir
from container_depot.container_depot.doctype.container import container
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_eir import _make_order_muat

PREFIX = "EOUT"


def _survey_row(container):
	"""A throwaway Survey Order carrying ``container``, and the tank row's name.

	Built by hand rather than through a booking: these tests are about the INSPECTION, and
	``test_tank_survey`` owns how a schedule really comes into being.
	"""
	doc = frappe.get_doc({
		"doctype": "Survey Order",
		"booking": None,
		"survey_date": today(),
		"depot": frappe.db.get_value("Container", container, "depot"),
		"status": "Scheduled",
		"tanks": [{"container": container, "status": "Lowered"}],
	})
	doc.flags.ignore_validate = True
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	return doc.tanks[0].name


def _eir_out_draft(container, order_muat=None):
	"""Raise an EIR-Out the way production now does — by closing a tank's survey row — and
	optionally hand it the bon afterwards, which is what an Order Muat submit does.

	Returns the EIR-Out's name.
	"""
	name = eir.provision_eir_out_for_survey(_survey_row(container))
	if order_muat:
		eir.attach_order_muat_to_eirs(order_muat)
	return name


def _container(no, status="Available"):
	frappe.get_doc({
		"doctype": "Container",
		"container_no": no,
		"container_type": "ISO Tank",
		"status": status,
		"principal": ensure_test_customer("EIR-Out Test Principal"),
	}).insert(ignore_permissions=True)
	return no


def _finish_cleaning(container):
	"""The submitted, Completed Cleaning Order that now stands for "this tank is clean"."""
	doc = frappe.get_doc({
		"doctype": "Cleaning Order", "container": container, "status": "Completed",
	}).insert(ignore_permissions=True, ignore_mandatory=True)
	frappe.db.set_value("Cleaning Order", doc.name, "docstatus", 1, update_modified=False)
	return doc.name


def _eir_in(container, *, damage=False):
	"""A submitted EIR-In baseline (optionally with one damage finding)."""
	lines = None
	if damage:
		masters = eir.get_eir_masters()
		item = masters["checklist"][0]["item_code"]
		dmg = next((d["code"] for d in masters["damage_codes"] if d["code"] != "v"), None)
		lines = [{"item_code": item, "damage_code": dmg, "remarks": "dent at gate-in"}]
	res = eir.create_eir(
		inspection_type="EIR-In", container=container, tank_status="Empty Clean",
		lines=lines, create_cleaning_order=0, create_repair_order=0, submit=True,
	)
	return res["name"]


def _submit_eir_out(container, *, has_damage=False, order_muat=None):
	"""Create + submit an EIR-Out directly (bypasses the worklist) and return its name.

	A bon is ALWAYS ensured, even when the test does not care which one: since 2026-09-03 an
	EIR-Out cannot be submitted until an Order Muat carries its tank
	(``Inspection.before_submit``), because a clean submit sends the tank through the gate in
	the same breath. Tests that are about something else should not have to say so.
	"""
	if not order_muat and not eir.latest_voucher_for_container(container, "EIR-Out"):
		_make_order_muat(ensure_test_customer("EIR-Out Shipper"), container)
	doc = frappe.new_doc("Inspection")
	doc.inspection_type = "EIR-Out"
	doc.container = container
	doc.inspector = frappe.session.user
	doc.depot = frappe.db.get_value("Container", container, "depot")
	if has_damage:
		# Has Damage is derived from the log (Inspection.sync_has_damage), so a tank that is
		# meant to read as damaged needs the finding that says so — one row with a real
		# defect code, which is what the PWA would have written.
		masters = eir.get_eir_masters()
		doc.append("damage_log", {
			"component": "Frame",
			"damage_type": next(d["code"] for d in masters["damage_codes"] if d["code"] != "v"),
			"damage_description": "temuan saat load-out",
			"severity": "Minor",
		})
	if order_muat:
		doc.referred_voucher = order_muat
		doc.voucher_doctype = "Order Muat"
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


class TestEirOut(FrappeTestCase):
	def tearDown(self):
		frappe.db.delete("Container Activity", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Container Movement", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Gate Entry", {"container_no": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Inspection", {"container": ["like", f"{PREFIX}%"]})
		orders = frappe.get_all(
			"Survey Order Tank",
			filters={"container": ["like", f"{PREFIX}%"]}, pluck="parent", distinct=True,
		)
		frappe.db.delete("Survey Order Tank", {"container": ["like", f"{PREFIX}%"]})
		if orders:
			frappe.db.delete("Survey Order", {"name": ["in", orders]})
		frappe.db.delete("Repair Order", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Cleaning Order", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Container", {"name": ["like", f"{PREFIX}%"]})

	def test_latest_eir_in(self):
		c = _container(f"{PREFIX}0000003")
		first = _eir_in(c)
		second = _eir_in(c)
		self.assertEqual(eir.latest_eir_in(c), second)
		self.assertNotEqual(first, second)

	def test_closing_a_survey_raises_the_eir_out_with_no_bon(self):
		"""The draft is born days before anybody cuts a bon — that is the whole point of
		moving it earlier — so it carries the EIR-In baseline and nothing from a voucher."""
		c = _container(f"{PREFIX}0000004")
		ein = _eir_in(c, damage=True)
		_finish_cleaning(c)

		eo = frappe.get_doc("Inspection", _eir_out_draft(c))
		self.assertEqual(eo.inspection_type, "EIR-Out")
		self.assertEqual(eo.reference_eir_in, ein)
		self.assertIsNone(eo.referred_voucher)
		self.assertTrue(eo.survey_tank)
		self.assertEqual(
			frappe.db.get_value("Survey Order Tank", eo.survey_tank, "container"), c
		)

	def test_the_bon_adopts_that_draft_instead_of_raising_another(self):
		"""Everything typed on the Generate Bon screen has to land on the document the survey
		already opened — a second EIR-Out beside it is exactly what this rework removed."""
		c = _container(f"{PREFIX}0000008")
		_eir_in(c)
		_finish_cleaning(c)
		eo = _eir_out_draft(c)
		om = _make_order_muat(
			ensure_test_customer("EIR-Out Shipper"), c,
			truck="B-9001-XY", driver="Budi", phone="08110001",
		)

		result = eir.attach_order_muat_to_eirs(om)
		self.assertEqual(result["attached"], [eo])
		self.assertEqual(result["missing"], [])

		after = frappe.get_doc("Inspection", eo)
		self.assertEqual(after.referred_voucher, om)
		self.assertEqual(after.voucher_doctype, "Order Muat")
		self.assertEqual(
			frappe.db.count("Inspection", {"container": c, "inspection_type": "EIR-Out", "docstatus": ["!=", 2]}),
			1,
		)

	def test_a_bon_for_a_tank_with_no_survey_reports_it_rather_than_inventing_one(self):
		"""The deliberate consequence of a single birthplace. The operator who just cut the
		bon is told, because they are the one who can go and close the survey."""
		c = _container(f"{PREFIX}0000010")
		om = _make_order_muat(ensure_test_customer("EIR-Out Shipper"), c)

		result = eir.attach_order_muat_to_eirs(om)
		self.assertEqual(result["attached"], [])
		self.assertEqual(result["missing"], [c])
		self.assertEqual(frappe.db.count("Inspection", {"container": c, "inspection_type": "EIR-Out"}), 0)

	def test_a_resubmitted_bon_does_not_raise_a_second_eir_out(self):
		# A bon can go back to draft for a correction (order_generation.revert_order_to_draft)
		# and be submitted again. By then the surveyor may already have SUBMITTED the EIR-Out
		# — invisible to the open-draft check — so the re-attach must recognise its own work
		# rather than report the tank as missing an EIR.
		c = _container(f"{PREFIX}0000009")
		_eir_in(c, damage=True)
		_finish_cleaning(c)
		om = _make_order_muat(ensure_test_customer("EIR-Out Shipper"), c)
		eo = _eir_out_draft(c, order_muat=om)
		frappe.db.set_value("Inspection", eo, {"docstatus": 1, "status": "Submitted"})

		self.assertEqual(eir.attach_order_muat_to_eirs(om), {"attached": [], "missing": []})
		self.assertEqual(frappe.db.count("Inspection", {"container": c, "inspection_type": "EIR-Out"}), 1)

	def test_an_eir_out_cannot_be_submitted_before_the_bon_is_out(self):
		"""Submitting is not a filing step here — a clean EIR-Out sends the tank through the
		gate in the same submit. Doing that with no bon behind it would release a tank on no
		loading paperwork at all: no truck, no driver, no booking code surrendered."""
		c = _container(f"{PREFIX}0000012")
		_eir_in(c)
		_finish_cleaning(c)
		eo = frappe.get_doc("Inspection", _eir_out_draft(c))
		with self.assertRaises(frappe.ValidationError):
			eo.submit()

		_make_order_muat(ensure_test_customer("EIR-Out Shipper"), c)
		frappe.get_doc("Inspection", eo.name).submit()
		self.assertEqual(frappe.db.get_value("Inspection", eo.name, "docstatus"), 1)

	def test_open_eir_out_reference(self):
		c = _container(f"{PREFIX}0000005")
		_eir_in(c, damage=True)
		_finish_cleaning(c)
		om = _make_order_muat(ensure_test_customer("EIR-Out Shipper"), c)
		eo = _eir_out_draft(c, order_muat=om)

		payload = eir.open_eir_out(eo)
		ref = payload["reference"]
		self.assertIsNotNone(ref["eir_in"])
		self.assertTrue(ref["eir_in"]["damages"])  # baseline had a finding

	# --- seal numbers (the load-out record: what the tank leaves WITH) ---------

	def _draft_with_seals(self, no, seals):
		"""Provision an EIR-Out draft, start the work clock, and save `seals` onto it."""
		c = _container(no)
		_eir_in(c)
		_finish_cleaning(c)
		om = _make_order_muat(ensure_test_customer("EIR-Out Shipper"), c)
		eo = _eir_out_draft(c, order_muat=om)
		eir.start_eir(eo)
		eir.save_draft(inspection=eo, inspection_type="EIR-Out", seals=seals)
		return eo

	def test_seals_are_saved_and_read_back_in_order(self):
		eo = self._draft_with_seals(f"{PREFIX}0000011", [
			{"seal_no": "SEAL-001", "remarks": "top hatch"},
			{"seal_no": "SEAL-002"},
		])
		rows = eir.open_eir_out(eo)["seals"]
		self.assertEqual([r["seal_no"] for r in rows], ["SEAL-001", "SEAL-002"])
		self.assertEqual(rows[0]["remarks"], "top hatch")
		self.assertIsNone(rows[1]["remarks"])

	def test_seals_accept_bare_strings(self):
		"""An integration may reasonably post ["ABC"] rather than [{"seal_no": "ABC"}]."""
		eo = self._draft_with_seals(f"{PREFIX}0000012", ["SEAL-A", "SEAL-B"])
		self.assertEqual([r["seal_no"] for r in eir.open_eir_out(eo)["seals"]], ["SEAL-A", "SEAL-B"])

	def test_seals_drop_blanks_and_duplicates(self):
		"""A blank row is an abandoned tap; a repeat is a double-tap — the same physical
		seal cannot be fitted twice."""
		eo = self._draft_with_seals(f"{PREFIX}0000013", [
			{"seal_no": "SEAL-X"}, {"seal_no": "   "}, {"seal_no": "seal-x"}, {"seal_no": "SEAL-Y"},
		])
		self.assertEqual([r["seal_no"] for r in eir.open_eir_out(eo)["seals"]], ["SEAL-X", "SEAL-Y"])

	def test_a_save_without_seals_leaves_the_list_alone(self):
		"""EIR-In saves never carry seals — omitting the key must not wipe a saved list."""
		eo = self._draft_with_seals(f"{PREFIX}0000014", [{"seal_no": "SEAL-KEEP"}])
		eir.save_draft(inspection=eo, inspection_type="EIR-Out", remarks="just a note")
		self.assertEqual([r["seal_no"] for r in eir.open_eir_out(eo)["seals"]], ["SEAL-KEEP"])

	def test_seals_can_be_cleared_explicitly(self):
		eo = self._draft_with_seals(f"{PREFIX}0000015", [{"seal_no": "SEAL-GONE"}])
		eir.save_draft(inspection=eo, inspection_type="EIR-Out", seals=[])
		self.assertEqual(eir.open_eir_out(eo)["seals"], [])

	# --- the Container master reads its seals back from here --------------------
	def test_seal_history_shows_submitted_releases_only(self):
		"""The Container master carries no seal fields of its own — its Seals section reads
		this history live. A draft EIR-Out is still being typed, so its numbers are not yet
		part of the tank's record."""
		eo = self._draft_with_seals(f"{PREFIX}0000016", [
			{"seal_no": "SEAL-H1", "remarks": "manhole"},
			{"seal_no": "SEAL-H2"},
		])
		c = frappe.db.get_value("Inspection", eo, "container")
		self.assertEqual(container.seal_history(c), [])  # still a draft

		frappe.get_doc("Inspection", eo).submit()
		history = container.seal_history(c)
		self.assertEqual(len(history), 1)
		self.assertEqual(history[0]["eir"], eo)
		self.assertEqual([s["seal_no"] for s in history[0]["seals"]], ["SEAL-H1", "SEAL-H2"])
		self.assertEqual(history[0]["seals"][0]["remarks"], "manhole")

	def test_seal_history_skips_a_release_without_seals(self):
		"""This is the seal history, not the release history: an EIR-Out nobody sealed would
		otherwise show up as an empty row that reads like missing data."""
		c = _container(f"{PREFIX}0000017")
		_eir_in(c)
		_finish_cleaning(c)
		_submit_eir_out(c)
		self.assertEqual(container.seal_history(c), [])

	def test_submit_clean_releases_the_tank(self):
		"""A clean submit scores Ready To Load and, in the same submit, takes the tank out —
		so a single-tank bon goes straight past Ready To Load to Completed."""
		c = _container(f"{PREFIX}0000006")
		_eir_in(c)
		_finish_cleaning(c)
		om = _make_order_muat(ensure_test_customer("EIR-Out Shipper"), c)

		name = _submit_eir_out(c, order_muat=om)
		self.assertEqual(frappe.db.get_value("Inspection", name, "out_outcome"), "Ready To Load")
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Gate_Out")
		self.assertEqual(frappe.db.get_value("Order Muat", om, "order_status"), "Completed")

	def test_submit_with_a_finding_sets_hold(self):
		"""A checklist finding is now the only thing that can hold a tank — the separate
		exterior / seal assessment was dropped at the depot's request."""
		c = _container(f"{PREFIX}0000007")
		_eir_in(c)
		_finish_cleaning(c)
		om = _make_order_muat(ensure_test_customer("EIR-Out Shipper"), c)

		name = _submit_eir_out(c, has_damage=True, order_muat=om)
		self.assertEqual(frappe.db.get_value("Inspection", name, "out_outcome"), "Hold Pending Clearance")
		self.assertEqual(frappe.db.get_value("Order Muat", om, "order_status"), "Hold")

	def test_open_draft_separates_in_and_out(self):
		c = _container(f"{PREFIX}0000008", status="Available")
		din = eir.open_draft(container=c, inspection_type="EIR-In")
		dout = eir.open_draft(container=c, inspection_type="EIR-Out")
		self.assertNotEqual(din["inspection"], dout["inspection"])
		self.assertEqual(
			frappe.db.get_value("Inspection", dout["inspection"], "inspection_type"), "EIR-Out"
		)

	def test_a_held_tank_stays_in_the_depot(self):
		"""The mirror of the clean submit: a finding leaves the tank exactly where it was."""
		c = _container(f"{PREFIX}0000009", status="Available")
		_finish_cleaning(c)
		_submit_eir_out(c, has_damage=True)
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Available")
