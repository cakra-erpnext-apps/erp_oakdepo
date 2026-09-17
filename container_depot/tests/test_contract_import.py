"""Import baris tarif Depot Contract dari paste Excel (``import_tariff_lines``).

Parsing, default dari Base Contract, item tak dikenal, mode replace, dan penjaga status
(hanya kontrak yang masih bisa diedit). Test-test ini dulu menumpang di
``test_service_menu.py``; file itu ikut turun bersama fitur Depot Service Menu (patch
v0_92) sementara import-nya tetap hidup.

Fixture memakai awalan ``ZZ-IMP-TEST`` dan dihapus di tearDown.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot.doctype.depot_contract import depot_contract

_PREFIX = "ZZ-IMP-TEST"
_CUST = "ZZ Imp Test Customer"
_BASE_CUST = "ZZ Imp Base Customer"


class TestContractTariffImport(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._contracts = []
		group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"
		self._ensure_item(f"{_PREFIX}-A", group)
		self._ensure_item(f"{_PREFIX}-B", group)
		# The rate card the import cribs its defaults from is another CONTRACT now.
		self._base = self._base_contract([
			{"item": f"{_PREFIX}-A", "rate": 100.0, "manhour_rate": 0.0, "currency": "USD"},
			{"item": f"{_PREFIX}-B", "rate": 200.0, "manhour_rate": 5.0, "currency": "USD"},
		])
		frappe.db.commit()

	def _safe(self, fn):
		try:
			fn()
		except Exception:
			frappe.db.rollback()

	def tearDown(self):
		# Raw delete: Depot Contract.on_trash refuses to delete anything past Draft
		# (contracts are Voided / Amended, never removed), and this fixture makes Void ones.
		self._safe(lambda: self._contracts and frappe.db.delete("Depot Contract", {"name": ("in", self._contracts)}))
		self._safe(lambda: self._contracts and frappe.db.delete("Tariff Rate", {"parent": ("in", self._contracts)}))
		for code in (f"{_PREFIX}-A", f"{_PREFIX}-B"):
			self._safe(lambda code=code: frappe.db.exists("Item", code) and frappe.delete_doc("Item", code, force=True, ignore_permissions=True))
		for cust in (_CUST, _BASE_CUST):
			self._safe(lambda cust=cust: frappe.db.exists("Customer", cust) and frappe.delete_doc("Customer", cust, force=True, ignore_permissions=True))
		frappe.db.commit()
		super().tearDown()

	# --- fixtures -------------------------------------------------------------
	def _ensure_item(self, code, group):
		if frappe.db.exists("Item", code):
			return
		frappe.get_doc({
			"doctype": "Item", "item_code": code, "item_name": code,
			"item_group": group, "stock_uom": "Nos",
			"is_stock_item": 0, "is_sales_item": 1,
		}).insert(ignore_permissions=True)

	def _customer(self, name=_CUST):
		if frappe.db.exists("Customer", name):
			return name
		frappe.get_doc({
			"doctype": "Customer", "customer_name": name,
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
			"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
		}).insert(ignore_permissions=True)
		return name

	def _base_contract(self, lines):
		"""The contract whose lines the import copies defaults from. Draft on purpose: being
		cribbed from has nothing to do with being live, and the picker says so."""
		doc = frappe.get_doc({
			"doctype": "Depot Contract", "customer": self._customer(_BASE_CUST),
			"status": "Draft", "payment_type": "Cash", "currency": "USD",
			"valid_from": "2026-01-01", "valid_to": "2030-12-31",
			"tariff_lines": lines,
		}).insert(ignore_permissions=True)
		self._contracts.append(doc.name)
		return doc.name

	def _draft_contract(self, status="Draft"):
		doc = frappe.get_doc({
			"doctype": "Depot Contract", "customer": self._customer(),
			"status": status, "payment_type": "Cash",
			"currency": "USD", "base_contract": self._base,
			"valid_from": "2026-01-01", "valid_to": "2030-12-31",
		}).insert(ignore_permissions=True)
		self._contracts.append(doc.name)
		return doc

	# --- paste-import ---------------------------------------------------------
	def test_import_paste_with_defaults_and_unknown(self):
		c = self._draft_contract()
		text = f"{_PREFIX}-A\n{_PREFIX}-B\t250\nNOPE-UNKNOWN"
		res = depot_contract.import_tariff_lines(c.name, text)
		self.assertEqual(res["added"], 2)
		self.assertEqual(len(res["errors"]), 1)
		c.reload()
		rows = {r.item: r for r in c.tariff_lines}
		self.assertEqual(rows[f"{_PREFIX}-A"].rate, 100.0)   # default from base PL
		self.assertEqual(rows[f"{_PREFIX}-B"].rate, 250.0)   # pasted override
		self.assertEqual(rows[f"{_PREFIX}-A"].uom, "Nos")    # uom default from PL

	def test_import_match_by_item_name(self):
		c = self._draft_contract()
		# Items here have item_name == item_code; resolution by name still works.
		res = depot_contract.import_tariff_lines(c.name, f"{_PREFIX}-A")
		self.assertEqual(res["added"], 1)

	def test_import_replace_clears_first(self):
		c = self._draft_contract()
		depot_contract.import_tariff_lines(c.name, f"{_PREFIX}-A\n{_PREFIX}-B")
		res = depot_contract.import_tariff_lines(c.name, f"{_PREFIX}-A", replace=1)
		c.reload()
		self.assertEqual(len(c.tariff_lines), 1)
		self.assertEqual(res["total_lines"], 1)

	def test_import_blocked_when_not_editable(self):
		c = self._draft_contract(status="Void")
		with self.assertRaises(frappe.ValidationError):
			depot_contract.import_tariff_lines(c.name, f"{_PREFIX}-A")
