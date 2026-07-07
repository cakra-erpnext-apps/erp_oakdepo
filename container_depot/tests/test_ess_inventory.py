"""Tests for the ESS PWA read endpoints — Feature F1 (Tank Inventory & Live
Status). Covers the server-side status derivation (incl. the duplicated
``In_Workshop`` value), the summary counts, list filtering/search/pagination,
the detail payload, and the Guest rejection guard.

Fixtures are created once in setUpClass and removed in tearDownClass (mirroring
this repo's idempotent-fixture convention rather than relying on per-test
rollback). All tests are read-only.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from container_depot.ess.inventory import (
	derive_status,
	get_inventory_summary,
	get_tank_list,
	get_tank_detail,
)
from container_depot.ess.documents import get_tank_documents, _pdf_url
from container_depot.ess.repairs import get_tank_repairs, set_repair_status
from container_depot.tests.test_api import ensure_test_branch, ensure_test_customer

ESS_DEPOT = "ESST"
# Raw status seeded per container -> expected derived bucket.
TANKS = {
	"ESST1000001": "In_Depot",  # in_depot (just gated in, + PT due)
	"ESST1000002": "Gate_Out",  # gate_out
	"ESST1000003": "Available",  # ready (consolidated ready pool)
	"ESST1000004": "Available",  # cleaning (open CO)
	"ESST1000005": "In_Depot",  # repair_survey
	"ESST1000006": "Available",  # repair_survey (open RO)
	"ESST1000007": "Available",  # repair_survey (open EIR)
}


def _teardown():
	names = list(TANKS.keys())
	for dt in ["Container Movement", "Cleaning Order", "Repair Order", "Inspection", "Periodic Test"]:
		frappe.db.delete(dt, {"container": ["in", names]})
	frappe.db.delete("Container", {"name": ["in", names]})
	if frappe.db.exists("Depot", ESS_DEPOT):
		frappe.db.delete("Depot", {"name": ESS_DEPOT})
	frappe.db.commit()


def _build():
	frappe.get_doc(
		{"doctype": "Depot", "depot_code": ESS_DEPOT, "depot_name": "ESS Test Depot", "branch": ensure_test_branch()}
	).insert(ignore_permissions=True)
	for no, status in TANKS.items():
		frappe.get_doc(
			{
				"doctype": "Container",
				"container_no": no,
				"container_type": "ISO Tank",
				"status": status,
				"depot": ESS_DEPOT,
				"principal": ensure_test_customer("ESS Inventory Test Principal"),
			}
		).insert(ignore_permissions=True)
	frappe.get_doc(
		{"doctype": "Cleaning Order", "container": "ESST1000004", "status": "Pending"}
	).insert(ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "Repair Order",
			"container": "ESST1000006",
			"status": "Draft",
			"billing_status": "Unbilled",
		}
	).insert(ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "Inspection",
			"container": "ESST1000007",
			"inspection_type": "EIR-In",
			"status": "Submitted",
			"inspector": "Administrator",
		}
	).insert(ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "Periodic Test",
			"container": "ESST1000001",
			"status": "Scheduled",
			"test_type": "2,5Y",
			"due_date": today(),
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()


class TestEssInventory(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_teardown()  # clean slate in case a prior run left scratch rows
		_build()

	@classmethod
	def tearDownClass(cls):
		_teardown()
		super().tearDownClass()

	def test_derive_status_mapping(self):
		# Presence-based raw status + open-order signals drive the UI buckets.
		self.assertEqual(derive_status("Gate_Out"), "gate_out")
		self.assertEqual(derive_status("Available"), "ready")
		# A present tank with no open work is plain in_depot.
		self.assertEqual(derive_status("In_Depot"), "in_depot")
		# Open work drives the cleaning / repair_survey buckets regardless of raw status.
		self.assertEqual(derive_status("In_Depot", open_cleaning=True), "cleaning")
		self.assertEqual(derive_status("In_Depot", open_repair=True), "repair_survey")
		self.assertEqual(derive_status("In_Depot", open_inspection=True), "repair_survey")
		# Open work overrides the Available->ready mapping so an active job still shows.
		self.assertEqual(derive_status("Available", open_cleaning=True), "cleaning")
		self.assertEqual(derive_status("Available", open_repair=True), "repair_survey")
		self.assertEqual(derive_status("Available", open_inspection=True), "repair_survey")
		# Gate-out wins over everything.
		self.assertEqual(derive_status("Gate_Out", open_repair=True), "gate_out")

	def test_inventory_summary_counts(self):
		res = get_inventory_summary(depot=ESS_DEPOT)
		self.assertTrue(res["success"])
		# ESST1000005 is In_Depot with no open order → in_depot (buckets are order-driven now).
		self.assertEqual(
			res["counts"],
			{"in_depot": 2, "cleaning": 1, "repair_survey": 2, "ready": 1, "gate_out": 1},
		)
		self.assertEqual(res["total"], 7)
		self.assertEqual(res["periodic_test_due"], 1)

	def test_tank_list_pagination(self):
		res = get_tank_list(depot=ESS_DEPOT, page_length=3)
		self.assertEqual(res["total"], 7)
		self.assertEqual(len(res["items"]), 3)
		# Each row carries a derived bucket + pt_due flag (not the raw status).
		row = next(i for i in res["items"] if i["container_no"] == "ESST1000001")
		self.assertEqual(row["status"], "in_depot")
		self.assertTrue(row["pt_due"])

	def test_tank_list_status_filter(self):
		res = get_tank_list(depot=ESS_DEPOT, status="repair_survey")
		self.assertEqual(res["total"], 2)  # ESST1000006 (open RO) + ESST1000007 (open EIR)
		self.assertEqual({i["status"] for i in res["items"]}, {"repair_survey"})

	def test_tank_list_search(self):
		res = get_tank_list(depot=ESS_DEPOT, search="ESST1000002")
		self.assertEqual([i["container_no"] for i in res["items"]], ["ESST1000002"])

	def test_tank_list_rejects_bad_status(self):
		with self.assertRaises(frappe.ValidationError):
			get_tank_list(depot=ESS_DEPOT, status="not_a_bucket")

	def test_tank_detail(self):
		res = get_tank_detail("ESST1000001")
		self.assertTrue(res["success"])
		self.assertEqual(res["status"], "in_depot")
		self.assertTrue(res["pt_due"])
		for key in ("capacity", "tare_weight", "last_test_date", "yard_zone", "container_type"):
			self.assertIn(key, res)

	def test_tank_documents(self):
		# ESST1000007 has an open Inspection (EIR); ESST1000006 a Repair Order.
		eir = get_tank_documents("ESST1000007")
		self.assertTrue(eir["success"])
		cats = {d["category"] for d in eir["documents"]}
		self.assertIn("EIR", cats)
		ins = next(d for d in eir["documents"] if d["category"] == "EIR")
		self.assertEqual(ins["doctype"], "Inspection")
		self.assertIn("download_pdf", ins["pdf_url"])
		self.assertIn("doctype=Inspection", ins["pdf_url"])
		# Browser-native print view is the primary (wkhtmltopdf-independent) link.
		self.assertIn("/printview", ins["view_url"])
		self.assertIn("trigger_print=1", ins["view_url"])

		rep = get_tank_documents("ESST1000006")
		self.assertIn("Estimasi Perbaikan", {d["category"] for d in rep["documents"]})

	def test_pdf_url_uses_cleaning_cert_format(self):
		url = _pdf_url("Cleaning Certificate", "CERT-2026-00001", "Cleaning Certificate Format")
		self.assertIn("doctype=Cleaning+Certificate", url)
		self.assertIn("format=Cleaning+Certificate+Format", url)
		# Standard format omits the format param entirely.
		self.assertNotIn("format=", _pdf_url("Inspection", "EIR-2026-00001"))

	def test_get_tank_repairs(self):
		res = get_tank_repairs("ESST1000006")
		self.assertTrue(res["success"])
		self.assertEqual(len(res["repairs"]), 1)
		ro = res["repairs"][0]
		self.assertEqual(ro["status"], "Draft")
		self.assertEqual(ro["billing_status"], "Unbilled")
		self.assertEqual(ro["next_statuses"], ["Pending Approval", "Cancelled"])
		self.assertIn("items", ro)

	def test_set_repair_status_transitions(self):
		# Self-contained: own container + RO, cleaned up so other tests are safe.
		c = frappe.get_doc(
			{
				"doctype": "Container",
				"container_no": "ESST1009999",
				"container_type": "ISO Tank",
				"status": "In_Depot",
				"depot": ESS_DEPOT,
				"principal": ensure_test_customer("ESS Inventory Test Principal"),
			}
		).insert(ignore_permissions=True)
		ro = frappe.get_doc(
			{
				"doctype": "Repair Order",
				"container": c.name,
				"status": "Draft",
				"billing_status": "Unbilled",
			}
		).insert(ignore_permissions=True)
		try:
			# Invalid jump rejected.
			with self.assertRaises(frappe.ValidationError):
				set_repair_status(ro.name, "Completed")

			r1 = set_repair_status(ro.name, "Pending Approval")
			self.assertEqual(r1["status"], "Pending Approval")

			r2 = set_repair_status(ro.name, "Approved")
			self.assertEqual(r2["status"], "Approved")
			# Controller propagated the container status (reuse, not reimplement).
			self.assertEqual(frappe.db.get_value("Container", c.name, "status"), "In_Depot")
		finally:
			for dt in ["Container Movement"]:
				frappe.db.delete(dt, {"container": c.name})
			frappe.delete_doc("Repair Order", ro.name, force=True, ignore_permissions=True)
			frappe.delete_doc("Container", c.name, force=True, ignore_permissions=True)
			frappe.db.commit()

	def test_guest_is_rejected(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				get_inventory_summary()
		finally:
			frappe.set_user("Administrator")
