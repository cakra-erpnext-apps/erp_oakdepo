"""Tests for the Depot Contract / Tariff Rate doctypes."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from container_depot.container_depot.doctype.depot_contract.depot_contract import (
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
	"""Remove the test customer's contracts and their tariff lines — an Active one left
	behind silently prices every later test, and these commit."""
	customer = ensure_test_customer(CUSTOMER_NAME)
	names = frappe.get_all("Depot Contract", filters={"customer": customer}, pluck="name")
	if names:
		frappe.db.delete("Tariff Rate", {"parent": ["in", names]})
		frappe.db.delete("Depot Contract", {"name": ["in", names]})
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

	# --- the contract IS the rate card -----------------------------------
	def test_the_tariff_lines_are_the_rate_card(self):
		"""Nothing is published anywhere: the resolver reads these rows.

		This used to assert a Price List named after the contract, carrying an Item Price per
		line. That mirror was deleted 2026-09-17 — it could be edited in place and was then
		silently overwritten on the contract's next save."""
		from container_depot import pricing_model

		c = _make_contract(status="Active", tariff_lines=[{"item": "Lift Off", "rate": 250000}])
		c.insert(ignore_permissions=True)
		customer = ensure_test_customer(CUSTOMER_NAME)
		self.assertEqual(pricing_model.active_contract(customer), c.name)
		self.assertEqual(pricing_model.resolve_price("Lift Off", c.name), 250000)

	def test_the_contract_leaves_the_customer_master_alone(self):
		"""It used to write its published list onto ``Customer.default_price_list`` and guard
		that field against hand edits. Both are gone: ERPNext's own field takes no part in
		pricing here any more, so the app neither writes it nor polices it.

		Asserted as "unchanged" rather than "empty": the field is ERPNext's, and a site whose
		Selling Settings default one is free to fill it in."""
		name = ensure_test_customer(CUSTOMER_NAME)
		before = frappe.db.get_value("Customer", name, "default_price_list")
		c = _make_contract(status="Active", tariff_lines=[{"item": "Lift Off", "rate": 250000}])
		c.insert(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Customer", name, "default_price_list"), before)
		# ...and saving the Customer is not refused for touching it — the guard is gone too.
		customer = frappe.get_doc("Customer", name)
		customer.default_price_list = "Standard Selling"
		customer.save(ignore_permissions=True)
		self.addCleanup(
			frappe.db.set_value, "Customer", name, "default_price_list", before, update_modified=False
		)

	def test_editing_a_rate_takes_effect_in_place(self):
		from container_depot import pricing_model

		c = _make_contract(status="Active", tariff_lines=[{"item": "Lift Off", "rate": 250000}])
		c.insert(ignore_permissions=True)
		c.tariff_lines[0].rate = 300000
		c.save(ignore_permissions=True)
		self.assertEqual(pricing_model.resolve_price("Lift Off", c.name), 300000)

	def test_void_takes_the_rate_card_out_of_service(self):
		from container_depot import pricing_model

		c = _make_contract(status="Active", tariff_lines=[{"item": "Lift Off", "rate": 250000}])
		c.insert(ignore_permissions=True)
		customer = ensure_test_customer(CUSTOMER_NAME)
		self.assertEqual(pricing_model.active_contract(customer), c.name)
		c.status = "Void"
		c.save(ignore_permissions=True)
		self.assertIsNone(pricing_model.active_contract(customer))

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
		# Rate / Manhour format in the contract currency, and the resolver reads it off the
		# line — so one contract can never quote two currencies.
		c = _make_contract(currency="USD", status="Draft", tariff_lines=[{"item": "Lift Off", "rate": 36}])
		c.insert(ignore_permissions=True)
		self.assertEqual(c.tariff_lines[0].currency, "USD")

	def test_base_contract_lines_returns_priced_items(self):
		from container_depot.container_depot.doctype.depot_contract.depot_contract import (
			base_contract_lines,
		)

		src = _make_contract(
			status="Draft", tariff_lines=[{"item": "Lift Off", "uom": "Nos", "rate": 36.0}]
		)
		src.insert(ignore_permissions=True)
		lines = base_contract_lines(src.name)
		self.assertTrue(any(d["item"] == "Lift Off" and d["rate"] == 36.0 for d in lines))
		self.assertTrue(all({"item", "uom", "rate", "manhour_rate"} <= set(d.keys()) for d in lines))

	def test_base_contract_query_offers_any_contract_that_has_lines(self):
		"""Cribbing is copying numbers, so status is not the question — an Expired contract
		is often exactly the one being renewed. Empty contracts are hidden (nothing to copy)
		and so is the contract doing the cribbing (it cannot seed from itself)."""
		from container_depot.container_depot.doctype.depot_contract.depot_contract import (
			base_contract_query,
		)

		crib = _make_contract(
			status="Expired", tariff_lines=[{"item": "Lift Off", "rate": 111}]
		)
		crib.insert(ignore_permissions=True)
		empty = _make_contract(status="Draft", tariff_lines=[])
		empty.insert(ignore_permissions=True)
		me = _make_contract(status="Draft", tariff_lines=[{"item": "Lift Off", "rate": 1}])
		me.insert(ignore_permissions=True)

		names = [r[0] for r in base_contract_query("Depot Contract", "", "name", 0, 100, {"name": me.name})]
		self.assertIn(crib.name, names)      # has lines, status irrelevant
		self.assertNotIn(empty.name, names)  # nothing to copy from
		self.assertNotIn(me.name, names)     # never itself

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

	def test_set_status_walks_the_flow(self):
		from container_depot.container_depot.doctype.depot_contract.depot_contract import set_status

		c = _make_contract(status="Draft", tariff_lines=[{"item": "Lift Off", "rate": 250000}])
		c.insert(ignore_permissions=True)
		# Draft submits straight to Active — the Negotiation step was removed.
		set_status(c.name, "Active")
		self.assertEqual(frappe.db.get_value("Depot Contract", c.name, "status"), "Active")
		# Active then ends at Expired (the "Invalid" button uses Void instead).
		set_status(c.name, "Expired")
		self.assertEqual(frappe.db.get_value("Depot Contract", c.name, "status"), "Expired")

	# --- amendment (the Duplicate / edit replacement) ---------------------
	def _active_contract(self, **overrides):
		c = _make_contract(
			status="Active", tariff_lines=[{"item": "Lift Off", "rate": 250000}], **overrides
		)
		c.insert(ignore_permissions=True)
		return c

	def test_amendment_draft_leaves_source_running(self):
		src = self._active_contract()
		amd = _make_contract(
			status="Draft",
			amends_contract=src.name,
			tariff_lines=[{"item": "Lift Off", "rate": 275000}],
		)
		amd.insert(ignore_permissions=True)
		# Nothing changes until the amendment is submitted.
		self.assertEqual(frappe.db.get_value("Depot Contract", src.name, "status"), "Active")

	def test_submitting_amendment_supersedes_source(self):
		from container_depot.container_depot.doctype.depot_contract.depot_contract import set_status

		src = self._active_contract()
		amd = _make_contract(
			status="Draft",
			amends_contract=src.name,
			tariff_lines=[{"item": "Lift Off", "rate": 275000}],
		)
		amd.insert(ignore_permissions=True)
		set_status(amd.name, "Active")

		from container_depot import pricing_model

		self.assertEqual(frappe.db.get_value("Depot Contract", src.name, "status"), "Amended")
		# The amendment is now the customer's live contract, and its rate is what prices.
		customer = ensure_test_customer(CUSTOMER_NAME)
		hit = get_active_contract(customer)
		self.assertEqual(hit.name, amd.name)
		self.assertEqual(pricing_model.active_contract(customer), amd.name)
		self.assertEqual(pricing_model.resolve_price("Lift Off", amd.name), 275000)

	def test_amendment_must_keep_customer(self):
		src = self._active_contract()
		other = "Depot Contract Amend Other Co"
		try:
			amd = _make_contract(
				status="Draft",
				customer=ensure_test_customer(other),
				amends_contract=src.name,
				tariff_lines=[{"item": "Lift Off", "rate": 275000}],
			)
			with self.assertRaises(frappe.ValidationError):
				amd.insert(ignore_permissions=True)
		finally:
			frappe.db.delete("Depot Contract", {"customer": other})
			frappe.db.delete("Customer", {"name": other})
			frappe.db.commit()

	def test_already_amended_contract_cannot_be_amended_again(self):
		from container_depot.container_depot.doctype.depot_contract.depot_contract import set_status

		src = self._active_contract()
		first = _make_contract(
			status="Draft", amends_contract=src.name,
			tariff_lines=[{"item": "Lift Off", "rate": 275000}],
		)
		first.insert(ignore_permissions=True)
		set_status(first.name, "Active")
		# src is Amended now — the next amendment must start from `first`.
		second = _make_contract(
			status="Draft", amends_contract=src.name,
			tariff_lines=[{"item": "Lift Off", "rate": 280000}],
		)
		with self.assertRaises(frappe.ValidationError):
			second.insert(ignore_permissions=True)

	def test_only_one_active_contract_per_customer(self):
		from container_depot.container_depot.doctype.depot_contract.depot_contract import set_status

		src = self._active_contract()
		# A fresh (non-amendment) contract cannot go live beside src...
		rival = _make_contract(status="Draft", tariff_lines=[{"item": "Lift Off", "rate": 1}])
		rival.insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			set_status(rival.name, "Active")
		# ...nor can a second amendment of src once the first one has replaced it.
		a1, a2 = (
			_make_contract(status="Draft", amends_contract=src.name,
				tariff_lines=[{"item": "Lift Off", "rate": r}]).insert(ignore_permissions=True)
			for r in (2, 3)
		)
		set_status(a1.name, "Active")
		with self.assertRaises(frappe.ValidationError):
			set_status(a2.name, "Active")
		active = frappe.get_all(
			"Depot Contract", {"customer": src.customer, "status": "Active"}, pluck="name"
		)
		self.assertEqual(active, [a1.name])

	# --- delete guard (Duplicate/Delete are off in the form) --------------
	def test_draft_is_deletable_but_active_is_not(self):
		draft = _make_contract(status="Draft")
		draft.insert(ignore_permissions=True)
		frappe.delete_doc("Depot Contract", draft.name, ignore_permissions=True)
		self.assertFalse(frappe.db.exists("Depot Contract", draft.name))

		live = self._active_contract()
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Depot Contract", live.name, ignore_permissions=True)


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
