"""Tests for FASE G — EIR OUT Digital (surveyor load-out inspection vs last EIR-In).

Covers: cleaning-cert validity helper, latest EIR-In baseline, auto-provision of EIR-Out
drafts from an Order Muat (with reference + cert), the comparison payload, the submit
outcome (Ready To Load vs Hold + Order Muat status), the open-draft per-type separation,
and the gate-out enforcement (no clean EIR-Out -> blocked).

FrappeTestCase rolls back per test; tearDown also deletes throwaway rows by prefix.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot.operations import eir
from container_depot.operations.cleaning import get_latest_valid_cleaning_cert
from container_depot.operations.gate import mark_gate_out
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


def _cert(container, valid_until):
	doc = frappe.get_doc({
		"doctype": "Cleaning Certificate",
		"container": container,
		"clean_date": today(),
		"valid_until": valid_until,
	}).insert(ignore_permissions=True, ignore_mandatory=True)
	frappe.db.set_value("Cleaning Certificate", doc.name, "docstatus", 1, update_modified=False)
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


def _submit_eir_out(container, *, exterior="Clean", seals=1, cert=None, valid_until=None,
		has_damage=False, order_muat=None):
	"""Create + submit an EIR-Out directly (bypasses the worklist) and return its name."""
	doc = frappe.new_doc("Inspection")
	doc.inspection_type = "EIR-Out"
	doc.container = container
	doc.inspector = frappe.session.user
	doc.depot = frappe.db.get_value("Container", container, "depot")
	doc.exterior_condition = exterior
	doc.seals_intact = seals
	if cert:
		doc.cleaning_cert = cert
		doc.cleaning_cert_valid_until = valid_until
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
		frappe.db.delete("Cleaning Certificate", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Repair Order", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Cleaning Order", {"container": ["like", f"{PREFIX}%"]})
		frappe.db.delete("Container", {"name": ["like", f"{PREFIX}%"]})

	def test_cleaning_cert_validity(self):
		c = _container(f"{PREFIX}0000001")
		_cert(c, add_days(today(), 10))
		got = get_latest_valid_cleaning_cert(c)
		self.assertIsNotNone(got)
		self.assertTrue(got["valid"])

		c2 = _container(f"{PREFIX}0000002")
		_cert(c2, add_days(today(), -1))  # expired yesterday
		got2 = get_latest_valid_cleaning_cert(c2)
		self.assertIsNotNone(got2)
		self.assertFalse(got2["valid"])

	def test_latest_eir_in(self):
		c = _container(f"{PREFIX}0000003")
		first = _eir_in(c)
		second = _eir_in(c)
		self.assertEqual(eir.latest_eir_in(c), second)
		self.assertNotEqual(first, second)

	def test_provision_eir_out_from_order_muat(self):
		c = _container(f"{PREFIX}0000004")
		ein = _eir_in(c, damage=True)
		_cert(c, add_days(today(), 20))
		shipper = ensure_test_customer("EIR-Out Shipper")
		om = _make_order_muat(shipper, c)

		created = eir.provision_eir_out_for_order_muat(om)
		self.assertEqual(len(created), 1)
		eo = frappe.get_doc("Inspection", created[0])
		self.assertEqual(eo.inspection_type, "EIR-Out")
		self.assertEqual(eo.reference_eir_in, ein)
		self.assertTrue(eo.cleaning_cert)
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
		_cert(c, add_days(today(), 20))
		om = _make_order_muat(ensure_test_customer("EIR-Out Shipper"), c)
		eo = eir.provision_eir_out_for_order_muat(om)[0]

		payload = eir.open_eir_out(eo)
		ref = payload["reference"]
		self.assertIsNotNone(ref["eir_in"])
		self.assertTrue(ref["eir_in"]["damages"])  # baseline had a finding
		self.assertTrue(ref["cleaning_cert"]["valid"])

	def test_submit_clean_sets_ready_to_load(self):
		c = _container(f"{PREFIX}0000006")
		_eir_in(c)
		cert = _cert(c, add_days(today(), 20))
		om = _make_order_muat(ensure_test_customer("EIR-Out Shipper"), c)

		name = _submit_eir_out(c, exterior="Clean", seals=1, cert=cert,
			valid_until=add_days(today(), 20), order_muat=om)
		self.assertEqual(frappe.db.get_value("Inspection", name, "out_outcome"), "Ready To Load")
		self.assertEqual(frappe.db.get_value("Order Muat", om, "order_status"), "Ready To Load")

	def test_submit_dirty_sets_hold(self):
		c = _container(f"{PREFIX}0000007")
		_eir_in(c)
		cert = _cert(c, add_days(today(), 20))
		om = _make_order_muat(ensure_test_customer("EIR-Out Shipper"), c)

		name = _submit_eir_out(c, exterior="Dirty", seals=1, cert=cert,
			valid_until=add_days(today(), 20), order_muat=om)
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
		cert = _cert(c, add_days(today(), 20))
		_submit_eir_out(c, exterior="Clean", seals=1, cert=cert, valid_until=add_days(today(), 20))
		# Submit may have re-saved the container; force the pickup-ready status for the gate.
		frappe.db.set_value("Container", c, "status", "Available", update_modified=False)

		res = mark_gate_out(container=c)
		self.assertEqual(res["status"], "Gate_Out")
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Gate_Out")
