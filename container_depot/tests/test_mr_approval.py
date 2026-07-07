"""M&R owner-approval workflow (operations.mr + the Repair Order controller).

The estimate must be submitted to the container owner and approved before any work
starts (approval is mandatory). The owner may approve, reject, or request a revision,
and may approve only some lines (partial approval, per Repair Used Item). Only Approved
lines drive ``total_cost`` and the stock issue on completion.

Pricing is wired through a per-owner Price List so the totals are real. All fixtures use
the ``MRA`` prefix and are removed in tearDown (stock entries are cancelled too).
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from container_depot.operations import eir, mr
from container_depot.tests.test_eir import _make_container

_CUST = "MRA Test Owner"
_PL = "MRA Test PL"
_PART = "MRA-PART"     # stock item, priced 100
_SERVICE = "MRA-LABOR"  # non-stock service, priced 50
_WH_NAME = "MRA Test Store"


class TestMRApproval(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._containers, self._orders, self._inspections, self._stock_entries = [], [], [], []
		self.company = mr._resolve_company()
		self._neg_stock = frappe.db.get_single_value("Stock Settings", "allow_negative_stock")
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
		self._ensure_owner_pricing()

	def _safe(self, fn):
		try:
			fn()
		except Exception:
			frappe.db.rollback()

	def tearDown(self):
		touched = frappe.get_all("Stock Entry Detail", filters={"item_code": _PART}, pluck="parent", distinct=True)
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
		self._safe(lambda: frappe.db.delete("Bin", {"item_code": _PART}))
		self._safe(lambda: frappe.db.delete("Item Price", {"price_list": _PL}))
		self._safe(lambda: frappe.db.exists("Price List", _PL) and frappe.delete_doc("Price List", _PL, force=True, ignore_permissions=True))
		wh = self._wh_name()
		for dt, name in (("Item", _PART), ("Item", _SERVICE), ("Warehouse", wh), ("Customer", _CUST)):
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
	def _ensure_owner_pricing(self):
		grp = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"
		for code, name, stock in ((_PART, "MRA Part", 1), (_SERVICE, "MRA Labor", 0)):
			if not frappe.db.exists("Item", code):
				frappe.get_doc({
					"doctype": "Item", "item_code": code, "item_name": name,
					"item_group": grp, "stock_uom": "Nos", "is_stock_item": stock, "is_sales_item": 1,
				}).insert(ignore_permissions=True)
		if not frappe.db.exists("Price List", _PL):
			frappe.get_doc({
				"doctype": "Price List", "price_list_name": _PL, "currency": "USD", "selling": 1, "enabled": 1,
			}).insert(ignore_permissions=True)
		for code, rate in ((_PART, 100.0), (_SERVICE, 50.0)):
			if not frappe.db.exists("Item Price", {"item_code": code, "price_list": _PL, "selling": 1}):
				frappe.get_doc({
					"doctype": "Item Price", "item_code": code, "price_list": _PL,
					"selling": 1, "price_list_rate": rate,
				}).insert(ignore_permissions=True)
		if not frappe.db.exists("Customer", _CUST):
			frappe.get_doc({
				"doctype": "Customer", "customer_name": _CUST,
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
			}).insert(ignore_permissions=True)
		frappe.db.set_value("Customer", _CUST, "default_price_list", _PL)

	def _wh_name(self):
		return frappe.db.get_value("Warehouse", {"warehouse_name": _WH_NAME, "company": self.company}, "name")

	def _ensure_warehouse(self):
		existing = self._wh_name()
		if existing:
			return existing
		return frappe.get_doc({
			"doctype": "Warehouse", "warehouse_name": _WH_NAME, "company": self.company, "is_group": 0,
		}).insert(ignore_permissions=True).name

	def _receive_stock(self, warehouse, qty):
		se = frappe.get_doc({
			"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "company": self.company,
			"to_warehouse": warehouse, "set_posting_time": 1,
			"posting_date": frappe.utils.add_days(frappe.utils.today(), -1), "posting_time": "00:00:00",
			"items": [{"item_code": _PART, "qty": qty, "t_warehouse": warehouse, "basic_rate": 1000}],
		})
		se.insert(ignore_permissions=True)
		se.submit()
		self._stock_entries.append(se.name)
		return se.name

	def _draft_ro(self, cno):
		c = _make_container(cno, principal=_CUST)
		self._containers.append(c)
		res = eir.create_eir(
			inspection_type="EIR-In", container=c,
			lines=[{"item_code": "11", "damage_code": "12", "remarks": "valve"}], submit=True,
		)
		self._inspections.append(res["name"])
		ro = frappe.db.get_value("Repair Order", {"container": c}, "name")
		self._orders.append(ro)
		return c, ro

	def _submit(self, ro, used_items, warehouse=None):
		mr.save_mr_order(repair_order=ro, used_items=used_items, warehouse=warehouse, submit=False)
		mr.submit_for_approval(ro)

	# --- submit ---------------------------------------------------------------
	def test_submit_requires_item(self):
		_, ro = self._draft_ro("MRAREQ00001")
		with self.assertRaises(frappe.ValidationError):
			mr.submit_for_approval(ro)

	def test_submit_sets_pending_and_parks_container(self):
		c, ro = self._draft_ro("MRAPEN00001")
		self._submit(ro, [{"item": _SERVICE, "quantity": 1}])
		doc = frappe.get_doc("Repair Order", ro)
		self.assertEqual(doc.status, "Pending Approval")
		self.assertIsNotNone(doc.requested_on)
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "In_Depot")

	# --- approve --------------------------------------------------------------
	def test_approve_all_totals_every_line(self):
		_, ro = self._draft_ro("MRAALL00001")
		self._submit(ro, [{"item": _PART, "quantity": 1}, {"item": _SERVICE, "quantity": 1}])
		mr.record_decision(ro, "Approved")
		doc = frappe.get_doc("Repair Order", ro)
		self.assertEqual(doc.status, "Approved")
		self.assertTrue(all(r.decision == "Approved" for r in doc.used_items))
		self.assertEqual(flt(doc.total_cost), 150.0)  # 100 + 50
		self.assertIsNotNone(doc.decided_on)

	def test_partial_approval_excludes_rejected_from_total(self):
		_, ro = self._draft_ro("MRAPAR00001")
		self._submit(ro, [{"item": _PART, "quantity": 1}, {"item": _SERVICE, "quantity": 2}])
		# Approve the part (100), reject the service (2 × 50 = 100) — aligned by line order.
		mr.record_decision(ro, "Approved", line_decisions=["Approved", "Rejected"])
		doc = frappe.get_doc("Repair Order", ro)
		self.assertEqual(doc.status, "Approved")
		self.assertEqual(doc.used_items[0].decision, "Approved")
		self.assertEqual(doc.used_items[1].decision, "Rejected")
		self.assertEqual(flt(doc.total_cost), 100.0)  # rejected line excluded

	def test_approve_requires_at_least_one_line(self):
		_, ro = self._draft_ro("MRANON00001")
		self._submit(ro, [{"item": _SERVICE, "quantity": 1}])
		with self.assertRaises(frappe.ValidationError):
			mr.record_decision(ro, "Approved", line_decisions=["Rejected"])

	# --- reject ---------------------------------------------------------------
	def test_reject_marks_all_and_clears_repair(self):
		c, ro = self._draft_ro("MRAREJ00001")
		self._submit(ro, [{"item": _SERVICE, "quantity": 1}])
		mr.record_decision(ro, "Rejected", note="owner declined")
		doc = frappe.get_doc("Repair Order", ro)
		self.assertEqual(doc.status, "Rejected")
		self.assertEqual(doc.owner_note, "owner declined")
		self.assertTrue(all(r.decision == "Rejected" for r in doc.used_items))
		self.assertEqual(frappe.db.get_value("Container", c, "repair_status"), "Not_Required")

	# --- revision loop --------------------------------------------------------
	def test_revision_loop_returns_to_editable(self):
		_, ro = self._draft_ro("MRAREV00001")
		self._submit(ro, [{"item": _SERVICE, "quantity": 1}])
		mr.record_decision(ro, "Revision Requested", note="please adjust")
		doc = frappe.get_doc("Repair Order", ro)
		self.assertEqual(doc.status, "Revision Requested")
		self.assertEqual(doc.revision_no, 1)
		self.assertEqual(doc.owner_note, "please adjust")
		# Editable again — change the estimate and re-submit; decisions reset to Pending.
		mr.save_mr_order(repair_order=ro, used_items=[{"item": _PART, "quantity": 2}], submit=False)
		mr.submit_for_approval(ro)
		doc = frappe.get_doc("Repair Order", ro)
		self.assertEqual(doc.status, "Pending Approval")
		self.assertEqual(doc.used_items[0].item, _PART)
		self.assertEqual(doc.used_items[0].decision, "Pending")

	# --- guards ---------------------------------------------------------------
	def test_controller_rejects_illegal_transition(self):
		_, ro = self._draft_ro("MRAGRD00001")
		doc = frappe.get_doc("Repair Order", ro)
		doc.status = "Completed"  # Draft -> Completed is not allowed
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	# --- detail payload -------------------------------------------------------
	def test_detail_exposes_prices_and_actions(self):
		_, ro = self._draft_ro("MRADET00001")
		self._submit(ro, [{"item": _PART, "quantity": 1}])
		d = mr.get_mr_order_detail(ro)
		self.assertEqual(d["status"], "Pending Approval")
		self.assertEqual(flt(d["used_items"][0]["rate"]), 100.0)
		self.assertEqual(flt(d["used_items"][0]["amount"]), 100.0)
		self.assertEqual(d["used_items"][0]["decision"], "Pending")
		self.assertEqual(flt(d["total_cost"]), 100.0)
		self.assertIn("Approved", d["actions"])

	# --- stock issue only for approved lines ----------------------------------
	def test_complete_issues_only_approved_stock(self):
		warehouse = self._ensure_warehouse()
		self._receive_stock(warehouse, 10)
		c, ro = self._draft_ro("MRASTK00001")
		# Part (stock) rejected, service approved → completion issues NO stock.
		self._submit(ro, [{"item": _PART, "quantity": 4}, {"item": _SERVICE, "quantity": 1}], warehouse=warehouse)
		mr.record_decision(ro, "Approved", line_decisions=["Rejected", "Approved"])
		mr.start_repair(ro)
		res = mr.save_mr_order(repair_order=ro, submit=True)
		self.assertEqual(res["status"], "Completed")
		self.assertIsNone(res["stock_entry"])  # the only stock line was rejected
		self.assertEqual(flt(mr._on_hand(_PART, warehouse)), 10.0)  # untouched
		self.assertEqual(frappe.db.get_value("Container", c, "status"), "Available")
