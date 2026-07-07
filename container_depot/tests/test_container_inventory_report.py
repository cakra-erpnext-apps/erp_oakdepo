"""Tests for the Container Inventory live report + the dashboard seeder."""

from __future__ import annotations

import unittest
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot.operations.report.container_inventory.container_inventory import execute
from container_depot.tests.test_api import ensure_test_customer


def _make_container(cno, status, principal, eir_in_date=None):
	return frappe.get_doc({
		"doctype": "Container",
		"container_no": cno,
		"container_type": "ISO Tank",
		"status": status,
		"principal": principal,
		"eir_in_date": eir_in_date,
	}).insert(ignore_permissions=True)


class TestContainerInventoryReport(FrappeTestCase):
	def test_columns_shape(self):
		columns, _ = execute({})
		names = {c["fieldname"] for c in columns}
		self.assertTrue({"container_no", "principal", "inventory_stage", "in_date", "days_in_depo"} <= names)

	def test_in_depo_default_excludes_prearrival_and_departed(self):
		p = ensure_test_customer("InvRpt InDepo Cust")
		_make_container("INVRPTRDY01", "Available", p)   # Ready -> in depo
		_make_container("INVRPTOUT01", "Gate_Out", p)    # Departed -> excluded
		_make_container("INVRPTPRE01", "Booked", p)      # Pre-Arrival -> excluded
		_, data = execute({"principal": p})              # in_depo_only defaults to 1
		cnos = {r["container_no"] for r in data}
		self.assertIn("INVRPTRDY01", cnos)
		self.assertNotIn("INVRPTOUT01", cnos)
		self.assertNotIn("INVRPTPRE01", cnos)

	def test_in_depo_off_includes_all(self):
		p = ensure_test_customer("InvRpt All Cust")
		_make_container("INVRPTALL01", "Available", p)
		_make_container("INVRPTALL02", "Gate_Out", p)
		_, data = execute({"principal": p, "in_depo_only": 0})
		cnos = {r["container_no"] for r in data}
		self.assertEqual(cnos, {"INVRPTALL01", "INVRPTALL02"})

	def test_days_in_depo_computed(self):
		p = ensure_test_customer("InvRpt Age Cust")
		_make_container("INVRPTAGE01", "Available", p, eir_in_date=add_days(today(), -7))
		_, data = execute({"principal": p})
		row = next(r for r in data if r["container_no"] == "INVRPTAGE01")
		self.assertEqual(row["days_in_depo"], 7)

	@unittest.skip("Yard zones / inventory-stage buckets removed in Phase 2 status refactor")
	def test_stage_filter(self):
		p = ensure_test_customer("InvRpt Stage Cust")
		_make_container("INVRPTSTG01", "Available", p)        # Ready
		_make_container("INVRPTSTG02", "In_Depot", p)   # Cleaning
		_, data = execute({"principal": p, "inventory_stage": "Cleaning"})
		cnos = {r["container_no"] for r in data}
		self.assertEqual(cnos, {"INVRPTSTG02"})

	def test_dashboard_seeder_idempotent(self):
		from container_depot.install import (
			INVENTORY_CHARTS,
			INVENTORY_NUMBER_CARDS,
			setup_inventory_dashboard,
		)

		setup_inventory_dashboard()
		setup_inventory_dashboard()  # second run must not duplicate
		# Number Card autonames from label, Dashboard Chart from chart_name.
		for card in INVENTORY_NUMBER_CARDS:
			self.assertTrue(frappe.db.exists("Number Card", card["label"]))
		for chart in INVENTORY_CHARTS:
			self.assertTrue(frappe.db.exists("Dashboard Chart", chart["chart_name"]))
