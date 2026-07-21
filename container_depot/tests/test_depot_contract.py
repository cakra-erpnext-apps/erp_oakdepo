"""Tests for the Depot Contract / Tariff Rate doctypes."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot.operations.doctype.depot_contract.depot_contract import (
	get_active_contract,
)
from container_depot.tests.test_api import ensure_test_customer


CUSTOMER_NAME = "Depot Contract Test Co"


def _make_contract(**overrides) -> frappe.model.document.Document:
	defaults = {
		"doctype": "Depot Contract",
		"customer": ensure_test_customer(CUSTOMER_NAME),
		"currency": "IDR",
		"status": "Draft",
		"payment_type": "Cash",
		"valid_from": today(),
		"valid_to": add_days(today(), 365),
	}
	defaults.update(overrides)
	return frappe.get_doc(defaults)


def _cleanup_contract_world():
	"""Remove contracts and the Price Lists / Item Prices they published, plus the
	customer's default-list pointer (Active contracts publish these and commit)."""
	customer = ensure_test_customer(CUSTOMER_NAME)
	pls = frappe.get_all("Price List", filters={"customer": customer}, pluck="name")
	for pl in pls:
		frappe.db.delete("Item Price", {"price_list": pl})
	frappe.db.delete("Depot Contract", {"customer": customer})
	if pls:
		frappe.db.delete("Price List", {"name": ["in", pls]})
	frappe.db.set_value("Customer", customer, "default_price_list", None, update_modified=False)
	frappe.db.commit()


class TestDepotContract(FrappeTestCase):
	def tearDown(self):
		# Per-test cleanup so get_active_contract isn't polluted by previous tests.
		_cleanup_contract_world()
		super().tearDown()

	@classmethod
	def tearDownClass(cls):
		_cleanup_contract_world()
		super().tearDownClass()

	def test_cash_contract_minimal(self):
		c = _make_contract()
		c.insert(ignore_permissions=True)
		self.assertEqual(c.payment_type, "Cash")
		self.assertEqual(c.payment_terms, None)

	def test_top_contract_requires_terms(self):
		c = _make_contract(payment_type="TOP", credit_limit=1_000_000)
		with self.assertRaises(frappe.ValidationError):
			c.insert(ignore_permissions=True)

	def test_top_contract_requires_credit_limit(self):
		c = _make_contract(payment_type="TOP", payment_terms="NET 30", credit_limit=0)
		with self.assertRaises(frappe.ValidationError):
			c.insert(ignore_permissions=True)

	# --- "Both" payment type (customer may transact Cash or TOP) ----------
	def test_both_contract_requires_terms(self):
		# Both allows TOP bookings, so it carries the same credit requirements as TOP.
		c = _make_contract(payment_type="Both", credit_limit=1_000_000)
		with self.assertRaises(frappe.ValidationError):
			c.insert(ignore_permissions=True)

	def test_both_contract_with_terms_ok(self):
		c = _make_contract(payment_type="Both", payment_terms="NET 30", credit_limit=1_000_000)
		c.insert(ignore_permissions=True)
		self.assertEqual(c.payment_type, "Both")
		self.assertEqual(c.payment_terms, "NET 30")

	def test_both_contract_booking_keeps_operator_choice(self):
		c = _make_contract(
			status="Active", payment_type="Both", payment_terms="NET 30", credit_limit=1_000_000,
			tariff_lines=[{"item": "Lift Off", "rate": 250000}],
		)
		c.insert(ignore_permissions=True)

		def synced(pick):
			b = frappe.get_doc({
				"doctype": "Container Booking",
				"customer": ensure_test_customer(CUSTOMER_NAME),
				"contract": c.name,
				"payment_type": pick,
			})
			b._sync_payment_type_from_contract()
			return b.payment_type

		self.assertEqual(synced("TOP"), "TOP")   # operator's pick is kept
		self.assertEqual(synced("Cash"), "Cash")
		self.assertEqual(synced(None), "Cash")   # empty defaults to Cash

	def test_single_mode_contract_forces_booking_payment_type(self):
		c = _make_contract(
			status="Active", payment_type="Cash",
			tariff_lines=[{"item": "Lift Off", "rate": 250000}],
		)
		c.insert(ignore_permissions=True)
		b = frappe.get_doc({
			"doctype": "Container Booking",
			"customer": ensure_test_customer(CUSTOMER_NAME),
			"contract": c.name,
			"payment_type": "TOP",  # ignored — a Cash contract forces Cash
		})
		b._sync_payment_type_from_contract()
		self.assertEqual(b.payment_type, "Cash")

	def test_both_contract_is_postpaid(self):
		from container_depot.monthly_invoicing import _is_postpaid

		cust = ensure_test_customer(CUSTOMER_NAME)
		_make_contract(
			status="Active", payment_type="Both", payment_terms="NET 30", credit_limit=1,
			tariff_lines=[{"item": "Lift Off", "rate": 250000}],
		).insert(ignore_permissions=True)
		# Both carries a credit relationship → monthly scheduler skips; consolidated bills.
		self.assertTrue(_is_postpaid(cust))

	def test_valid_to_must_follow_valid_from(self):
		c = _make_contract(valid_to=add_days(today(), -1))
		with self.assertRaises(frappe.ValidationError):
			c.insert(ignore_permissions=True)

	def test_active_status_requires_tariff_lines(self):
		c = _make_contract(status="Active")
		with self.assertRaises(frappe.ValidationError):
			c.insert(ignore_permissions=True)

	def test_active_contract_with_tariff_lines_ok(self):
		c = _make_contract(
			status="Active",
			tariff_lines=[{"item": "Lift Off", "rate": 250000}],
		)
		c.insert(ignore_permissions=True)
		self.assertEqual(c.status, "Active")
		self.assertEqual(len(c.tariff_lines), 1)

	def test_get_active_contract_returns_active(self):
		_make_contract(
			status="Draft",
			tariff_lines=[{"item": "Standard Cleaning", "rate": 100000}],
		).insert(ignore_permissions=True)
		_make_contract(
			status="Active",
			payment_type="TOP",
			payment_terms="NET 45",
			credit_limit=5_000_000,
			tariff_lines=[{"item": "Lift Off", "rate": 250000}],
		).insert(ignore_permissions=True)

		hit = get_active_contract(ensure_test_customer(CUSTOMER_NAME))
		self.assertIsNotNone(hit)
		self.assertEqual(hit.payment_type, "TOP")
		self.assertEqual(hit.payment_terms, "NET 45")

	# --- price-list publishing -------------------------------------------
	def test_activation_publishes_price_list(self):
		c = _make_contract(status="Active", tariff_lines=[{"item": "Lift Off", "rate": 250000}])
		c.insert(ignore_permissions=True)
		# Named by Customer + contract number, e.g. "Depot Contract Test Co - DCNT-...".
		self.assertTrue(c.generated_price_list)
		self.assertIn(c.name, c.generated_price_list)
		pl = frappe.get_doc("Price List", c.generated_price_list)
		self.assertEqual(pl.enabled, 1)
		self.assertEqual(pl.selling, 1)
		self.assertEqual(pl.customer, ensure_test_customer(CUSTOMER_NAME))
		rate = frappe.db.get_value(
			"Item Price",
			{"item_code": "Lift Off", "price_list": c.generated_price_list, "selling": 1},
			"price_list_rate",
		)
		self.assertEqual(rate, 250000)

	def test_reactivate_updates_price_in_place(self):
		c = _make_contract(status="Active", tariff_lines=[{"item": "Lift Off", "rate": 250000}])
		c.insert(ignore_permissions=True)
		c.tariff_lines[0].rate = 300000
		c.save(ignore_permissions=True)
		prices = frappe.get_all(
			"Item Price",
			filters={"item_code": "Lift Off", "price_list": c.generated_price_list, "selling": 1},
			fields=["price_list_rate"],
		)
		self.assertEqual(len(prices), 1)
		self.assertEqual(prices[0].price_list_rate, 300000)

	def test_new_active_contract_disables_old_list(self):
		c1 = _make_contract(
			status="Active",
			valid_from=add_days(today(), -10),
			tariff_lines=[{"item": "Lift Off", "rate": 250000}],
		)
		c1.insert(ignore_permissions=True)
		c2 = _make_contract(status="Active", tariff_lines=[{"item": "Lift Off", "rate": 260000}])
		c2.insert(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Price List", c1.generated_price_list, "enabled"), 0)
		self.assertEqual(frappe.db.get_value("Price List", c2.generated_price_list, "enabled"), 1)

	def test_void_disables_published_list(self):
		c = _make_contract(status="Active", tariff_lines=[{"item": "Lift Off", "rate": 250000}])
		c.insert(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Price List", c.generated_price_list, "enabled"), 1)
		c.status = "Void"
		c.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Price List", c.generated_price_list, "enabled"), 0)

	def test_duplicate_item_lines_rejected(self):
		c = _make_contract(
			status="Active",
			tariff_lines=[
				{"item": "Lift Off", "rate": 250000},
				{"item": "Lift Off", "rate": 260000},
			],
		)
		with self.assertRaises(frappe.ValidationError):
			c.insert(ignore_permissions=True)

	def test_resolve_tariff_rate_reads_published_list(self):
		from container_depot import pricing

		c = _make_contract(status="Active", tariff_lines=[{"item": "Lift Off", "rate": 250000}])
		c.insert(ignore_permissions=True)
		self.assertEqual(pricing.resolve_tariff_rate(c.name, "Lift Off"), 250000)
		self.assertEqual(pricing.resolve_tariff_rate(c.name, "Nonexistent Item"), 0)

	def test_line_currency_follows_contract(self):
		# Rate / Manhour format in the contract (Base Price List) currency.
		c = _make_contract(currency="USD", status="Draft", tariff_lines=[{"item": "Lift Off", "rate": 36}])
		c.insert(ignore_permissions=True)
		self.assertEqual(c.tariff_lines[0].currency, "USD")

	def test_base_price_list_lines_returns_priced_items(self):
		from container_depot.operations.doctype.depot_contract.depot_contract import base_price_list_lines

		lines = base_price_list_lines("OAK 2026")
		self.assertTrue(any(d["item"] == "Lift Off" and d["rate"] == 36.0 for d in lines))
		self.assertTrue(all({"item", "uom", "rate", "manhour_rate"} <= set(d.keys()) for d in lines))

	def test_base_price_list_query_allows_cribbing_from_any_list(self):
		# The base picker may seed from another customer's list (relaxed filter), but
		# still hides empty / buying-only lists (nothing to copy from those).
		from container_depot.operations.doctype.depot_contract.depot_contract import base_price_list_query

		cust = ensure_test_customer(CUSTOMER_NAME)
		crib = "DCT Crib Source"
		empty = "DCT Empty List"
		for pl in (crib, empty):
			if not frappe.db.exists("Price List", pl):
				frappe.get_doc({
					"doctype": "Price List", "price_list_name": pl, "currency": "IDR",
					"customer": cust, "selling": 1, "buying": 0, "enabled": 1,
				}).insert(ignore_permissions=True)
		if not frappe.db.exists("Item Price", {"item_code": "Lift Off", "price_list": crib}):
			frappe.get_doc({
				"doctype": "Item Price", "item_code": "Lift Off", "price_list": crib,
				"price_list_rate": 111, "selling": 1,
			}).insert(ignore_permissions=True)
		try:
			names = [r[0] for r in base_price_list_query("Price List", "", "name", 0, 100, {})]
			self.assertIn(crib, names)       # customer list with prices now shows
			self.assertIn("OAK 2026", names)  # standard catalog still shows
			self.assertNotIn(empty, names)    # empty list stays hidden
		finally:
			frappe.db.delete("Item Price", {"price_list": ["in", [crib, empty]]})
			frappe.db.delete("Price List", {"name": ["in", [crib, empty]]})
			frappe.db.commit()

	# --- status workflow -------------------------------------------------
	def test_status_transition_guard_blocks_skips(self):
		c = _make_contract(status="Draft", tariff_lines=[{"item": "Lift Off", "rate": 250000}])
		c.insert(ignore_permissions=True)
		# Terminal states are dead ends — Void cannot be walked back to Active.
		c.status = "Void"
		c.save(ignore_permissions=True)
		c.status = "Active"
		with self.assertRaises(frappe.ValidationError):
			c.save(ignore_permissions=True)

	def test_set_status_walks_the_flow_and_publishes(self):
		from container_depot.operations.doctype.depot_contract.depot_contract import set_status

		c = _make_contract(status="Draft", tariff_lines=[{"item": "Lift Off", "rate": 250000}])
		c.insert(ignore_permissions=True)
		# Draft submits straight to Active — the Negotiation step was removed.
		set_status(c.name, "Active")
		self.assertEqual(frappe.db.get_value("Depot Contract", c.name, "status"), "Active")
		self.assertTrue(frappe.db.get_value("Depot Contract", c.name, "generated_price_list"))
		# Active then ends at Expired (the "Invalid" button uses Void instead).
		set_status(c.name, "Expired")
		self.assertEqual(frappe.db.get_value("Depot Contract", c.name, "status"), "Expired")


class TestContainerPrincipalLink(FrappeTestCase):
	"""Quick sanity: Container.principal must accept a Customer name."""

	CONTAINER_NO = "TSTU2222220"  # ISO 11 chars total when stripped

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.customer = ensure_test_customer("Container Principal Link Test Co")

	@classmethod
	def tearDownClass(cls):
		frappe.db.delete("Container", {"container_no": cls.CONTAINER_NO})
		frappe.db.commit()
		super().tearDownClass()

	def test_container_principal_links_to_customer(self):
		c = frappe.get_doc({
			"doctype": "Container",
			"container_no": self.CONTAINER_NO,
			"container_type": "ISO Tank",
			"status": "Available",
			"principal": self.customer,
		})
		c.insert(ignore_permissions=True)
		self.assertEqual(c.principal, self.customer)
