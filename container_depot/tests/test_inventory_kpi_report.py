"""Inventory KPI per Principal — the per-principal roll-up behind the depot dashboard.

The report crashed in production with ``Table 'tabPeriodic Test' doesn't exist``: it still
queried the standalone Periodic Test doctype that patch v0_47 dropped in favour of Periodic
Test Order. Nothing executed the report in CI, so the dead table survived the migration. The
smoke test below is the guard — it runs every query the report issues, so any other doctype
that gets renamed or dropped out from under it fails here instead of in the browser.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot.report.inventory_kpi_per_principal.inventory_kpi_per_principal import (
	execute,
)
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_eir import _make_container

_DEPOT = "OAK1"


class TestInventoryKpiReport(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._principal = ensure_test_customer("IKPI Test Principal")
		self._containers = []
		self._orders = []

	def tearDown(self):
		for o in self._orders:
			frappe.db.delete("Periodic Test Order", {"name": o})
		for c in self._containers:
			frappe.db.delete("Container Activity", {"container": c})
			frappe.db.delete("Periodic Test Order", {"container": c})
			frappe.db.delete("Container", {"name": c})
		frappe.db.commit()
		super().tearDown()

	def _container(self, cno):
		c = _make_container(cno, principal=self._principal, depot=_DEPOT)
		self._containers.append(c)
		return c

	def _pt_order(self, container, test_type, status="Draft"):
		doc = frappe.get_doc({
			"doctype": "Periodic Test Order",
			"container": container,
			"test_type": test_type,
			"status": status,
		}).insert(ignore_permissions=True)
		self._orders.append(doc.name)
		return doc

	def _row(self, depot=None):
		_, data = execute({"depot": depot} if depot else {})
		return next((r for r in data if r["principal"] == self._principal), None)

	def test_runs_without_error_and_has_expected_columns(self):
		columns, data = execute({})
		names = {c["fieldname"] for c in columns}
		self.assertTrue({"principal", "stock_in_depo", "pt_25", "pt_5", "total_cleaned"} <= names)
		self.assertIsInstance(data, list)

	def test_periodic_test_counts_split_by_type(self):
		c1 = self._container("IKPIPT00001")
		c2 = self._container("IKPIPT00002")
		self._pt_order(c1, "2,5Y")
		self._pt_order(c2, "2,5Y")
		self._pt_order(c1, "5Y")

		row = self._row()
		self.assertIsNotNone(row, "principal missing from report")
		self.assertEqual(row["pt_25"], 2)
		self.assertEqual(row["pt_5"], 1)

	def test_cancelled_periodic_tests_are_not_counted(self):
		c = self._container("IKPIPT00003")
		self._pt_order(c, "2,5Y")
		self._pt_order(c, "2,5Y", status="Cancelled")

		self.assertEqual(self._row()["pt_25"], 1)

	def test_depot_filter_scopes_the_counts(self):
		c = self._container("IKPIPT00004")
		self._pt_order(c, "5Y")

		self.assertEqual(self._row(depot=_DEPOT)["pt_5"], 1)
		self.assertIsNone(self._row(depot="OAK2"))
