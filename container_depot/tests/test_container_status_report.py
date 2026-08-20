"""Container Status Report — every order type a tank can carry must reach its column.

The report's whole point is that an operator reads one row instead of opening ten list
views, so the failure that matters is a column that stays empty while the order exists.
Nothing about that is visible in the code: the container link sits on a different child
doctype per parent (Order Bongkar reuses ``Container Booking Item``, Order Muat uses
``Order Container Item``, and the booking itself shares the first with Order Bongkar), so
a wrong pairing silently yields blanks. One fixture per type, then one assertion per
column, is the only thing that catches it.

The readiness half is checked against ``container_status.container_open_orders`` rather
than against a hand-written expectation — the report is supposed to agree with the gate,
and pinning it to the same function is what keeps it agreeing.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot.container_depot.container_status import container_open_orders
from container_depot.container_depot.report.container_status_report.container_status_report import (
	execute,
)
from container_depot.tests.test_api import ensure_test_customer

CUSTOMER = "Status Report Co"
DEPOT = "OAK1"
PREFIX = "CSRT"
TANK = f"{PREFIX}0000001"
BARE = f"{PREFIX}0000002"


def _cleanup():
	names = frappe.get_all("Container", filters={"container_no": ("like", f"{PREFIX}%")}, pluck="name")
	if names:
		for parent, child in (
			("Container Booking", "Container Booking Item"),
			("Order Bongkar", "Container Booking Item"),
			("Order Muat", "Order Container Item"),
			("Gate Out Plan", "Gate Out Plan Item"),
		):
			for p in set(
				frappe.get_all(
					child,
					filters={"container": ("in", names), "parenttype": parent},
					pluck="parent",
				)
			):
				frappe.db.delete(child, {"parent": p})
				frappe.db.delete(parent, {"name": p})
			frappe.db.delete("Booking Code", {"booking": ("in", [])})
		for dt in (
			"Inspection", "Cleaning Order", "Repair Order",
			"Container Position Survey", "Container Movement", "Container Activity",
		):
			frappe.db.delete(dt, {"container": ("in", names)})
		frappe.db.delete("Container", {"name": ("in", names)})
	if frappe.db.exists("Customer", CUSTOMER):
		frappe.db.delete("Customer", {"name": CUSTOMER})
	frappe.db.commit()


class TestContainerStatusReport(FrappeTestCase):
	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		_cleanup()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		_cleanup()
		self.customer = ensure_test_customer(CUSTOMER)
		self._tank(TANK, status="In_Depot")
		self._tank(BARE, status="Available")

	def tearDown(self):
		_cleanup()

	# --- fixtures -------------------------------------------------------------
	def _tank(self, cno, status="In_Depot"):
		return frappe.get_doc({
			"doctype": "Container",
			"container_no": cno,
			"container_type": "ISO Tank",
			"status": status,
			"principal": self.customer,
			"depot": DEPOT,
		}).insert(ignore_permissions=True).name

	def _insert(self, payload, submit=False):
		doc = frappe.get_doc(payload)
		doc.flags.ignore_validate = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		if submit:
			frappe.db.set_value(doc.doctype, doc.name, "docstatus", 1, update_modified=False)
		return doc.name

	def _row(self, container=TANK, **filters):
		_columns, rows = execute(filters)
		match = [r for r in rows if r["container_no"] == container]
		return match[0] if match else None

	# --- the columns ----------------------------------------------------------
	def test_every_order_type_reaches_its_own_column(self):
		expected = {
			"eir_in": self._insert({
				"doctype": "Inspection", "container": TANK, "inspection_type": "EIR-In",
			}),
			"eir_out": self._insert({
				"doctype": "Inspection", "container": TANK, "inspection_type": "EIR-Out",
			}),
			"cleaning_order": self._insert({
				"doctype": "Cleaning Order", "container": TANK,
				"customer": self.customer, "status": "Pending",
			}),
			"repair_order": self._insert({"doctype": "Repair Order", "container": TANK}),
			"position_survey": self._insert({
				"doctype": "Container Position Survey", "container": TANK,
			}),
			"booking": self._insert({
				"doctype": "Container Booking", "direction": "Tank In",
				"customer": self.customer, "principal": self.customer,
				"items": [{"container": TANK, "condition": "EMPTY CLEAN"}],
			}),
			# Order Bongkar's container grid is Container Booking Item, not Order
			# Container Item — the pairing this test exists to pin.
			"order_bongkar": self._insert({
				"doctype": "Order Bongkar", "shipper": self.customer,
				"ex_vessel": "MV STATUS REPORT",
				"containers": [{"container": TANK, "container_no": TANK}],
			}, submit=True),
			"order_muat": self._insert({
				"doctype": "Order Muat", "shipper": self.customer,
				"containers": [{"container": TANK, "container_no": TANK}],
			}, submit=True),
			"gate_out_plan": self._insert({
				"doctype": "Gate Out Plan", "principal": self.customer, "depot": DEPOT,
				"source": "Email", "status": "Open",
				"containers": [{"container": TANK, "target_lift_on": add_days(today(), 3)}],
			}),
		}

		row = self._row()
		self.assertIsNotNone(row, "the tank fell out of its own report")
		for column, name in expected.items():
			with self.subTest(column=column):
				self.assertEqual(row[column], name)

	def test_a_tank_with_no_orders_shows_empty_columns_not_someone_elses(self):
		self._insert({
			"doctype": "Cleaning Order", "container": TANK,
			"customer": self.customer, "status": "Pending",
		})
		row = self._row(BARE)
		self.assertIsNotNone(row)
		self.assertIsNone(row["cleaning_order"])
		self.assertEqual(row["open_orders"], 0)
		self.assertEqual(row["readiness"], "Siap")

	def test_the_newest_document_wins(self):
		self._insert({
			"doctype": "Cleaning Order", "container": TANK,
			"customer": self.customer, "status": "Completed",
		})
		newer = self._insert({
			"doctype": "Cleaning Order", "container": TANK,
			"customer": self.customer, "status": "Pending",
		})
		self.assertEqual(self._row()["cleaning_order"], newer)

	def test_a_cancelled_order_is_not_reported_as_the_tanks_paperwork(self):
		live = self._insert({
			"doctype": "Cleaning Order", "container": TANK,
			"customer": self.customer, "status": "Pending",
		})
		cancelled = self._insert({
			"doctype": "Cleaning Order", "container": TANK,
			"customer": self.customer, "status": "Cancelled",
		})
		frappe.db.set_value("Cleaning Order", cancelled, "docstatus", 2, update_modified=False)

		self.assertEqual(self._row()["cleaning_order"], live)

	# --- readiness ------------------------------------------------------------
	def test_readiness_and_the_count_agree_with_container_open_orders(self):
		self._insert({
			"doctype": "Cleaning Order", "container": TANK,
			"customer": self.customer, "status": "Pending",
		})
		self._insert({"doctype": "Repair Order", "container": TANK, "status": "In Progress"})

		row = self._row()
		self.assertEqual(row["open_orders"], len(container_open_orders(TANK)))
		self.assertEqual(row["readiness"], "Belum: Cleaning, M&R")

	def test_a_finished_order_stops_holding_the_tank(self):
		order = self._insert({
			"doctype": "Cleaning Order", "container": TANK,
			"customer": self.customer, "status": "Pending",
		})
		self.assertEqual(self._row()["readiness"], "Belum: Cleaning")

		frappe.db.set_value("Cleaning Order", order, "status", "Completed", update_modified=False)
		row = self._row()
		self.assertEqual(row["readiness"], "Siap")
		# Finished, but still this tank's paperwork.
		self.assertEqual(row["cleaning_order"], order)

	# --- filters --------------------------------------------------------------
	def test_with_open_work_keeps_only_the_tanks_someone_is_waiting_on(self):
		self._insert({
			"doctype": "Cleaning Order", "container": TANK,
			"customer": self.customer, "status": "Pending",
		})
		_columns, rows = execute({"with_open_work": 1})
		listed = {r["container_no"] for r in rows if r["container_no"].startswith(PREFIX)}
		self.assertEqual(listed, {TANK})

	def test_a_retired_tank_is_out_of_the_report_unless_asked_for(self):
		frappe.db.set_value("Container", BARE, "is_active", 0)

		self.assertIsNone(self._row(BARE))
		self.assertIsNotNone(self._row(BARE, include_retired=1))

	def test_the_principal_filter_scopes_the_rows(self):
		rows = execute({"principal": self.customer})[1]
		self.assertEqual(
			{r["container_no"] for r in rows}, {TANK, BARE},
			"the principal filter let another customer's tanks through",
		)
