"""Tests for the Container Activity unified action-history feed."""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime, today

from container_depot.operations.container_activity import log_container_activity
from container_depot.tests._booking_helpers import make_booking_code
from container_depot.tests.test_api import ensure_test_customer


def _make_container(cno, *, status="Available", principal=None, depot=None):
	return frappe.get_doc({
		"doctype": "Container",
		"container_no": cno,
		"container_type": "ISO Tank",
		"status": status,
		"principal": principal or ensure_test_customer("Activity Test Principal"),
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
			c, "Gate In", reference_doctype="Container", reference_name=c, to_status="In_Depot", summary="x"
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
		# Pre-arrival (Booked) so gate-in is allowed (a present tank can't gate in again).
		c = _make_container("ACTGATE0001", status="Booked", principal=cust)
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
		self.assertEqual(acts[0]["to_status"], "In_Depot")

	def test_inspection_logs_activity(self):
		c = _make_container("ACTINSP0001", status="In_Depot")
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
		self.assertEqual(acts[0]["to_status"], "In_Depot")

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
		doc.status = "In_Depot"
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


class TestContainerActivityBookingToOrderBongkar(FrappeTestCase):
	"""End-to-end: a Booking and the Order Bongkar generated from it each append
	one Container Activity row, linked back to the document that produced it."""

	def test_booking_to_order_bongkar_records_activity(self):
		from container_depot.operations.order_generation import make_order

		cust = ensure_test_customer("Activity Flow Cust")
		# A TOP (postpaid) contract lets the booking submit without the Cash
		# paid-invoice gate, so the whole flow runs in one test.
		frappe.get_doc({
			"doctype": "Depot Contract",
			"customer": cust,
			"currency": "IDR",
			"status": "Active",
			"payment_type": "TOP",
			"payment_terms": "NET 30",
			"credit_limit": 100000000,
			"valid_from": today(),
			"valid_to": add_days(today(), 365),
			"tariff_lines": [{"item": "Lift Off", "rate": 250000}],
		}).insert(ignore_permissions=True)

		# 1) Booking (Tank In). Submit auto-creates the pre-arrival Container,
		#    issues its Booking Code, and logs a "Booking" activity per item.
		booking = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": cust,
			"do_reference": "DO-ACTFLOW-001",
			"items": [{"container_no": "ACTFLOW0001"}],
		}).insert(ignore_permissions=True)
		booking.submit()
		booking.reload()

		container = booking.items[0].container
		code = booking.items[0].booking_code
		self.assertTrue(container, "booking submit should resolve a Container")
		self.assertTrue(code, "booking submit should issue a Booking Code")

		# 2) Generate the Order Bongkar from that booking and submit it — logs an
		#    "Order Bongkar" activity for the same container.
		order = frappe.get_doc("Order Bongkar", make_order(booking.name, [code]))
		order.submit()

		# 3) Inspect the container's unified activity feed.
		feed = frappe.get_all(
			"Container Activity",
			filters={"container": container},
			fields=["activity_time", "activity_type", "reference_doctype", "reference_name", "summary"],
			order_by="activity_time asc, creation asc",
		)
		print(f"\n=== Container Activity feed for {container} ({len(feed)} rows) ===")
		for f in feed:
			stamp = str(f["activity_time"])[:19]
			print(f"  {stamp}  {f['activity_type']:<16} <- {f['reference_doctype']} {f['reference_name']}  | {f['summary'] or ''}")

		by_type = {f["activity_type"]: f for f in feed}
		self.assertIn("Booking", by_type, "Booking activity was not recorded")
		self.assertIn("Order Bongkar", by_type, "Order Bongkar activity was not recorded")
		# Each activity backlinks to the document that produced it.
		self.assertEqual(by_type["Booking"]["reference_doctype"], "Container Booking")
		self.assertEqual(by_type["Booking"]["reference_name"], booking.name)
		self.assertEqual(by_type["Order Bongkar"]["reference_doctype"], "Order Bongkar")
		self.assertEqual(by_type["Order Bongkar"]["reference_name"], order.name)
