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
# Raw status seeded per container -> expected Monitor bucket. Buckets are order-state
# centric: a container is classified by its most-advanced Cleaning/M&R order state
# (in_progress > pending > draft); no open order -> available.
TANKS = {
	"ESST1000001": "In_Depot",  # pending (Cleaning Order Pending) + PT due
	"ESST1000002": "Gate_Out",  # gate_out
	"ESST1000003": "Available",  # available (no orders at all)
	"ESST1000004": "In_Depot",  # in_progress (Cleaning Order In_Progress)
	"ESST1000005": "In_Depot",  # in_progress (Repair Order In Progress)
	"ESST1000006": "In_Depot",  # draft (Repair Order Draft — created, not submitted)
	"ESST1000007": "In_Depot",  # available (EIR-In Submitted — inspection never buckets)
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
	# ESST1000001: Cleaning Order Pending (queued, not started) -> pending bucket.
	frappe.get_doc(
		{"doctype": "Cleaning Order", "container": "ESST1000001", "status": "Pending"}
	).insert(ignore_permissions=True)
	# ESST1000004: cleaning STARTED (In_Progress) -> in_progress bucket.
	co = frappe.get_doc(
		{"doctype": "Cleaning Order", "container": "ESST1000004", "status": "Pending"}
	).insert(ignore_permissions=True)
	frappe.db.set_value("Cleaning Order", co.name, "status", "In_Progress", update_modified=False)
	# ESST1000005: M&R STARTED (In Progress) -> in_progress bucket.
	ro5 = frappe.get_doc(
		{"doctype": "Repair Order", "container": "ESST1000005", "status": "Draft", "billing_status": "Unbilled"}
	).insert(ignore_permissions=True)
	frappe.db.set_value("Repair Order", ro5.name, "status", "In Progress", update_modified=False)
	# ESST1000006: M&R created but NOT submitted (Draft) -> draft bucket (also backs the
	# repairs/documents tests below, which expect a Draft RO).
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
		# Order-state centric: classify by the most-advanced order state the tank carries.
		self.assertEqual(derive_status("Gate_Out"), "gate_out")
		self.assertEqual(derive_status("Available"), "available")
		# A present tank with no open order is available (nothing raised on it).
		self.assertEqual(derive_status("In_Depot"), "available")
		self.assertEqual(derive_status("In_Depot", draft=True), "draft")
		self.assertEqual(derive_status("In_Depot", pending=True), "pending")
		self.assertEqual(derive_status("In_Depot", in_progress=True), "in_progress")
		# Most-advanced state wins when several coexist.
		self.assertEqual(derive_status("In_Depot", in_progress=True, pending=True, draft=True), "in_progress")
		self.assertEqual(derive_status("In_Depot", pending=True, draft=True), "pending")
		# Gate-out is terminal.
		self.assertEqual(derive_status("Gate_Out", in_progress=True), "gate_out")

	def test_inventory_summary_counts(self):
		res = get_inventory_summary(depot=ESS_DEPOT)
		self.assertTrue(res["success"])
		# available = 1003 (idle) + 1007 (submitted EIR, no order); draft = 1006;
		# pending = 1001 (Cleaning Pending); in_progress = 1004 (CO IP) + 1005 (RO IP).
		self.assertEqual(
			res["counts"],
			{"available": 2, "draft": 1, "pending": 1, "in_progress": 2, "gate_out": 1},
		)
		self.assertEqual(res["total"], 7)
		self.assertEqual(res["periodic_test_due"], 1)

	def test_tank_list_pagination(self):
		res = get_tank_list(depot=ESS_DEPOT, page_length=3)
		self.assertEqual(res["total"], 7)
		self.assertEqual(len(res["items"]), 3)
		# Each row carries a derived bucket + pt_due flag (not the raw status).
		row = next(i for i in res["items"] if i["container_no"] == "ESST1000001")
		self.assertEqual(row["status"], "pending")
		self.assertTrue(row["pt_due"])

	def test_tank_list_status_filter(self):
		res = get_tank_list(depot=ESS_DEPOT, status="in_progress")
		self.assertEqual(res["total"], 2)  # ESST1000004 (cleaning) + ESST1000005 (M&R) started
		self.assertEqual({i["container_no"] for i in res["items"]}, {"ESST1000004", "ESST1000005"})
		self.assertEqual({i["status"] for i in res["items"]}, {"in_progress"})

	def test_tank_list_draft_and_pending_buckets(self):
		# A created-but-not-started order buckets by its state, not "in progress".
		draft = get_tank_list(depot=ESS_DEPOT, status="draft")
		self.assertEqual({i["container_no"] for i in draft["items"]}, {"ESST1000006"})
		pending = get_tank_list(depot=ESS_DEPOT, status="pending")
		self.assertEqual({i["container_no"] for i in pending["items"]}, {"ESST1000001"})
		available = get_tank_list(depot=ESS_DEPOT, status="available")
		self.assertEqual({i["container_no"] for i in available["items"]}, {"ESST1000003", "ESST1000007"})

	def test_tank_list_carries_driving_order(self):
		# Each draft/pending/in_progress row names the order that drives it (kind + link).
		rows = {i["container_no"]: i for i in get_tank_list(depot=ESS_DEPOT)["items"]}
		self.assertEqual(rows["ESST1000006"]["order"]["kind"], "M&R")  # Draft M&R
		self.assertEqual(rows["ESST1000006"]["order"]["doctype"], "Repair Order")
		self.assertTrue(rows["ESST1000006"]["order"]["name"])
		self.assertEqual(rows["ESST1000001"]["order"]["kind"], "Cleaning")  # Pending Cleaning
		self.assertEqual(rows["ESST1000004"]["order"]["kind"], "Cleaning")  # in-progress cleaning
		# available / gate_out carry no order link.
		self.assertIsNone(rows["ESST1000003"]["order"])
		self.assertIsNone(rows["ESST1000002"]["order"])

	def test_tank_list_search(self):
		res = get_tank_list(depot=ESS_DEPOT, search="ESST1000002")
		self.assertEqual([i["container_no"] for i in res["items"]], ["ESST1000002"])

	def test_tank_list_rejects_bad_status(self):
		with self.assertRaises(frappe.ValidationError):
			get_tank_list(depot=ESS_DEPOT, status="not_a_bucket")

	def test_tank_detail(self):
		res = get_tank_detail("ESST1000001")
		self.assertTrue(res["success"])
		self.assertEqual(res["status"], "pending")  # Cleaning Order Pending
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

	def test_pdf_url_uses_cleaning_order_format(self):
		url = _pdf_url("Cleaning Order", "CO-2026-00001", "Cleaning Order Format")
		self.assertIn("doctype=Cleaning+Order", url)
		self.assertIn("format=Cleaning+Order+Format", url)
		# Standard format omits the format param entirely.
		self.assertNotIn("format=", _pdf_url("Inspection", "EIR-2026-00001"))

	def test_get_tank_repairs(self):
		res = get_tank_repairs("ESST1000006")
		self.assertTrue(res["success"])
		self.assertEqual(len(res["repairs"]), 1)
		ro = res["repairs"][0]
		self.assertEqual(ro["status"], "Draft")
		self.assertEqual(ro["billing_status"], "Unbilled")
		# A Draft hands over to Admin Ops (Service Setup) — it can no longer jump straight
		# to the customer-visible Pending Approval. "Approved" is the Admin-Ops bypass
		# edge (this assertion had omitted it, so it was failing before the gate landed).
		self.assertEqual(ro["next_statuses"], ["Service Setup", "Approved", "Cancelled"])
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

			# Draft -> Service Setup (Admin Ops) -> Pending Approval (customer web).
			r1 = set_repair_status(ro.name, "Service Setup")
			self.assertEqual(r1["status"], "Service Setup")

			r1b = set_repair_status(ro.name, "Pending Approval")
			self.assertEqual(r1b["status"], "Pending Approval")

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
