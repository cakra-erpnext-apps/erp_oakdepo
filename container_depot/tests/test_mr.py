"""M&R (Maintenance & Repair) flow (operations.mr): an EIR with damage auto-creates an
editable Draft Repair Order; the team picks inventory parts and completes it, which
issues those parts from stock (a Material Issue Stock Entry) and returns the tank to the
ready pool.

Stock movements + Repair Order saves commit, so created docs (incl. the seeded Material
Receipt and the issued Stock Entry) are cancelled/removed explicitly after each test.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from container_depot.operations import eir, eir_followups, mr
from container_depot.tests.test_eir import _make_container

_ITEM = "MR-TEST-SEALKIT"
_WH_NAME = "MR Test Store"


class TestMaintenanceRepairFlow(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._containers = []
		self._orders = []
		self._inspections = []
		self._stock_entries = []
		self.company = mr._resolve_company()
		# Decouple the stock test from ERPNext's backdated-receipt posting-order quirk
		# inside the test transaction: allow negative stock so the issue always posts
		# (the Bin total — what we assert — is still correct: 10 received - 3 issued = 7).
		self._neg_stock = frappe.db.get_single_value("Stock Settings", "allow_negative_stock")
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)

	def _safe(self, fn):
		"""Run a cleanup step without letting its failure abort the rest of tearDown."""
		try:
			fn()
		except Exception:
			frappe.db.rollback()

	def tearDown(self):
		# Cancel + drop EVERY stock entry that touched the test item (tracked or not —
		# an errored test may have submitted an issue without recording its name), so the
		# test leaves no stock ledger behind. Each step is isolated so one failure can't
		# strand the others (which would poison the next run with leftover containers).
		touched = frappe.get_all("Stock Entry Detail", filters={"item_code": _ITEM}, pluck="parent", distinct=True)
		for se in set(self._stock_entries) | set(touched):
			self._safe(lambda se=se: self._drop_stock_entry(se))
		for o in self._orders:
			self._safe(lambda o=o: frappe.db.delete("Repair Order", {"name": o}))
		for c in self._containers:
			self._safe(lambda c=c: frappe.db.delete("Repair Order", {"container": c}))
			self._safe(lambda c=c: frappe.db.delete("Container Activity", {"container": c}))
			self._safe(lambda c=c: frappe.db.delete("Container", {"name": c}))
		for ins in self._inspections:
			self._safe(lambda ins=ins: frappe.db.delete("Inspection", {"name": ins}))
		self._safe(lambda: frappe.db.delete("Bin", {"item_code": _ITEM}))
		for dt, name in (("Item", _ITEM), ("Warehouse", self._wh_name())):
			if name:
				self._safe(lambda dt=dt, name=name: frappe.db.exists(dt, name) and frappe.delete_doc(dt, name, force=True, ignore_permissions=True))
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", self._neg_stock or 0)
		frappe.db.commit()
		super().tearDown()

	def _drop_stock_entry(self, se):
		if not frappe.db.exists("Stock Entry", se):
			return
		doc = frappe.get_doc("Stock Entry", se)
		if doc.docstatus == 1:
			doc.cancel()
		frappe.delete_doc("Stock Entry", se, force=True, ignore_permissions=True)

	# --- fixtures -------------------------------------------------------------
	def _container(self, cno, **kw):
		c = _make_container(cno, **kw)
		self._containers.append(c)
		return c

	def _wh_name(self):
		return frappe.db.get_value("Warehouse", {"warehouse_name": _WH_NAME, "company": self.company}, "name")

	def _ensure_warehouse(self):
		existing = self._wh_name()
		if existing:
			return existing
		wh = frappe.get_doc({
			"doctype": "Warehouse", "warehouse_name": _WH_NAME, "company": self.company, "is_group": 0,
		}).insert(ignore_permissions=True)
		return wh.name

	def _ensure_item(self):
		if not frappe.db.exists("Item", _ITEM):
			frappe.get_doc({
				"doctype": "Item", "item_code": _ITEM, "item_name": "M&R Test Seal Kit",
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups",
				"stock_uom": "Nos", "is_stock_item": 1,
			}).insert(ignore_permissions=True)
		return _ITEM

	def _receive_stock(self, warehouse, qty):
		"""Seed on-hand stock via a submitted Material Receipt, backdated a day so the
		later Material Issue can never race it in the stock ledger."""
		se = frappe.get_doc({
			"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "company": self.company,
			"to_warehouse": warehouse, "set_posting_time": 1,
			"posting_date": frappe.utils.add_days(frappe.utils.today(), -1), "posting_time": "00:00:00",
			"items": [{"item_code": _ITEM, "qty": qty, "t_warehouse": warehouse, "basic_rate": 1000}],
		})
		se.insert(ignore_permissions=True)
		se.submit()
		self._stock_entries.append(se.name)
		return se.name

	def _eir_with_damage(self, cno):
		c = self._container(cno)
		res = eir.create_eir(
			inspection_type="EIR-In", container=c,
			lines=[{"item_code": "11", "damage_code": "12", "remarks": "valve broken"}], submit=True,
		)
		self._inspections.append(res["name"])
		return c, res["name"]

	# --- auto-create from EIR -------------------------------------------------
	def test_eir_damage_creates_draft_mr(self):
		c, eir_name = self._eir_with_damage("MRDMG000001")
		ro = frappe.db.get_value(
			"Repair Order", {"container": c}, ["name", "status", "inspection"], as_dict=True
		)
		self.assertTrue(ro)
		self._orders.append(ro.name)
		self.assertEqual(ro.status, "Draft")
		self.assertEqual(ro.inspection, eir_name)

	def test_detail_copies_eir_damages(self):
		c, _ = self._eir_with_damage("MRDMG000002")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		d = mr.get_mr_order_detail(ro)
		self.assertEqual(d["container"], c)
		self.assertEqual(d["status"], "Draft")
		# Section 1: the EIR damage entry was copied into the read-only Damages snapshot.
		self.assertGreaterEqual(len(d["damages"]), 1)
		self.assertEqual(d["damages"][0]["damage_code"], "12")
		# Section 2 starts empty (the team adds services/parts); warehouses are offered.
		self.assertEqual(d["used_items"], [])
		self.assertIn("warehouses", d)

	# --- lifecycle ------------------------------------------------------------
	def test_start_marks_in_progress(self):
		c, _ = self._eir_with_damage("MRSTART0001")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		mr.start_repair(ro)
		self.assertEqual(frappe.db.get_value("Repair Order", ro, "status"), "In Progress")
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Repair_In_Progress")

	def test_complete_issues_stock_and_frees_tank(self):
		warehouse = self._ensure_warehouse()
		self._ensure_item()
		self._receive_stock(warehouse, 10)

		c, _ = self._eir_with_damage("MRSTOCK0001")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		mr.start_repair(ro)
		res = mr.save_mr_order(
			repair_order=ro, warehouse=warehouse,
			used_items=[{"item": _ITEM, "quantity": 3, "remark": "Foot valve", "photos": ["/files/x.jpg"]}],
			submit=True,
		)
		self.assertEqual(res["status"], "Completed")
		self.assertTrue(res["stock_entry"])
		self._stock_entries.append(res["stock_entry"])

		# Stock issued: 10 received - 3 consumed = 7 on hand.
		self.assertEqual(flt(mr._on_hand(_ITEM, warehouse)), 7.0)
		# The Material Issue actually moved 3 out.
		se = frappe.get_doc("Stock Entry", res["stock_entry"])
		self.assertEqual(se.stock_entry_type, "Material Issue")
		self.assertEqual(flt(se.items[0].qty), 3.0)
		# Tank back in the ready pool.
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Available")

	def test_complete_without_parts_skips_stock(self):
		c, _ = self._eir_with_damage("MRNOPART001")
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		mr.start_repair(ro)
		# No stockable item used — no Stock Entry, still completes.
		res = mr.save_mr_order(repair_order=ro, used_items=[], submit=True)
		self.assertEqual(res["status"], "Completed")
		self.assertIsNone(res["stock_entry"])
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Available")
