"""Tests for the Container Activity unified action-history feed."""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime, today

from container_depot.operations.container_activity import log_container_activity
from container_depot.tests._booking_helpers import make_booking_code
from container_depot.tests.test_api import ensure_test_customer


def _make_container(cno, *, status="Available", principal=None, depot=None):
	return frappe.get_doc({
		"doctype": "Container",
		"container_no": cno,
		"container_type": "ISO Tank",
		"status": status,
		"principal": principal,
		"depot": depot,
	}).insert(ignore_permissions=True).name


def _activities(container, activity_type=None):
	filters = {"container": container}
	if activity_type:
		filters["activity_type"] = activity_type
	return frappe.get_all("Container Activity", filters=filters, fields=["name", "activity_type", "reference_doctype", "reference_name", "to_status"])


class TestContainerActivityHelper(FrappeTestCase):
	def test_helper_inserts_and_denormalizes(self):
		cust = ensure_test_customer("Activity Helper Cust")
		c = _make_container("ACTHLP00001", principal=cust)
		name = log_container_activity(
			c, "Gate In", reference_doctype="Container", reference_name=c, to_status="Gate_In", summary="x"
		)
		self.assertTrue(name)
		row = frappe.get_doc("Container Activity", name)
		self.assertEqual(row.container, c)
		self.assertEqual(row.activity_type, "Gate In")
		self.assertEqual(row.principal, cust)  # denormalized from the container

	def test_helper_resilient_to_bad_container(self):
		# A bad/missing container must not raise — audit logging is best-effort.
		self.assertIsNone(log_container_activity(None, "Gate In"))

	def test_append_only_blocks_non_system_manager(self):
		c = _make_container("ACTAPP00001")
		name = log_container_activity(c, "Gate In")
		doc = frappe.get_doc("Container Activity", name)
		# Simulate an edit cycle: on_update compares against the pre-save snapshot.
		doc._doc_before_save = frappe.get_doc("Container Activity", name)
		doc.summary = "tampered"
		with mock.patch("frappe.get_roles", return_value=["Container Depot"]):
			with self.assertRaises(frappe.ValidationError):
				doc.on_update()
			with self.assertRaises(frappe.ValidationError):
				doc.on_trash()


class TestContainerActivityWiring(FrappeTestCase):
	def test_gate_entry_logs_activity(self):
		cust = ensure_test_customer("Activity Gate Cust")
		c = _make_container("ACTGATE0001", principal=cust)
		code = make_booking_code(customer=cust, container_no="ACTGATE0001", container=c)
		ge = frappe.get_doc({
			"doctype": "Gate Entry",
			"booking_code": code.name,
			"container_no": "ACTGATE0001",
			"container": c,
			"gate_in_timestamp": now_datetime(),
			"security_guard": "Administrator",
		})
		ge.insert(ignore_permissions=True)
		ge.submit()
		acts = _activities(c, "Gate In")
		self.assertEqual(len(acts), 1)
		self.assertEqual(acts[0]["reference_doctype"], "Gate Entry")
		self.assertEqual(acts[0]["reference_name"], ge.name)
		self.assertEqual(acts[0]["to_status"], "Gate_In")

	def test_inspection_logs_activity(self):
		c = _make_container("ACTINSP0001", status="Gate_In")
		insp = frappe.get_doc({
			"doctype": "Inspection",
			"container": c,
			"inspection_type": "EIR-In",
			"inspector": "Administrator",
			"status": "Draft",
		})
		insp.insert(ignore_permissions=True)
		insp.submit()
		acts = _activities(c, "Inspection (EIR)")
		self.assertEqual(len(acts), 1)
		self.assertEqual(acts[0]["reference_name"], insp.name)
		self.assertEqual(acts[0]["to_status"], "Inspecting")

	def test_cleaning_certificate_logs_activity(self):
		c = _make_container("ACTCERT0001")
		cert = frappe.get_doc({
			"doctype": "Cleaning Certificate",
			"container": c,
			"cleaning_method": "PP Wash",
		})
		cert.insert(ignore_permissions=True)
		cert.submit()
		acts = _activities(c, "Cleaning Certificate")
		self.assertEqual(len(acts), 1)
		self.assertEqual(acts[0]["reference_name"], cert.name)

	def test_periodic_test_logs_activity(self):
		c = _make_container("ACTPTST0001")
		pt = frappe.get_doc({
			"doctype": "Periodic Test",
			"container": c,
			"test_type": "2,5Y",
			"periodic_date": today(),
		})
		pt.insert(ignore_permissions=True)
		pt.submit()
		acts = _activities(c, "Periodic Test")
		self.assertEqual(len(acts), 1)
		self.assertEqual(acts[0]["reference_name"], pt.name)


class TestContainerActivityReportAndBackfill(FrappeTestCase):
	def test_report_filters(self):
		from container_depot.operations.report.container_activity.container_activity import execute

		c = _make_container("ACTRPT00001")
		log_container_activity(c, "Gate In")
		log_container_activity(c, "Cleaning")
		_, all_rows = execute({"container": c})
		self.assertEqual(len(all_rows), 2)
		_, gate_rows = execute({"container": c, "activity_type": "Gate In"})
		self.assertEqual({r["activity_type"] for r in gate_rows}, {"Gate In"})

	def test_backfill_from_movement(self):
		from container_depot.patches.v0_23.backfill_container_activity import execute as backfill

		c = _make_container("ACTBKFL0001", status="Available")
		# A status change auto-creates a Container Movement.
		doc = frappe.get_doc("Container", c)
		doc.status = "Gate_In"
		doc.save(ignore_permissions=True)
		mv = frappe.db.get_value("Container Movement", {"container": c}, "name")
		self.assertTrue(mv)

		# The patch commits; neutralize it so the test stays inside its rollback.
		with mock.patch("frappe.db.commit"):
			backfill()
			acts = frappe.get_all(
				"Container Activity",
				filters={"reference_doctype": "Container Movement", "reference_name": mv},
			)
			self.assertEqual(len(acts), 1)
			backfill()  # idempotent — no duplicate
			acts = frappe.get_all(
				"Container Activity",
				filters={"reference_doctype": "Container Movement", "reference_name": mv},
			)
			self.assertEqual(len(acts), 1)
