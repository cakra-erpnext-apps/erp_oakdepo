"""Parts on a Cleaning Order draw from stock the way the M&R's do: each Part row names its
gudang, a gudang that cannot cover the qty refuses the save, and Submit takes the parts out
as one Material Issue. Revert to draft puts them back. No owner approval step.

Fixtures use the ``CLNP`` prefix and are removed in tearDown (stock entries cancelled first).
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from container_depot.container_depot import cleaning, mr
from container_depot.tests.test_eir import _make_container

_PART = "CLNP-PART"
_WH_NAME = "CLNP Test Store"


class TestCleaningParts(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.company = mr._resolve_company()
		self._containers, self._stock_entries = [], []
		if not frappe.db.exists("Item", _PART):
			frappe.get_doc({
				"doctype": "Item", "item_code": _PART, "item_name": "CLNP Gasket",
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"stock_uom": "Nos", "is_stock_item": 1, "is_sales_item": 1,
			}).insert(ignore_permissions=True)
		self.wh = frappe.db.get_value("Warehouse", {"warehouse_name": _WH_NAME, "company": self.company}) or frappe.get_doc({
			"doctype": "Warehouse", "warehouse_name": _WH_NAME, "company": self.company, "is_group": 0,
		}).insert(ignore_permissions=True).name
		receipt = frappe.get_doc({
			"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "company": self.company,
			"to_warehouse": self.wh, "set_posting_time": 1,
			"posting_date": frappe.utils.add_days(frappe.utils.today(), -1), "posting_time": "00:00:00",
			"items": [{"item_code": _PART, "qty": 5, "t_warehouse": self.wh, "basic_rate": 1000}],
		}).insert(ignore_permissions=True)
		receipt.submit()
		self._stock_entries.append(receipt.name)

	def tearDown(self):
		frappe.set_user("Administrator")
		touched = frappe.get_all("Stock Entry Detail", filters={"item_code": _PART}, pluck="parent", distinct=True)
		# Issues before the receipt they drew from, or the receipt refuses to cancel.
		for se in sorted(set(touched) | set(self._stock_entries), key=lambda n: n in self._stock_entries):
			doc = frappe.get_doc("Stock Entry", se)
			if doc.docstatus == 1:
				doc.cancel()
			frappe.delete_doc("Stock Entry", se, force=True, ignore_permissions=True)
		for c in self._containers:
			for co in frappe.get_all("Cleaning Order", filters={"container": c}, pluck="name"):
				frappe.db.delete("Cleaning Order Service", {"parent": co})
				frappe.db.delete("Cleaning Order", {"name": co})
			frappe.db.delete("Container Activity", {"container": c})
			frappe.db.delete("Container", {"name": c})
		frappe.db.delete("Stock Ledger Entry", {"item_code": _PART})
		frappe.db.delete("Bin", {"item_code": _PART})
		frappe.delete_doc("Item", _PART, force=True, ignore_permissions=True)
		frappe.delete_doc("Warehouse", self.wh, force=True, ignore_permissions=True)
		frappe.db.commit()
		super().tearDown()

	def _order(self, cno, qty):
		c = _make_container(cno, status="In_Depot")
		self._containers.append(c)
		return frappe.get_doc({
			"doctype": "Cleaning Order", "container": c, "status": "Pending",
			"cleaning_services": [{"cleaning_item": _PART, "quantity": qty, "warehouse": self.wh}],
		}).insert(ignore_permissions=True)

	def _on_hand(self):
		return flt(frappe.db.get_value("Bin", {"item_code": _PART, "warehouse": self.wh}, "actual_qty"))

	def test_part_row_is_stamped_and_refused_when_short(self):
		co = self._order("CLNP0000001", 2)
		row = co.cleaning_services[0]
		self.assertEqual(row.line_type, "Part")
		self.assertEqual(row.on_hand, "5")
		co.cleaning_services[0].quantity = 9
		with self.assertRaises(frappe.ValidationError):
			co.save(ignore_permissions=True)

	def test_submit_issues_revert_and_cancel_return(self):
		co = self._order("CLNP0000002", 2)
		self.assertEqual(self._on_hand(), 5)  # nothing moves while the lines are editable
		co.submit()
		se = frappe.db.get_value("Cleaning Order", co.name, "stock_entry")
		self.assertTrue(se)
		self.assertEqual(self._on_hand(), 3)

		cleaning.revert_to_draft(co.name)
		self.assertEqual(frappe.db.get_value("Stock Entry", se, "docstatus"), 2)
		self.assertFalse(frappe.db.get_value("Cleaning Order", co.name, "stock_entry"))
		self.assertEqual(self._on_hand(), 5)

		frappe.get_doc("Cleaning Order", co.name).submit()
		self.assertEqual(self._on_hand(), 3)
		# A submitted order is never cancelled: back to Draft (parts return), then Cancel.
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Cleaning Order", co.name).cancel()
		cleaning.revert_to_draft(co.name)
		cleaning.cancel_order(co.name)
		self.assertEqual(self._on_hand(), 5)
