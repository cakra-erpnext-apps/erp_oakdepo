"""Cleaning Register dan Repair Register — register semua cleaning dan semua M&R.

Sebelum keduanya ada, order Standard Cleaning / Other dan M&R biasa tidak muncul di register
mana pun: ketiga register cuci hanya memuat jenisnya sendiri, dan Periodic Test Register
hanya uji berkala.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, getdate

from container_depot.container_depot import register_history
from container_depot.container_depot.report.cleaning_register import (
	cleaning_register as cleaning_report,
)
from container_depot.container_depot.report.repair_register import (
	repair_register as repair_report,
)
from container_depot.tests.test_cleaning_type import ensure_item
from container_depot.tests.test_registers import _PRINCIPAL, _RegisterCase


class _Case(_RegisterCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._had_principal = bool(frappe.db.exists("Customer", _PRINCIPAL))

	@classmethod
	def tearDownClass(cls):
		# ensure_test_customer membuat principal-nya; _RegisterCase tidak pernah menghapusnya.
		if not cls._had_principal and frappe.db.exists("Customer", _PRINCIPAL):
			frappe.delete_doc("Customer", _PRINCIPAL, force=True, ignore_permissions=True,
					  delete_permanently=True)
			frappe.db.commit()
		super().tearDownClass()

	def tearDown(self):
		# Bel yang dibangkitkan order test ikut dihapus — order-nya dihapus di super().
		for dt in ("Cleaning Order", "Repair Order"):
			names = frappe.get_all(dt, filters={"container": ["in", self._containers or [""]]},
					       pluck="name")
			if names:
				frappe.db.delete("Notification Log",
						 {"document_type": dt, "document_name": ["in", names]})
		super().tearDown()


class TestCleaningRegister(_Case):
	def _cleaning(self, container, *, services=(), cleaning_type=None, plan_date=None):
		doc = frappe.get_doc({
			"doctype": "Cleaning Order", "container": container, "status": "Service Setup",
			"cleaning_services": [{"cleaning_item": i} for i in services],
		})
		if cleaning_type:
			doc.cleaning_type = cleaning_type
		if plan_date:
			doc.plan_date = plan_date
		return doc.insert(ignore_permissions=True).name

	def _rows(self, filters=None):
		cols, rows, _msg, _chart, summary = cleaning_report.execute(filters or {})
		return cols, self._mine(rows), summary

	def test_every_cleaning_type_is_listed(self):
		"""Standard Cleaning — yang tidak masuk register jenis mana pun — ikut tampil."""
		ensure_item("CLN-STANDARD", "Standard Clean")
		plain = self._container("C1")
		steam = self._container("C2")
		self._cleaning(plain, services=["CLN-STANDARD"])
		self._cleaning(steam, services=["CLN-STANDARD"], cleaning_type="Steam Wash")

		cols, rows, _summary = self._rows()
		self.assertEqual({r["tank_no"] for r in rows}, {plain, steam})
		self.assertIn("cleaning_type", [c["fieldname"] for c in cols])
		by_tank = {r["tank_no"]: r["cleaning_type"] for r in rows}
		self.assertEqual(by_tank[steam], "Steam Wash")

	def test_date_range_defaults_to_the_order_own_date(self):
		"""Tanggal bawaan = Tanggal Cleaning (plan_date), bukan jam order dibuat."""
		ensure_item("CLN-STANDARD", "Standard Clean")
		c = self._container("C3")
		last_week = add_days(getdate(), -7)
		self._cleaning(c, services=["CLN-STANDARD"], plan_date=last_week)

		_cols, rows, _summary = self._rows({"from_date": last_week, "to_date": last_week})
		self.assertEqual([r["tank_no"] for r in rows], [c])
		_cols, rows, _summary = self._rows({"from_date": getdate(), "to_date": getdate()})
		self.assertEqual(rows, [])

	def test_tank_history_reads_the_same_register(self):
		ensure_item("CLN-STANDARD", "Standard Clean")
		c = self._container("C4")
		self._cleaning(c, services=["CLN-STANDARD"])
		out = register_history.tank_history(c, "Cleaning")
		self.assertEqual(len(out["rows"]), 1)


class TestRepairRegister(_Case):
	def _repair(self, container, *, job_type="Repair", status="Draft"):
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": container, "job_type": job_type,
			"status": "Draft", "billing_status": "Unbilled",
		}).insert(ignore_permissions=True)
		if status != "Draft":
			frappe.db.set_value("Repair Order", ro.name, "status", status, update_modified=False)
		return ro.name

	def _rows(self, filters=None):
		_cols, rows, _msg, _chart, summary = repair_report.execute(filters or {})
		return self._mine(rows), {s["label"]: s["value"] for s in summary}

	def test_only_repair_jobs_are_listed(self):
		repair = self._container("R1")
		self._repair(repair)
		self._repair(self._container("R2"), job_type="Periodic Test")
		rows, _summary = self._rows()
		self.assertEqual([r["tank_no"] for r in rows], [repair])

	def test_summary_counts_waiting_and_open(self):
		self._repair(self._container("R3"), status="Pending Approval")
		self._repair(self._container("R4"), status="Completed")
		rows, _summary = self._rows()
		self.assertEqual(len(rows), 2)
		# Ringkasan atas seluruh site; cukup pastikan order test ini terhitung.
		_rows, summary = self._rows({"search": "REGTR"})
		self.assertEqual(summary["Menunggu Approval"], 1)
		self.assertEqual(summary["Selesai"], 1)
		self.assertEqual(summary["Belum Selesai"], 1)

	def test_only_outstanding_drops_completed(self):
		open_tank = self._container("R5")
		self._repair(open_tank)
		self._repair(self._container("R6"), status="Completed")
		rows, _summary = self._rows({"only_outstanding": 1})
		self.assertEqual([r["tank_no"] for r in rows], [open_tank])

	def test_tank_history_reads_the_same_register(self):
		c = self._container("R7")
		self._repair(c)
		out = register_history.tank_history(c, "Repair")
		self.assertEqual([r["repair_order"] for r in out["rows"]],
				 frappe.get_all("Repair Order", filters={"container": c}, pluck="name"))
