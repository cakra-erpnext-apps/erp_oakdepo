"""Labour (manhour) is billed ONCE, at invoicing — never folded into a service's rate.

Every line of a contract's Price List carries a **Manhour** beside its Rate: the hours that
service takes. Orders keep the two apart; the invoice is where the hours of everything being
billed are totalled and charged once:

    Total = Total Price + (Total Manhour x Hour)

Both halves of that rule are asserted here: the rate resolver must NOT merge labour into a
service's price, and the invoice funnel every menu goes through must show the hours per line,
total them in the header, and fold that one charge into the grand total.

The contract publishes a Price List, so each test cleans the customer's world back to its
pre-test state.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, today

from container_depot import invoicing, pricing, pricing_model
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_container_booking import _cleanup_customer_world

# Hours the contract books per service (the "Manhour" column of its Price List).
LIFT_OFF_HOURS = 1.5
CLEAN_HOURS = 0.5


class TestManhourBilling(FrappeTestCase):
	CUSTOMER = "Manhour Billing Co"
	NOCON = "Manhour No-Contract Co"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.customer = ensure_test_customer(cls.CUSTOMER)
		cls.nocon = ensure_test_customer(cls.NOCON)
		_cleanup_customer_world(cls.customer)
		_cleanup_customer_world(cls.nocon)
		cls.contract = frappe.get_doc({
			"doctype": "Depot Contract",
			"customer": cls.customer,
			"currency": "IDR",
			"status": "Active",
			"payment_type": "TOP",
			"payment_terms": "NET 30",
			"credit_limit": 1_000_000_000,
			"valid_from": today(),
			"valid_to": add_days(today(), 365),
			"tariff_lines": [
				{"item": "Lift Off", "rate": 250000, "manhour_rate": LIFT_OFF_HOURS},
				{"item": "Standard Clean", "rate": 100000, "manhour_rate": CLEAN_HOURS},
				# A service the contract prices but books no labour for.
				{"item": "Lift On", "rate": 200000},
			],
		}).insert(ignore_permissions=True)
		cls.price_list = cls.contract.generated_price_list
		# ERPNext auto-inserts a missing Item Price when an invoice line prices an item the
		# selling list does not carry (Stock Settings "auto insert price list rate if
		# missing"). Snapshot what exists now so tearDownClass can drop exactly what these
		# tests caused — leaving one behind changes pricing for every later test.
		cls._item_prices_before = set(frappe.get_all("Item Price", pluck="name"))

	@classmethod
	def tearDownClass(cls):
		_cleanup_customer_world(cls.customer)
		_cleanup_customer_world(cls.nocon)
		leaked = set(frappe.get_all("Item Price", pluck="name")) - cls._item_prices_before
		if leaked:
			frappe.db.delete("Item Price", {"name": ("in", list(leaked))})
		frappe.db.commit()
		super().tearDownClass()

	def tearDown(self):
		# Every test raises drafts through the invoice funnel — drop them.
		frappe.db.delete("Sales Invoice", {"customer": ("in", [self.customer, self.nocon]), "docstatus": 0})
		frappe.db.commit()

	def _invoice(self, lines, customer=None, **kw):
		si = invoicing.create_draft_sales_invoice(customer or self.customer, lines, currency="IDR", **kw)
		self.assertTrue(si, "the site must be invoice-ready for this test")
		return frappe.get_doc("Sales Invoice", si)

	def _charge_rows(self, inv):
		"""The labour charge rows (there must never be more than one)."""
		return [t for t in (inv.taxes or []) if (t.description or "").strip() == invoicing.MANHOUR_CHARGE]

	# --- the contract carries hours beside the rate ---------------------------
	def test_contract_publishes_manhour_next_to_rate(self):
		self.assertEqual(pricing.contract_price_list(self.customer), self.price_list)
		self.assertAlmostEqual(pricing.manhour_for("Lift Off", self.price_list), LIFT_OFF_HOURS)
		self.assertAlmostEqual(pricing_model.resolve_price("Lift Off", self.price_list), 250000)

	def test_rate_never_includes_labour(self):
		"""The tariff resolves to the agreed rate alone — labour is not folded in."""
		for item, rate in (("Lift Off", 250000), ("Standard Clean", 100000)):
			self.assertAlmostEqual(pricing_model.resolve_price(item, self.price_list), rate)

	# --- the invoice shows hours per line and totals them once ----------------
	def test_each_line_carries_its_own_manhour(self):
		inv = self._invoice([
			{"item_code": "Lift Off", "qty": 1, "rate": 250000},
			{"item_code": "Standard Clean", "qty": 1, "rate": 100000},
		])
		by_item = {r.item_code: r for r in inv.items}
		self.assertAlmostEqual(flt(by_item["Lift Off"].manhour), LIFT_OFF_HOURS)
		self.assertAlmostEqual(flt(by_item["Standard Clean"].manhour), CLEAN_HOURS)

	def test_manhour_is_not_priced_into_the_line(self):
		"""The hours sit beside the price — the line's own amount is qty × rate, nothing more."""
		inv = self._invoice([{"item_code": "Lift Off", "qty": 2, "rate": 250000}])
		self.assertAlmostEqual(flt(inv.items[0].amount), 500000)
		self.assertAlmostEqual(flt(inv.total), 500000, msg="Total Price excludes labour")
		self.assertAlmostEqual(flt(inv.total_manhour), LIFT_OFF_HOURS, msg="qty must not inflate it")

	def test_total_is_price_plus_hours_times_hour(self):
		inv = self._invoice([
			{"item_code": "Lift Off", "qty": 1, "rate": 250000},
			{"item_code": "Standard Clean", "qty": 1, "rate": 100000},
		])
		hours = LIFT_OFF_HOURS + CLEAN_HOURS
		self.assertAlmostEqual(flt(inv.total_manhour), hours)
		self.assertAlmostEqual(flt(inv.manhour_hour), pricing.DEFAULT_MANHOUR_HOUR)
		self.assertAlmostEqual(flt(inv.manhour_amount), hours * pricing.DEFAULT_MANHOUR_HOUR)
		self.assertAlmostEqual(
			flt(inv.grand_total), flt(inv.total) + hours * pricing.DEFAULT_MANHOUR_HOUR
		)

	def test_hours_do_not_scale_with_quantity(self):
		"""A rate is per unit; a manhour is not — qty must leave the hours alone.

		Only the SUM of the lines' manhours meets a multiplier, and that multiplier is Hour.
		"""
		inv = self._invoice([{"item_code": "Lift Off", "qty": 3, "rate": 250000}])
		self.assertAlmostEqual(flt(inv.total_manhour), LIFT_OFF_HOURS)
		self.assertAlmostEqual(flt(inv.items[0].amount), 750000, msg="the rate still follows qty")
		self.assertAlmostEqual(
			flt(inv.manhour_amount), LIFT_OFF_HOURS * pricing.DEFAULT_MANHOUR_HOUR
		)

	def test_services_priced_without_labour_add_no_hours(self):
		inv = self._invoice([{"item_code": "Lift On", "qty": 2, "rate": 200000}])
		self.assertEqual(flt(inv.total_manhour), 0)
		self.assertEqual(self._charge_rows(inv), [], "no hours -> no labour charge at all")
		self.assertAlmostEqual(flt(inv.grand_total), flt(inv.total))

	def test_lines_without_an_item_are_not_charged_labour(self):
		"""A charge billed as free text (e.g. an M&R total) books no contract hours."""
		inv = self._invoice([{"description": "M&R RO-2026-00001", "qty": 1, "rate": 900000}])
		self.assertEqual(flt(inv.total_manhour), 0)

	def test_customer_without_contract_gets_no_hours(self):
		inv = self._invoice(
			[{"item_code": "Lift Off", "qty": 1, "rate": 250000}], customer=self.nocon
		)
		self.assertEqual(flt(inv.total_manhour), 0)

	def test_labour_can_be_switched_off_per_invoice(self):
		inv = self._invoice([{"item_code": "Lift Off", "qty": 1, "rate": 250000}], manhour=False)
		self.assertEqual(flt(inv.total_manhour), 0)

	# --- Hour is the editable multiplier --------------------------------------
	def test_editing_hour_reprices_labour_and_the_total(self):
		"""4 is only a default: change Hour and the charge (and grand total) follow."""
		inv = self._invoice([{"item_code": "Lift Off", "qty": 1, "rate": 250000}])
		price = flt(inv.total)
		inv.manhour_hour = 10
		inv.save(ignore_permissions=True)
		inv.reload()
		self.assertAlmostEqual(flt(inv.manhour_amount), LIFT_OFF_HOURS * 10)
		self.assertAlmostEqual(flt(inv.grand_total), price + LIFT_OFF_HOURS * 10)

	def test_labour_is_charged_once_however_often_it_is_saved(self):
		"""Re-saving must not stack a second charge row (or double the total)."""
		inv = self._invoice([{"item_code": "Lift Off", "qty": 1, "rate": 250000}])
		expected = flt(inv.grand_total)
		for _ in range(3):
			inv.save(ignore_permissions=True)
			inv.reload()
		self.assertEqual(len(self._charge_rows(inv)), 1)
		self.assertAlmostEqual(flt(inv.grand_total), expected)

	# --- tax lands on the labour too ------------------------------------------
	def test_tax_is_charged_on_price_plus_labour(self):
		"""PPN must see services AND labour: Total Price + Biaya Manhour -> tax -> Grand Total.

		The labour charge is a tax-table row, so a percentage left on "On Net Total" would
		tax the items only and undercharge the customer. It is repointed at the labour row.
		"""
		tmpl = frappe.db.get_value(
			"Sales Taxes and Charges Template", {"company": invoicing.get_default_company(), "is_default": 0}, "name"
		) or frappe.db.get_value("Sales Taxes and Charges Template", {}, "name")
		if not tmpl:
			self.skipTest("site has no Sales Taxes and Charges Template to exercise")
		rate = flt(frappe.db.get_value("Sales Taxes and Charges", {"parent": tmpl}, "rate"))
		inv = self._invoice(
			[{"item_code": "Lift Off", "qty": 1, "rate": 250000}], taxes_and_charges=tmpl
		)
		subtotal = flt(inv.total) + flt(inv.manhour_amount)
		self.assertAlmostEqual(flt(inv.manhour_amount), LIFT_OFF_HOURS * pricing.DEFAULT_MANHOUR_HOUR)
		# The labour row comes first so the percentage below it accumulates on top of it.
		self.assertEqual(self._charge_rows(inv)[0].idx, 1)
		percent = [t for t in inv.taxes if flt(t.rate)]
		self.assertTrue(percent, "the template must contribute a percentage row")
		self.assertEqual(percent[0].charge_type, "On Previous Row Total")
		tax = flt(inv.total_taxes_and_charges) - flt(inv.manhour_amount)
		self.assertAlmostEqual(tax, subtotal * rate / 100, places=2)
		self.assertAlmostEqual(flt(inv.grand_total), subtotal + tax, places=2)
