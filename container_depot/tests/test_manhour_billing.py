"""Labour (manhour) is billed ONCE, at invoicing — never folded into a service's rate.

Each invoice line carries its labour TARIFF per hour (``Sales Invoice Item.manhour``: off the
order, else the contract's ``Tariff Rate.manhour_rate``). The header sums them into Total
Manhour and — only when Tagih Manhour (``depot_bill_manhour``, off by default) is ticked —
meets that sum once with the hours worked (``manhour_hour``, "Total Jam", 4 by default):

    Total = Total Price + (Total Manhour x Total Jam)

Every part of that rule is asserted here: the rate resolver must NOT merge labour into a
service's price, and the invoice funnel every menu goes through must carry the tariff per
line, total it in the header, meet it with the hours, and fold that one charge into the
grand total.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, today

from container_depot import invoicing, pricing, pricing_model
from container_depot.tests.finance_fixture import require_finance
from container_depot.tests.test_api import ensure_test_customer
from container_depot.tests.test_container_booking import _cleanup_customer_world

# What one hour of labour costs this customer, per service (the contract's "Tarif Manhour").
LIFT_OFF_TARIFF = 60_000.0
CLEAN_TARIFF = 40_000.0
# Total Jam a new invoice starts with.
DEFAULT_JAM = 4


class TestManhourBilling(FrappeTestCase):
	CUSTOMER = "Manhour Billing Co"
	NOCON = "Manhour No-Contract Co"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		require_finance(cls)
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
				{"item": "Lift Off", "rate": 250000, "manhour_rate": LIFT_OFF_TARIFF},
				{"item": "Standard Clean", "rate": 100000, "manhour_rate": CLEAN_TARIFF},
				# A service the contract prices but charges no labour for.
				{"item": "Lift On", "rate": 200000, "manhour_rate": 0},
			],
		}).insert(ignore_permissions=True)
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
		for name in (cls.CUSTOMER, cls.NOCON):
			frappe.db.delete("Notification Log", {"subject": ["like", f"%{name}%"]})  # "Kontrak baru …"
		frappe.db.delete("Customer", {"name": ("in", [cls.customer, cls.nocon])})  # last
		frappe.db.commit()
		super().tearDownClass()

	def tearDown(self):
		# Every test raises drafts through the invoice funnel — drop them, rows included: the
		# numbers are reused once the series is reset, and a new invoice would inherit them.
		for si in frappe.get_all(
			"Sales Invoice", filters={"customer": ("in", [self.customer, self.nocon]), "docstatus": 0}, pluck="name"
		):
			for child in ("Sales Invoice Item", "Sales Taxes and Charges", "Payment Schedule", "Item Wise Tax Detail"):
				frappe.db.delete(child, {"parent": si, "parenttype": "Sales Invoice"})
			frappe.db.delete("Sales Invoice", {"name": si})
		frappe.db.commit()

	def _invoice(self, lines, customer=None, bill=True, **kw):
		"""A draft with Tagih Manhour ticked (``bill``), the way the user switches labour on."""
		si = invoicing.create_draft_sales_invoice(customer or self.customer, lines, currency="IDR", **kw)
		self.assertTrue(si, "the site must be invoice-ready for this test")
		inv = frappe.get_doc("Sales Invoice", si)
		if bill:
			inv.depot_bill_manhour = 1
			inv.save(ignore_permissions=True)
			inv.reload()
		return inv

	def _charge_rows(self, inv):
		"""The labour charge rows (there must never be more than one)."""
		return [t for t in (inv.taxes or []) if (t.description or "").strip() == invoicing.MANHOUR_CHARGE]

	def _delete_charge_row(self, inv):
		"""Do what the grid's Delete does: drop the row and save."""
		inv.set("taxes", [t for t in inv.taxes if t not in self._charge_rows(inv)])
		inv.save(ignore_permissions=True)
		inv.reload()
		return inv

	def _tax_template(self):
		company = invoicing.get_default_company()
		return frappe.db.get_value(
			"Sales Taxes and Charges Template", {"company": company, "is_default": 0}, "name"
		) or frappe.db.get_value("Sales Taxes and Charges Template", {}, "name")

	# --- the rate card: price and labour tariff side by side --------------------
	def test_the_contract_carries_the_labour_tariff_next_to_the_rate(self):
		self.assertEqual(pricing_model.active_contract(self.customer), self.contract.name)
		self.assertAlmostEqual(pricing.manhour_for("Lift Off", self.contract.name), LIFT_OFF_TARIFF)
		self.assertAlmostEqual(pricing_model.resolve_price("Lift Off", self.contract.name), 250000)

	def test_rate_never_includes_labour(self):
		"""The tariff resolves to the agreed rate alone — labour is not folded in."""
		for item, rate in (("Lift Off", 250000), ("Standard Clean", 100000)):
			self.assertAlmostEqual(pricing_model.resolve_price(item, self.contract.name), rate)

	# --- the invoice carries the tariff per line and totals it once ------------
	def test_labour_is_not_billed_until_tagih_manhour_is_ticked(self):
		inv = self._invoice([{"item_code": "Lift Off", "qty": 1, "rate": 250000}], bill=False)
		self.assertFalse(inv.depot_bill_manhour, "off by default")
		self.assertAlmostEqual(flt(inv.total_manhour), LIFT_OFF_TARIFF, msg="the tariffs still show")
		self.assertEqual(flt(inv.manhour_amount), 0)
		self.assertEqual(self._charge_rows(inv), [])
		self.assertAlmostEqual(flt(inv.grand_total), flt(inv.total))

	def test_each_line_carries_its_contract_tariff(self):
		inv = self._invoice([
			{"item_code": "Lift Off", "qty": 1, "rate": 250000},
			{"item_code": "Standard Clean", "qty": 1, "rate": 100000},
		])
		by_item = {r.item_code: r for r in inv.items}
		self.assertAlmostEqual(flt(by_item["Lift Off"].manhour), LIFT_OFF_TARIFF)
		self.assertAlmostEqual(flt(by_item["Standard Clean"].manhour), CLEAN_TARIFF)

	def test_an_order_line_brings_its_own_tariff(self):
		"""What the order quoted wins over the contract today — 0 included."""
		inv = self._invoice([
			{"item_code": "Lift Off", "qty": 1, "rate": 250000, "manhour": 5000},
			{"item_code": "Standard Clean", "qty": 1, "rate": 100000, "manhour": 0},
		])
		self.assertEqual(sorted(flt(r.manhour) for r in inv.items), [0, 5000])
		self.assertAlmostEqual(flt(inv.total_manhour), 5000)

	def test_manhour_is_not_priced_into_the_line(self):
		"""The tariff sits beside the price — the line's own amount is qty × rate, nothing more,
		and qty does not multiply the tariff either."""
		inv = self._invoice([{"item_code": "Lift Off", "qty": 2, "rate": 250000}])
		self.assertAlmostEqual(flt(inv.items[0].amount), 500000)
		self.assertAlmostEqual(flt(inv.total), 500000, msg="Total Price excludes labour")
		self.assertAlmostEqual(flt(inv.total_manhour), LIFT_OFF_TARIFF, msg="qty must not inflate it")

	def test_total_is_price_plus_tariffs_times_hours(self):
		inv = self._invoice([
			{"item_code": "Lift Off", "qty": 1, "rate": 250000},
			{"item_code": "Standard Clean", "qty": 1, "rate": 100000},
		])
		tariffs = LIFT_OFF_TARIFF + CLEAN_TARIFF
		self.assertAlmostEqual(flt(inv.total_manhour), tariffs)
		self.assertAlmostEqual(flt(inv.manhour_hour), DEFAULT_JAM, msg="Total Jam starts at 4")
		self.assertAlmostEqual(flt(inv.manhour_amount), tariffs * DEFAULT_JAM)
		self.assertAlmostEqual(flt(inv.grand_total), flt(inv.total) + tariffs * DEFAULT_JAM)

	def test_a_foreign_line_tariff_is_converted_through_its_kurs(self):
		inv = self._invoice(
			[{"item_code": "Lift On", "qty": 1, "rate": 1, "currency": "USD", "manhour": 10}],
			kurs={"USD": 16000},
		)
		self.assertAlmostEqual(flt(inv.items[0].manhour), 10, msg="the line keeps its own currency")
		self.assertAlmostEqual(flt(inv.total_manhour), 160000, msg="the header is in IDR")
		self.assertAlmostEqual(flt(inv.manhour_amount), 160000 * DEFAULT_JAM)

	def test_the_contract_tariff_follows_the_line_currency(self):
		"""The rate card's IDR tariff on a USD line is converted, not copied as 60 000 USD."""
		inv = self._invoice(
			[{"item_code": "Lift Off", "qty": 1, "rate": 10, "currency": "USD"}], kurs={"USD": 16000}
		)
		self.assertAlmostEqual(flt(inv.items[0].manhour), LIFT_OFF_TARIFF / 16000)
		self.assertAlmostEqual(flt(inv.total_manhour), LIFT_OFF_TARIFF, msg="back in IDR on the header")

	def test_services_without_a_tariff_add_no_labour(self):
		inv = self._invoice([{"item_code": "Lift On", "qty": 2, "rate": 200000}])
		self.assertEqual(flt(inv.total_manhour), 0)
		self.assertEqual(self._charge_rows(inv), [], "no tariff -> no labour charge at all")
		self.assertAlmostEqual(flt(inv.grand_total), flt(inv.total))

	def test_lines_without_an_item_are_not_charged_labour(self):
		"""A charge billed as free text (e.g. an M&R total) has no contract tariff."""
		inv = self._invoice([{"description": "M&R RO-2026-00001", "qty": 1, "rate": 900000}])
		self.assertEqual(flt(inv.total_manhour), 0)

	def test_customer_without_contract_gets_no_labour(self):
		inv = self._invoice(
			[{"item_code": "Lift Off", "qty": 1, "rate": 250000}], customer=self.nocon
		)
		self.assertEqual(flt(inv.total_manhour), 0)

	def test_labour_can_be_switched_off_per_invoice(self):
		inv = self._invoice([{"item_code": "Lift Off", "qty": 1, "rate": 250000}], manhour=False)
		self.assertEqual(flt(inv.total_manhour), 0)

	# --- Total Jam is the editable multiplier ----------------------------------
	def test_editing_the_hours_reprices_labour_and_the_total(self):
		inv = self._invoice([{"item_code": "Lift Off", "qty": 1, "rate": 250000}])
		price = flt(inv.total)
		inv.manhour_hour = 10
		inv.save(ignore_permissions=True)
		inv.reload()
		self.assertAlmostEqual(flt(inv.manhour_amount), LIFT_OFF_TARIFF * 10)
		self.assertAlmostEqual(flt(inv.grand_total), price + LIFT_OFF_TARIFF * 10)

	def test_labour_is_charged_once_however_often_it_is_saved(self):
		"""Re-saving must not stack a second charge row (or double the total)."""
		inv = self._invoice([{"item_code": "Lift Off", "qty": 1, "rate": 250000}])
		expected = flt(inv.grand_total)
		for _ in range(3):
			inv.save(ignore_permissions=True)
			inv.reload()
		self.assertEqual(len(self._charge_rows(inv)), 1)
		self.assertAlmostEqual(flt(inv.grand_total), expected)

	# --- the charge can be taken off an invoice -------------------------------
	def test_deleting_the_charge_row_sticks(self):
		"""Delete must delete. The row is derived, so it would otherwise be rebuilt on the
		next save and the user would watch their deletion undo itself."""
		inv = self._invoice([{"item_code": "Lift Off", "qty": 1, "rate": 250000}])
		price = flt(inv.total)
		self._delete_charge_row(inv)
		self.assertEqual(self._charge_rows(inv), [])
		# Answered by switching Tagih Manhour off — the tariffs and hours are still on record.
		self.assertFalse(inv.depot_bill_manhour)
		self.assertEqual(flt(inv.manhour_hour), DEFAULT_JAM)
		self.assertAlmostEqual(flt(inv.total_manhour), LIFT_OFF_TARIFF)
		self.assertEqual(flt(inv.manhour_amount), 0)
		self.assertAlmostEqual(flt(inv.grand_total), price)

		for _ in range(2):
			inv.save(ignore_permissions=True)
			inv.reload()
		self.assertEqual(self._charge_rows(inv), [])
		self.assertAlmostEqual(flt(inv.grand_total), price)

	def test_labour_returns_when_tagih_manhour_is_ticked_again(self):
		"""Deleting the row is not a one-way door — ticking the box switches it back on."""
		inv = self._delete_charge_row(
			self._invoice([{"item_code": "Lift Off", "qty": 1, "rate": 250000}])
		)
		inv.depot_bill_manhour = 1
		inv.manhour_hour = 10
		inv.save(ignore_permissions=True)
		inv.reload()
		self.assertEqual(len(self._charge_rows(inv)), 1)
		self.assertAlmostEqual(flt(inv.manhour_amount), LIFT_OFF_TARIFF * 10)

	def test_zero_hours_is_honoured(self):
		"""Total Jam 0 means "bill no labour here" and must survive the save."""
		inv = self._invoice([{"item_code": "Lift Off", "qty": 1, "rate": 250000}])
		inv.manhour_hour = 0
		inv.save(ignore_permissions=True)
		inv.reload()
		self.assertEqual(flt(inv.manhour_hour), 0)
		self.assertEqual(self._charge_rows(inv), [])
		self.assertAlmostEqual(flt(inv.grand_total), flt(inv.total))

	def test_deleting_the_charge_leaves_the_percentage_charging_on_net_total(self):
		"""Removing the labour row must put the tax below it back where it was.

		The charge is inserted first and the percentage repointed at it. If that reference
		is left dangling when the row goes, ERPNext does not complain — it bills the
		percentage as **0**, so the invoice would silently lose its whole PPN.
		"""
		rate = 11
		inv = self._delete_charge_row(
			self._invoice([{"item_code": "Lift Off", "qty": 1, "rate": 250000}], tax_input="11%")
		)
		percent = [t for t in inv.taxes if flt(t.rate)]
		self.assertTrue(percent, "the percentage row must survive — only labour was deleted")
		self.assertEqual(percent[0].charge_type, "On Net Total")
		self.assertEqual(percent[0].idx, 1, "the gap left by the labour row must be closed")
		self.assertAlmostEqual(flt(inv.total_taxes_and_charges), flt(inv.total) * rate / 100, places=2)

	# --- tax lands on the labour too ------------------------------------------
	def test_tax_is_charged_on_price_plus_labour(self):
		"""PPN must see services AND labour: Total Price + Biaya Manhour -> tax -> Grand Total."""
		rate = 11
		inv = self._invoice(
			[{"item_code": "Lift Off", "qty": 1, "rate": 250000}], tax_input="11%"
		)
		subtotal = flt(inv.total) + flt(inv.manhour_amount)
		self.assertAlmostEqual(flt(inv.manhour_amount), LIFT_OFF_TARIFF * DEFAULT_JAM)
		# The labour row comes first so the percentage below it accumulates on top of it.
		self.assertEqual(self._charge_rows(inv)[0].idx, 1)
		percent = [t for t in inv.taxes if flt(t.rate)]
		self.assertTrue(percent, "the PPN box must contribute a percentage row")
		self.assertEqual(percent[0].charge_type, "On Previous Row Total")
		tax = flt(inv.total_taxes_and_charges) - flt(inv.manhour_amount)
		self.assertAlmostEqual(tax, subtotal * rate / 100, places=2)
		self.assertAlmostEqual(flt(inv.grand_total), subtotal + tax, places=2)
