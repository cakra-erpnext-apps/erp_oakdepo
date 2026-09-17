"""Tests for the standalone depot pricing helper (pricing_model)."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.install import setup_custom_fields
from container_depot.pricing_model import effective_item_rate, resolve_price


def _contract(customer, lines, currency="USD"):
	"""An Active Depot Contract carrying ``lines`` — the customer's rate card.

	Active is the point: ``active_contract`` only ever answers with one, so a Draft would
	leave every resolver under test reading nothing. Cash keeps the fixture free of payment
	terms and a credit limit, which only TOP contracts are validated for.
	"""
	from frappe.utils import add_days, today

	if not frappe.db.exists("Customer", customer):
		frappe.get_doc({
			"doctype": "Customer", "customer_name": customer, "customer_type": "Company",
		}).insert(ignore_permissions=True)
	return frappe.get_doc({
		"doctype": "Depot Contract",
		"customer": customer,
		"currency": currency,
		"status": "Active" if lines else "Draft",
		"payment_type": "Cash",
		"valid_from": today(),
		"valid_to": add_days(today(), 365),
		"tariff_lines": lines,
	}).insert(ignore_permissions=True).name


def _ensure_item(code):
	"""The catalog item a tariff line points at. Cheap, and not every class seeds it."""
	if not frappe.db.exists("Item", code):
		frappe.get_doc({
			"doctype": "Item", "item_code": code, "item_name": code,
			"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups",
			"stock_uom": "Nos", "is_stock_item": 0, "is_sales_item": 1,
		}).insert(ignore_permissions=True)
	return code


def _drop_contracts(customers):
	"""Contracts and their lines, gone — a leftover Active one silently prices the next test."""
	names = frappe.get_all("Depot Contract", filters={"customer": ("in", customers)}, pluck="name")
	if names:
		frappe.db.delete("Tariff Rate", {"parent": ("in", names)})
		frappe.db.delete("Depot Contract", {"name": ("in", names)})

GROUP = "ZZ Pricing Test Group"
OAK_CUSTOMER = "ZZ Test OAK Principal"
BERT_CUSTOMER = "ZZ Test Bertschi Principal"
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

		# Fixed item: flat rate on the OAK contract, no manhour.
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

		# Two principals, one contract each — the rate card. The repair item carries no flat
		# rate anywhere, just a per-contract labour rate; the fixed item is priced only by OAK.
		cls.contracts = {}
		for customer, manhour_rate, lines in (
			(OAK_CUSTOMER, 4.50, [
				{"item": REPAIR_ITEM, "rate": 0, "manhour_rate": 4.50, "currency": "USD"},
				{"item": FIXED_ITEM, "rate": 36.0, "manhour_rate": 0, "currency": "USD"},
			]),
			(BERT_CUSTOMER, 4.00, [
				{"item": REPAIR_ITEM, "rate": 0, "manhour_rate": 4.00, "currency": "USD"},
			]),
		):
			cls.contracts[customer] = _contract(customer, lines)
		cls.OAK = cls.contracts[OAK_CUSTOMER]
		cls.BERT = cls.contracts[BERT_CUSTOMER]
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		_drop_contracts([OAK_CUSTOMER, BERT_CUSTOMER])
		frappe.db.delete("Item", {"item_code": ("in", [REPAIR_ITEM, FIXED_ITEM])})
		frappe.db.delete("Item Group", {"item_group_name": GROUP})
		frappe.db.commit()
		super().tearDownClass()

	def test_labour_is_never_folded_into_the_rate(self):
		"""The rate is the tariff alone — labour is billed once, on the invoice.

		The repair item carries a manhour in both lists and no flat price, so a resolver
		that still merged labour in would return a non-zero rate here (and the invoice's
		own manhour line would then charge those hours a second time)."""
		for contract in (self.OAK, self.BERT):
			self.assertEqual(effective_item_rate(REPAIR_ITEM, contract), 0.0)

	def test_manhour_is_readable_per_principal(self):
		# The hours stay reachable beside the rate — that is what billing totals.
		from container_depot.pricing import manhour_for

		self.assertAlmostEqual(manhour_for(REPAIR_ITEM, self.OAK), 4.50)
		self.assertAlmostEqual(manhour_for(REPAIR_ITEM, self.BERT), 4.00)
		self.assertEqual(manhour_for(FIXED_ITEM, self.OAK), 0.0)

	def test_fixed_item_uses_its_flat_contract_rate(self):
		self.assertAlmostEqual(effective_item_rate(FIXED_ITEM, self.OAK), 36.0)

	def test_fixed_item_without_price_is_zero(self):
		# The Bertschi contract carries no line for the fixed item.
		self.assertEqual(effective_item_rate(FIXED_ITEM, self.BERT), 0.0)

	def test_unknown_item_is_zero(self):
		self.assertEqual(effective_item_rate("ZZ Does Not Exist", self.OAK), 0.0)

	def test_resolve_price_matches_effective_rate(self):
		self.assertAlmostEqual(
			resolve_price(REPAIR_ITEM, self.OAK), effective_item_rate(REPAIR_ITEM, self.OAK)
		)


# Currency resolution — which of the two possible sources (own contract, the customer's
# billing currency) is allowed to name an order's currency, and when the operator may name it
# instead. There used to be a third, the site price-list catalog, and it won first: "Standard
# Selling" (IDR) shadowed ``Customer.default_currency`` and a USD principal without a contract
# silently produced IDR orders that no form ever showed.
USD_CUSTOMER = "ZZ Currency USD Customer"
BARE_CUSTOMER = "ZZ Currency Bare Customer"
CONTRACT_CUSTOMER = "ZZ Currency Contract Customer"


class TestCurrencyResolution(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_ensure_item(FIXED_ITEM)
		for name, currency in (
			(USD_CUSTOMER, "USD"),
			(BARE_CUSTOMER, None),
			(CONTRACT_CUSTOMER, "IDR"),
		):
			if not frappe.db.exists("Customer", name):
				doc = frappe.get_doc({
					"doctype": "Customer",
					"customer_name": name,
					"customer_type": "Company",
				})
				if currency:
					doc.default_currency = currency
				doc.insert(ignore_permissions=True)
		# The contract case: an Active USD contract against a customer whose master says IDR,
		# which is what makes "the agreement outranks the master" testable. It needs a line to
		# go Active at all — an empty contract is not a rate card and the controller says so.
		cls.contract = _contract(
			CONTRACT_CUSTOMER,
			[{"item": FIXED_ITEM, "rate": 1.0, "currency": "USD"}],
			currency="USD",
		)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		_drop_contracts([USD_CUSTOMER, BARE_CUSTOMER, CONTRACT_CUSTOMER])
		frappe.db.delete("Customer", {"name": ("in", [USD_CUSTOMER, BARE_CUSTOMER, CONTRACT_CUSTOMER])})
		frappe.db.commit()
		super().tearDownClass()

	def test_customer_currency_beats_a_contract_that_is_not_theirs(self):
		"""A USD principal with no contract still bills USD.

		``price_list_for_customer`` used to hand back the site catalog for a contract-less
		customer, and the resolver took that list's currency first — so
		``Customer.default_currency`` was never read and every order came out IDR. Both
		halves are gone: nothing answers for a customer without a contract, and the currency
		is then the customer's own."""
		from container_depot.pricing_model import active_contract, currency_for_customer

		self.assertEqual(currency_for_customer(USD_CUSTOMER, active_contract(USD_CUSTOMER)), "USD")

	def test_a_customer_with_no_contract_has_no_rate_card_at_all(self):
		"""Depot Contract is the only thing that prices an order, in either currency.

		The site catalog used to answer here for a contract-less customer, which put
		agreed-looking numbers on an order nobody had agreed — and in the wrong currency for
		a USD principal, an error of four orders of magnitude nothing downstream can catch.
		No contract, no rate: 0, which the Cashier can see and type over."""
		from container_depot.pricing_model import active_contract

		self.assertIsNone(active_contract(USD_CUSTOMER))
		self.assertIsNone(active_contract(BARE_CUSTOMER))
		self.assertIsNone(active_contract(None))

	def test_own_contract_outranks_the_customers_billing_currency(self):
		"""The contract holds the actual prices, so it names the currency — even when the
		master says otherwise."""
		from container_depot.pricing_model import active_contract, currency_for_customer

		found = active_contract(CONTRACT_CUSTOMER)
		self.assertEqual(found, self.contract)
		self.assertEqual(currency_for_customer(CONTRACT_CUSTOMER, found), "USD")

	def test_company_currency_is_the_last_resort(self):
		"""With nothing to go on the answer is the company's own currency — not a
		hardcoded IDR, which was wrong on any non-IDR site."""
		from container_depot.pricing_model import company_currency, currency_for_customer

		self.assertEqual(currency_for_customer(None, None), company_currency())
		self.assertEqual(
			currency_for_customer(BARE_CUSTOMER, contract=None), company_currency()
		)

	def test_only_a_customer_with_no_source_leaves_the_field_open(self):
		"""What the form's ``read_only_depends_on`` reads: a rate card or a stated billing
		currency is a fact of the agreement (locked); nothing at all is a question for the
		operator (open, defaulting to the company currency)."""
		from container_depot.pricing_model import active_contract, currency_is_locked

		self.assertTrue(currency_is_locked(CONTRACT_CUSTOMER, active_contract(CONTRACT_CUSTOMER)))
		self.assertTrue(currency_is_locked(USD_CUSTOMER, active_contract(USD_CUSTOMER)))
		self.assertFalse(currency_is_locked(BARE_CUSTOMER, active_contract(BARE_CUSTOMER)))

	def test_another_partys_contract_is_not_an_own_rate_card(self):
		"""The question the currency lock turns on. It used to be far slipperier — "is this
		price list this customer's, or a shared catalog that happens to be in use" — and the
		shared answer won. A contract has no shared version: it belongs to one customer."""
		from container_depot.pricing_model import is_own_rate_card

		self.assertFalse(is_own_rate_card(BARE_CUSTOMER, self.contract))
		self.assertTrue(is_own_rate_card(CONTRACT_CUSTOMER, self.contract))

	def test_repair_line_outside_the_rate_card_keeps_the_operators_currency(self):
		"""A line the owner's contract does not price has no currency of its own, so the one
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
