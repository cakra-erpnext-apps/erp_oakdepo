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

		for name in (OAK_PL, BERT_PL):
			if not frappe.db.exists("Price List", name):
				frappe.get_doc({
					"doctype": "Price List",
					"price_list_name": name,
					"currency": "USD",
					"selling": 1,
					"buying": 0,
					"enabled": 1,
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

		# manhour_rate now lives on each Item Price row (per principal). The repair
		# item carries no flat rate, just its per-list labour rate.
		for pl, rate in ((OAK_PL, 4.50), (BERT_PL, 4.00)):
			if not frappe.db.exists("Item Price", {"item_code": REPAIR_ITEM, "price_list": pl}):
				frappe.get_doc({
					"doctype": "Item Price",
					"item_code": REPAIR_ITEM,
					"price_list": pl,
					"price_list_rate": 0,
					"manhour_rate": rate,
					"selling": 1,
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

	def test_labour_is_never_folded_into_the_rate(self):
		"""The rate is the tariff alone — labour is billed once, on the invoice.

		The repair item carries a manhour in both lists and no flat price, so a resolver
		that still merged labour in would return a non-zero rate here (and the invoice's
		own manhour line would then charge those hours a second time)."""
		for pl in (OAK_PL, BERT_PL):
			self.assertEqual(effective_item_rate(REPAIR_ITEM, pl), 0.0)

	def test_manhour_is_readable_per_principal(self):
		# The hours stay reachable beside the rate — that is what billing totals.
		from container_depot.pricing import manhour_for

		self.assertAlmostEqual(manhour_for(REPAIR_ITEM, OAK_PL), 4.50)
		self.assertAlmostEqual(manhour_for(REPAIR_ITEM, BERT_PL), 4.00)
		self.assertEqual(manhour_for(FIXED_ITEM, OAK_PL), 0.0)

	def test_fixed_item_uses_flat_item_price(self):
		self.assertAlmostEqual(effective_item_rate(FIXED_ITEM, OAK_PL), 36.0)

	def test_fixed_item_without_price_is_zero(self):
		# No Item Price in the Bertschi list for the fixed item.
		self.assertEqual(effective_item_rate(FIXED_ITEM, BERT_PL), 0.0)

	def test_unknown_item_is_zero(self):
		self.assertEqual(effective_item_rate("ZZ Does Not Exist", OAK_PL), 0.0)

	def test_resolve_price_matches_effective_rate(self):
		self.assertAlmostEqual(resolve_price(REPAIR_ITEM, OAK_PL), effective_item_rate(REPAIR_ITEM, OAK_PL))


# Currency resolution — which of the three possible sources (own rate card, the customer's
# billing currency, the site catalog) is allowed to name an order's currency, and when the
# operator may name it instead. The old order let ANY price list win first, so the site
# catalog ("Standard Selling", IDR) shadowed ``Customer.default_currency`` and a USD
# principal without a contract silently produced IDR orders that no form ever showed.
USD_CUSTOMER = "ZZ Currency USD Customer"
BARE_CUSTOMER = "ZZ Currency Bare Customer"
CONTRACT_CUSTOMER = "ZZ Currency Contract Customer"
CCY_PL = "ZZ Currency Test PL"


class TestCurrencyResolution(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Price List", CCY_PL):
			frappe.get_doc({
				"doctype": "Price List",
				"price_list_name": CCY_PL,
				"currency": "USD",
				"selling": 1,
				"buying": 0,
				"enabled": 1,
			}).insert(ignore_permissions=True)

		# default_price_list is read-only and contract-driven (a hand edit is refused on an
		# EXISTING customer), so the contract case is seeded at insert time.
		for name, currency, price_list in (
			(USD_CUSTOMER, "USD", None),
			(BARE_CUSTOMER, None, None),
			(CONTRACT_CUSTOMER, "IDR", CCY_PL),
		):
			if not frappe.db.exists("Customer", name):
				doc = frappe.get_doc({
					"doctype": "Customer",
					"customer_name": name,
					"customer_type": "Company",
				})
				if currency:
					doc.default_currency = currency
				if price_list:
					doc.default_price_list = price_list
				doc.insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.db.delete("Customer", {"name": ("in", [USD_CUSTOMER, BARE_CUSTOMER, CONTRACT_CUSTOMER])})
		frappe.db.delete("Price List", {"name": CCY_PL})
		frappe.db.commit()
		super().tearDownClass()

	@property
	def site_catalog(self):
		return frappe.db.get_single_value("Selling Settings", "selling_price_list")

	def test_customer_currency_beats_the_site_catalog(self):
		"""A USD principal with no contract still bills USD.

		This is the regression the whole change exists for: ``price_list_for_customer``
		hands back the site catalog for a contract-less customer, and the old resolver
		took that list's currency first — so ``Customer.default_currency`` was never
		read and every order came out IDR."""
		from container_depot.pricing_model import currency_for_customer, price_list_for_customer

		self.assertEqual(currency_for_customer(USD_CUSTOMER, price_list_for_customer(USD_CUSTOMER)), "USD")

	def test_foreign_customer_does_not_borrow_the_site_catalog_as_a_rate_card(self):
		"""No rate at all beats a rate in the wrong currency.

		The site catalog is priced in the company currency. Seeding a USD order from it
		would stamp IDR figures onto USD lines, and billing reads those numbers as they
		stand — an error of four orders of magnitude that nothing downstream can catch."""
		from container_depot.pricing_model import price_list_for_customer

		self.assertIsNone(price_list_for_customer(USD_CUSTOMER))

	def test_base_currency_customer_still_gets_the_site_catalog(self):
		"""The guard is about currency, not about walk-ins: a customer in the company
		currency keeps the convenience of the shared catalog."""
		from container_depot.pricing_model import company_currency, price_list_for_customer

		catalog = self.site_catalog
		if not catalog or frappe.db.get_value("Price List", catalog, "currency") != company_currency():
			self.skipTest("site has no default selling price list in the company currency")
		self.assertEqual(price_list_for_customer(BARE_CUSTOMER), catalog)

	def test_own_rate_card_outranks_the_customers_billing_currency(self):
		"""The agreed list holds the actual prices, so it names the currency — even when
		the master says otherwise. Locking the field is what keeps the two from drifting."""
		from container_depot.pricing_model import currency_for_customer, price_list_for_customer

		pl = price_list_for_customer(CONTRACT_CUSTOMER)
		self.assertEqual(pl, CCY_PL)
		self.assertEqual(currency_for_customer(CONTRACT_CUSTOMER, pl), "USD")

	def test_company_currency_is_the_last_resort(self):
		"""With nothing to go on the answer is the company's own currency — not a
		hardcoded IDR, which was wrong on any non-IDR site."""
		from container_depot.pricing_model import company_currency, currency_for_customer

		self.assertEqual(currency_for_customer(None, None), company_currency())
		self.assertEqual(
			currency_for_customer(BARE_CUSTOMER, price_list=None), company_currency()
		)

	def test_only_a_customer_with_no_source_leaves_the_field_open(self):
		"""What the form's ``read_only_depends_on`` reads: a rate card or a stated billing
		currency is a fact of the agreement (locked); nothing at all is a question for the
		operator (open, defaulting to the company currency)."""
		from container_depot.pricing_model import currency_is_locked, price_list_for_customer

		self.assertTrue(currency_is_locked(CONTRACT_CUSTOMER, price_list_for_customer(CONTRACT_CUSTOMER)))
		self.assertTrue(currency_is_locked(USD_CUSTOMER, price_list_for_customer(USD_CUSTOMER)))
		self.assertFalse(currency_is_locked(BARE_CUSTOMER, price_list_for_customer(BARE_CUSTOMER)))

	def test_site_catalog_is_not_mistaken_for_an_own_rate_card(self):
		from container_depot.pricing_model import is_own_price_list

		catalog = self.site_catalog
		if not catalog:
			self.skipTest("site has no default selling price list")
		self.assertFalse(is_own_price_list(BARE_CUSTOMER, catalog))
		self.assertTrue(is_own_price_list(CONTRACT_CUSTOMER, CCY_PL))

	def test_repair_line_outside_the_rate_card_keeps_the_operators_currency(self):
		"""A line the owner's list does not price has no currency of its own, so the one
		the operator picked has to survive the save — and the line stays unlocked so the
		form lets them pick it in the first place."""
		ro = frappe.get_doc({
			"doctype": "Repair Order",
			"principal": BARE_CUSTOMER,
			"used_items": [{"item": FIXED_ITEM, "quantity": 1, "currency": "USD", "item_rate": 12.0}],
		})
		ro.calculate_totals()
		row = ro.used_items[0]
		self.assertEqual(row.currency, "USD")
		self.assertFalse(row.currency_locked)
		self.assertEqual([(t.currency, t.total) for t in ro.totals], [("USD", 12.0)])
