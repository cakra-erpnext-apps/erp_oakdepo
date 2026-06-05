"""Tests for the standalone depot pricing helper (pricing_model)."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.install import setup_custom_fields
from container_depot.pricing_model import effective_item_rate, resolve_price

GROUP = "ZZ Pricing Test Group"
OAK_PL = "ZZ Test OAK PL"
BERT_PL = "ZZ Test Bertschi PL"
REPAIR_ITEM = "ZZ Test Repair Valve"
FIXED_ITEM = "ZZ Test Lift On"


class TestPricingModel(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Custom fields (manhour / material_cost / manhour_rate) must exist.
		setup_custom_fields()

		if not frappe.db.exists("Item Group", GROUP):
			frappe.get_doc({
				"doctype": "Item Group",
				"item_group_name": GROUP,
				"parent_item_group": "All Item Groups",
				"is_group": 0,
			}).insert(ignore_permissions=True)

		for name, rate in ((OAK_PL, 4.50), (BERT_PL, 4.00)):
			if not frappe.db.exists("Price List", name):
				frappe.get_doc({
					"doctype": "Price List",
					"price_list_name": name,
					"currency": "USD",
					"selling": 1,
					"buying": 0,
					"enabled": 1,
					"manhour_rate": rate,
				}).insert(ignore_permissions=True)

		# Repair item: priced dynamically (manhour × rate + material), no flat price.
		if not frappe.db.exists("Item", REPAIR_ITEM):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": REPAIR_ITEM,
				"item_name": REPAIR_ITEM,
				"item_group": GROUP,
				"stock_uom": "Nos",
				"is_stock_item": 0,
				"is_sales_item": 1,
				"manhour": 0.5,
				"material_cost": 10.0,
			}).insert(ignore_permissions=True)

		# Fixed item: flat Item Price in the OAK list, no manhour.
		if not frappe.db.exists("Item", FIXED_ITEM):
			frappe.get_doc({
				"doctype": "Item",
				"item_code": FIXED_ITEM,
				"item_name": FIXED_ITEM,
				"item_group": GROUP,
				"stock_uom": "Nos",
				"is_stock_item": 0,
				"is_sales_item": 1,
				"manhour": 0,
			}).insert(ignore_permissions=True)
		if not frappe.db.exists("Item Price", {"item_code": FIXED_ITEM, "price_list": OAK_PL}):
			frappe.get_doc({
				"doctype": "Item Price",
				"item_code": FIXED_ITEM,
				"price_list": OAK_PL,
				"price_list_rate": 36.0,
				"selling": 1,
			}).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.db.delete("Item Price", {"item_code": ("in", [REPAIR_ITEM, FIXED_ITEM])})
		frappe.db.delete("Item", {"item_code": ("in", [REPAIR_ITEM, FIXED_ITEM])})
		frappe.db.delete("Price List", {"name": ("in", [OAK_PL, BERT_PL])})
		frappe.db.delete("Item Group", {"item_group_name": GROUP})
		frappe.db.commit()
		super().tearDownClass()

	def test_repair_item_priced_dynamically_per_principal(self):
		# Same Item, different Price List manhour_rate -> different effective rate.
		self.assertAlmostEqual(effective_item_rate(REPAIR_ITEM, OAK_PL), 0.5 * 4.50 + 10.0)
		self.assertAlmostEqual(effective_item_rate(REPAIR_ITEM, BERT_PL), 0.5 * 4.00 + 10.0)

	def test_fixed_item_uses_flat_item_price(self):
		self.assertAlmostEqual(effective_item_rate(FIXED_ITEM, OAK_PL), 36.0)

	def test_fixed_item_without_price_is_zero(self):
		# No Item Price in the Bertschi list for the fixed item.
		self.assertEqual(effective_item_rate(FIXED_ITEM, BERT_PL), 0.0)

	def test_unknown_item_is_zero(self):
		self.assertEqual(effective_item_rate("ZZ Does Not Exist", OAK_PL), 0.0)

	def test_resolve_price_matches_effective_rate(self):
		self.assertAlmostEqual(resolve_price(REPAIR_ITEM, OAK_PL), effective_item_rate(REPAIR_ITEM, OAK_PL))
