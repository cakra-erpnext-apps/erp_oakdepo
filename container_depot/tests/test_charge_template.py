"""Ambil Charges / Charge Template: lines copied between M&R, Cleaning and templates, priced
from the source or from the tank owner's contract, and a short part that lands on a draft
but cannot move the order on.

Fixtures use the ``CHGT`` prefix and are removed in tearDown.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot import mr
from container_depot.container_depot.doctype.charge_template.charge_template import (
	get_charges,
	save_as_template,
)
from container_depot.tests.test_eir import _make_container
from container_depot.tests.test_pricing_model import _contract, _drop_contracts, _ensure_item

_OWNER = "CHGT Owner"
_PRICED, _UNPRICED, _PART = "CHGT-WASH", "CHGT-SEAL", "CHGT-PART"
_TEMPLATES = ("CHGT Standar", "CHGT From Order")


class TestChargeTemplate(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		_ensure_item(_PRICED)
		_ensure_item(_UNPRICED)
		if not frappe.db.exists("Item", _PART):
			frappe.get_doc({
				"doctype": "Item", "item_code": _PART, "item_name": _PART, "stock_uom": "Nos",
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"is_stock_item": 1, "is_sales_item": 1,
			}).insert(ignore_permissions=True)
		_contract(_OWNER, [{"item": _PRICED, "rate": 36, "manhour_rate": 4, "currency": "USD"}])
		self.container = _make_container("CHGT0000001", principal=_OWNER)
		self.template = frappe.get_doc({
			"doctype": "Charge Template", "template_name": _TEMPLATES[0],
			"items": [
				{"item": _PRICED, "quantity": 2, "rate": 10, "manhour_rate": 1, "currency": "IDR", "remark": "a"},
				{"item": _UNPRICED, "quantity": 1, "rate": 5, "currency": "IDR"},
			],
		}).insert(ignore_permissions=True)
		self.company = mr._resolve_company()
		self.wh = frappe.db.get_value("Warehouse", {"warehouse_name": "CHGT Store", "company": self.company}) or frappe.get_doc({
			"doctype": "Warehouse", "warehouse_name": "CHGT Store", "company": self.company, "is_group": 0,
		}).insert(ignore_permissions=True).name

	def tearDown(self):
		frappe.set_user("Administrator")
		for ro in frappe.get_all("Repair Order", filters={"container": self.container}, pluck="name"):
			for child in ("Repair Used Item", "Repair Cost Total"):
				frappe.db.delete(child, {"parent": ro})
			frappe.db.delete("Repair Order", {"name": ro})
		for co in frappe.get_all("Cleaning Order", filters={"container": self.container}, pluck="name"):
			frappe.db.delete("Cleaning Order Service", {"parent": co})
			frappe.db.delete("Cleaning Order", {"name": co})
		frappe.db.delete("Container Activity", {"container": self.container})
		frappe.db.delete("Container", {"name": self.container})
		frappe.db.delete("Charge Template Item", {"parent": ("in", _TEMPLATES)})
		frappe.db.delete("Charge Template", {"name": ("in", _TEMPLATES)})
		_drop_contracts([_OWNER])
		frappe.db.delete("Customer", {"name": _OWNER})
		frappe.db.delete("Item", {"name": ("in", [_PRICED, _UNPRICED, _PART])})
		frappe.delete_doc("Warehouse", self.wh, force=True, ignore_permissions=True)
		frappe.db.commit()

	def test_rows_map_to_each_target_with_source_prices(self):
		repair = get_charges("Charge Template", self.template.name, "Repair Order")["rows"]
		self.assertEqual(
			[(r["item"], r["quantity"], r["item_rate"], r["manhour_rate"], r["remark"]) for r in repair],
			[(_PRICED, 2, 10, 1, "a"), (_UNPRICED, 1, 5, 0, None)],
		)
		cleaning = get_charges("Charge Template", self.template.name, "Cleaning Order")["rows"]
		self.assertEqual([(r["cleaning_item"], r["rate"]) for r in cleaning], [(_PRICED, 10), (_UNPRICED, 5)])

	def test_contract_price_overrides_only_what_the_contract_prices(self):
		res = get_charges("Charge Template", self.template.name, "Cleaning Order", self.container, "contract")
		self.assertTrue(res["contract"])
		priced, unpriced = res["rows"]
		self.assertEqual((priced["rate"], priced["manhour_rate"], priced["currency"]), (36, 4, "USD"))
		self.assertEqual((unpriced["rate"], unpriced["currency"]), (5, "IDR"))

	def test_order_saves_as_template_and_copies_back(self):
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": self.container,
			"cleaning_services": get_charges("Charge Template", self.template.name, "Cleaning Order")["rows"],
		}).insert(ignore_permissions=True)
		self.assertEqual([r.rate for r in co.cleaning_services], [10, 5])  # copied price is kept
		name = save_as_template("Cleaning Order", co.name, _TEMPLATES[1])
		rows = frappe.get_doc("Charge Template", name).items
		self.assertEqual([(r.item, r.quantity, r.rate) for r in rows], [(_PRICED, 2, 10), (_UNPRICED, 1, 5)])

	def test_short_part_lands_on_setup_but_cannot_be_forwarded(self):
		co = frappe.get_doc({
			"doctype": "Cleaning Order", "container": self.container,
			"cleaning_services": [{"cleaning_item": _PART, "quantity": 1, "warehouse": self.wh}],
		}).insert(ignore_permissions=True)
		self.assertEqual(co.status, "Service Setup")
		co.status = "Pending"
		with self.assertRaises(frappe.ValidationError):
			co.save(ignore_permissions=True)

	def test_short_part_lands_on_mr_draft_but_cannot_be_forwarded(self):
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": self.container,
			"used_items": [{"line_type": "Part", "item": _PART, "quantity": 1, "warehouse": self.wh}],
		}).insert(ignore_permissions=True)
		self.assertEqual(ro.status, "Draft")
		with self.assertRaises(frappe.ValidationError):
			mr.forward_to_team(ro.name)
		self.assertEqual(frappe.db.get_value("Repair Order", ro.name, "status"), "Draft")
