"""EIR / Bon / Gate / Pending Cash Report, dan menu report yang hanya memuat report
yang menunya bisa dibuka user.

Tidak ada yang di-commit di sini: baris test hilang lewat rollback kelas FrappeTestCase.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime, today

from container_depot.container_depot.doctype.pending_cash import pending_cash as pc_mod
from container_depot.container_depot.report.bon_report import bon_report
from container_depot.container_depot.report.pending_cash_report import pending_cash_report


class TestPendingCashReport(FrappeTestCase):
	def _pc(self, name, confidential):
		frappe.get_doc({
			"doctype": "Pending Cash", "name": name, "pending_cash_type": "PCRPT",
			"date": today(), "total": 1000, "status": "Draft", "direction": "Cash Outflow",
			"confidential": confidential, "owner": "someone-else@example.com",
			# Tanpa creation, db_insert menimpa owner dengan user sesi (Administrator).
			"creation": now_datetime(), "modified": now_datetime(),
		}).db_insert()

	def test_confidential_is_hidden_from_non_finance(self):
		"""Report tidak boleh jadi jalan pintas di sekitar centang Confidential."""
		self._pc("PCRPT-OPEN", 0)
		self._pc("PCRPT-SECRET", 1)

		def names():
			_cols, rows, *_ = pending_cash_report.execute({"pending_cash_type": "PCRPT"})
			return {r["pending_cash"] for r in rows}

		self.assertEqual(names(), {"PCRPT-OPEN", "PCRPT-SECRET"})
		with patch.object(pc_mod, "_may_see_confidential", return_value=False):
			self.assertEqual(names(), {"PCRPT-OPEN"})


class TestBonReport(FrappeTestCase):
	def test_muat_takes_its_principal_from_the_booking(self):
		"""Bon Muat tidak menyimpan principal; report mengambilnya dari booking-nya."""
		bons = {
			"Order Bongkar": [{"bon_date": "2026-10-01", "booking": "BK-IN", "principal": "P-IN",
					   "status": "Issued", "bon": "OB-1"}],
			"Order Muat": [{"bon_date": "2026-10-02", "booking": "BK-OUT", "status": "Completed",
					"bon": "OM-1"}],
		}
		with patch.object(frappe, "has_permission", return_value=True), \
		     patch.object(frappe, "get_list", side_effect=lambda dt, **kw: [dict(r) for r in bons[dt]]), \
		     patch.object(frappe, "get_all", return_value=[("BK-OUT", "P-OUT")]):
			_cols, rows, _msg, _chart, summary = bon_report.execute({})
			_cols, only_out, *_ = bon_report.execute({"principal": "P-OUT"})

		self.assertEqual([(r["kind"], r["principal"]) for r in rows],
				 [("Bongkar", "P-IN"), ("Muat", "P-OUT")])
		self.assertEqual([r["bon"] for r in only_out], ["OM-1"])
		self.assertEqual({s["label"]: s["value"] for s in summary}["Belum Selesai"], 1)


class TestReportMenuScope(FrappeTestCase):
	"""Report hanya tampil (sidebar, kartu workspace) kalau menu ref doctype-nya terbuka."""

	USER = "report-menu-scope@example.com"

	def setUp(self):
		frappe.get_doc({
			"doctype": "User", "email": self.USER, "first_name": "Report Scope",
			"send_welcome_email": 0, "roles": [{"role": "Admin Ops"}],
		}).insert(ignore_permissions=True)
		self.addCleanup(frappe.set_user, "Administrator")

	def test_finance_report_is_hidden_from_non_finance(self):
		frappe.set_user(self.USER)
		visible = set(frappe.get_list(
			"Report",
			filters={"name": ["in", ["EIR Report", "Pending Cash Report", "Storage Charges"]]},
			pluck="name",
		))
		# Admin Ops membuka menu Inspection dan Container Booking, tidak menu Pending Cash.
		self.assertEqual(visible, {"EIR Report", "Storage Charges"})
