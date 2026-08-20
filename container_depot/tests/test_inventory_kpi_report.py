"""Inventory KPI per Principal — the per-principal roll-up behind the depot dashboard.

The report once crashed in production with ``Table 'tabPeriodic Test' doesn't exist``: it
still queried a doctype that had been dropped out from under it, and nothing executed the
report in CI. The smoke test below is the guard — it runs every query the report issues, so
any other doctype that gets renamed or dropped fails here instead of in the browser.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot.report.inventory_kpi_per_principal.inventory_kpi_per_principal import (
	execute,
)

_DEPOT = "OAK1"


class TestInventoryKpiReport(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_runs_without_error_and_has_expected_columns(self):
		columns, data = execute({})
		names = {c["fieldname"] for c in columns}
		self.assertTrue({"principal", "stock_in_depo", "total_cleaned"} <= names)
		self.assertIsInstance(data, list)

	def test_depot_filter_runs_every_query(self):
		"""The depot-scoped branch takes a different code path in each sub-query."""
		columns, data = execute({"depot": _DEPOT})
		self.assertTrue(columns)
		self.assertIsInstance(data, list)
