"""Tests for FASE G — EIR OUT Digital (surveyor load-out inspection vs last EIR-In).

Covers: latest EIR-In baseline, auto-provision of EIR-Out drafts from an Order Muat
(with its EIR-In reference), the comparison payload, the submit
outcome (Ready To Load vs Hold + Order Muat status), the open-draft per-type separation,
and the gate-out enforcement (no clean EIR-Out -> blocked).

FrappeTestCase rolls back per test; tearDown also deletes throwaway rows by prefix.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot.container_depot import eir
from container_depot.container_depot.doctype.container import container
from container_depot.container_depot.gate import mark_gate_out
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_eir import _make_order_muat

PREFIX = "EOUT"


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
	"""Create + submit an EIR-Out directly (bypasses the worklist) and return its name."""
	doc = frappe.new_doc("Inspection")
	doc.inspection_type = "EIR-Out"
	doc.container = container
	doc.inspector = frappe.session.user
	doc.depot = frappe.db.get_value("Container", container, "depot")
	doc.has_damage = 1 if has_damage else 0
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
		frappe.db.delete("Repair Order", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Cleaning Order", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Container", {"name": ["like", f"{PREFIX}%"]})

	def test_latest_eir_in(self):
		c = _container(f"{PREFIX}0000003")
		first = _eir_in(c)
		second = _eir_in(c)
		self.assertEqual(eir.latest_eir_in(c), second)
		self.assertNotEqual(first, second)

	def test_provision_eir_out_from_order_muat(self):
		c = _container(f"{PREFIX}0000004")
		ein = _eir_in(c, damage=True)
		_finish_cleaning(c)
		shipper = ensure_test_customer("EIR-Out Shipper")
		om = _make_order_muat(shipper, c)

		created = eir.provision_eir_out_for_order_muat(om)
		self.assertEqual(len(created), 1)
		eo = frappe.get_doc("Inspection", created[0])
		self.assertEqual(eo.inspection_type, "EIR-Out")
		self.assertEqual(eo.reference_eir_in, ein)
		self.assertEqual(eo.referred_voucher, om)

		# Idempotent — a second provision creates no duplicate.
		again = eir.provision_eir_out_for_order_muat(om)
		self.assertEqual(again, [])
		self.assertEqual(
			frappe.db.count("Inspection", {"container": c, "inspection_type": "EIR-Out", "docstatus": 0}), 1
		)

	def test_open_eir_out_reference(self):
		c = _container(f"{PREFIX}0000005")
		_eir_in(c, damage=True)
		_finish_cleaning(c)
		om = _make_order_muat(ensure_test_customer("EIR-Out Shipper"), c)
		eo = eir.provision_eir_out_for_order_muat(om)[0]

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
		eo = eir.provision_eir_out_for_order_muat(om)[0]
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

	def test_submit_clean_sets_ready_to_load(self):
		c = _container(f"{PREFIX}0000006")
		_eir_in(c)
		_finish_cleaning(c)
		om = _make_order_muat(ensure_test_customer("EIR-Out Shipper"), c)

		name = _submit_eir_out(c, order_muat=om)
		self.assertEqual(frappe.db.get_value("Inspection", name, "out_outcome"), "Ready To Load")
		self.assertEqual(frappe.db.get_value("Order Muat", om, "order_status"), "Ready To Load")

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

	def test_gate_out_blocked_without_clean_eir_out(self):
		c = _container(f"{PREFIX}0000009", status="Available")
		with self.assertRaises(frappe.ValidationError):
			mark_gate_out(container=c)
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Available")

	def test_gate_out_allowed_with_clean_eir_out(self):
		c = _container(f"{PREFIX}0000010", status="Available")
		_finish_cleaning(c)
		_submit_eir_out(c)
		# Submit may have re-saved the container; force the pickup-ready status for the gate.
		frappe.db.set_value("Container", c, "status", "Available", update_modified=False)

		res = mark_gate_out(container=c)
		self.assertEqual(res["status"], "Gate_Out")
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Gate_Out")
