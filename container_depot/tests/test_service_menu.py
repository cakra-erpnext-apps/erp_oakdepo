"""Depot Service Menu — a dynamic, group-based filter over the Item catalog.

Covers the resolver (container_depot.service_menu): group membership incl. descendants,
the per-item extras escape-hatch, the safe fallback when a menu is missing/empty, and
that the M&R picker (container_depot.mr.mr_item_search) honours the seeded "Maintenance"
menu. Also covers the contract paste-import (container_depot.doctype.depot_contract:
import_tariff_lines) — parsing, base-price-list defaults, unknown items, replace, and
the editable-status guard.

All fixtures use the ``ZZ-MENU-TEST`` / ``ZZ Menu Test`` prefix and are removed in
tearDown so the test leaves nothing behind.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot import seed_dev
from container_depot.container_depot import mr, service_menu
from container_depot.container_depot.doctype.depot_contract import depot_contract
from container_depot.container_depot.doctype.periodic_test_order import periodic_test_order
from container_depot.container_depot.doctype.survey_order import survey_order

_PREFIX = "ZZ-MENU-TEST"
_MENU = "ZZ Menu Test"
_GROUP = "ZZ Menu Test Group"
_CHILD_GROUP = "ZZ Menu Test Child"
_PL = "ZZ Menu Test PL"
_CUST = "ZZ Menu Test Customer"
# The groups the M&R "Maintenance" menu maps / excludes are resolved from the LIVE menu in
# setUp, never hardcoded: the Item Group taxonomy has been replaced once already (the seeded
# placeholders gave way to the customer's rate-card groups) and the hardcoded names silently
# took this whole module red. Reading them off the menu makes the fixture taxonomy-agnostic.


class TestDepotServiceMenu(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._contracts = []
		# A group the Maintenance menu contains, and one it does not — whatever this site calls
		# them. Skips rather than fails when the menus were never seeded.
		self._mr_group = frappe.db.get_value(
			"Depot Service Menu Group", {"parent": mr.MR_MENU}, "item_group"
		)
		self._out_group = frappe.db.get_value(
			"Depot Service Menu Group", {"parent": "Cleaning"}, "item_group"
		)
		if not (self._mr_group and self._out_group):
			self.skipTest("Depot Service Menus not seeded in this site")
		# Item groups: a leaf G with a child GC (for the descendant test).
		self._ensure_group(_GROUP, parent="All Item Groups", is_group=1)
		self._ensure_group(_CHILD_GROUP, parent=_GROUP, is_group=0)
		# Items.
		self._ensure_item(f"{_PREFIX}-A", _GROUP)
		self._ensure_item(f"{_PREFIX}-B", _GROUP)
		self._ensure_item(f"{_PREFIX}-C", self._out_group)   # outsider, pulled in via extras
		self._ensure_item(f"{_PREFIX}-E", _CHILD_GROUP)   # in via descendant group
		self._ensure_item(f"{_PREFIX}-MR", self._mr_group)   # in the real Maintenance menu
		self._ensure_item(f"{_PREFIX}-CLEAN", self._out_group)  # excluded from Maintenance
		# The test menu: group G (+ descendants) plus C pinned as an extra.
		self._ensure_menu()
		# Selling price list + Item Prices for the import test.
		self._ensure_price_list()
		self._ensure_item_price(f"{_PREFIX}-A", 100.0, 0.0)
		self._ensure_item_price(f"{_PREFIX}-B", 200.0, 5.0)
		frappe.db.commit()

	def _safe(self, fn):
		try:
			fn()
		except Exception:
			frappe.db.rollback()

	def tearDown(self):
		# Raw delete: Depot Contract.on_trash refuses to delete anything past Draft
		# (contracts are Voided / Amended, never removed), and this fixture makes Void ones.
		self._safe(lambda: self._contracts and frappe.db.delete("Depot Contract", {"name": ("in", self._contracts)}))
		self._safe(lambda: frappe.db.delete("Item Price", {"price_list": _PL}))
		self._safe(lambda: frappe.db.exists("Price List", _PL) and frappe.delete_doc("Price List", _PL, force=True, ignore_permissions=True))
		self._safe(lambda: frappe.db.exists("Depot Service Menu", _MENU) and frappe.delete_doc("Depot Service Menu", _MENU, force=True, ignore_permissions=True))
		for code in (f"{_PREFIX}-A", f"{_PREFIX}-B", f"{_PREFIX}-C", f"{_PREFIX}-E", f"{_PREFIX}-MR",
		             f"{_PREFIX}-CLEAN", f"{_PREFIX}-SVY", f"{_PREFIX}-PT"):
			self._safe(lambda code=code: frappe.db.exists("Item", code) and frappe.delete_doc("Item", code, force=True, ignore_permissions=True))
		for g in (_CHILD_GROUP, _GROUP):
			self._safe(lambda g=g: frappe.db.exists("Item Group", g) and frappe.delete_doc("Item Group", g, force=True, ignore_permissions=True))
		self._safe(lambda: frappe.db.exists("Customer", _CUST) and frappe.delete_doc("Customer", _CUST, force=True, ignore_permissions=True))
		frappe.db.commit()
		super().tearDown()

	# --- fixtures -------------------------------------------------------------
	def _ensure_group(self, name, parent, is_group):
		if frappe.db.exists("Item Group", name):
			return
		frappe.get_doc({
			"doctype": "Item Group", "item_group_name": name,
			"parent_item_group": parent, "is_group": is_group,
		}).insert(ignore_permissions=True)

	def _ensure_item(self, code, group):
		if frappe.db.exists("Item", code):
			frappe.db.set_value("Item", code, "item_group", group)
			return
		frappe.get_doc({
			"doctype": "Item", "item_code": code, "item_name": code,
			"item_group": group, "stock_uom": "Nos",
			"is_stock_item": 0, "is_sales_item": 1,
		}).insert(ignore_permissions=True)

	def _ensure_menu(self):
		if frappe.db.exists("Depot Service Menu", _MENU):
			frappe.delete_doc("Depot Service Menu", _MENU, force=True, ignore_permissions=True)
		frappe.get_doc({
			"doctype": "Depot Service Menu", "menu_name": _MENU, "is_active": 1,
			"item_groups": [{"item_group": _GROUP}],
			"extra_items": [{"item": f"{_PREFIX}-C"}],
		}).insert(ignore_permissions=True)

	def _ensure_price_list(self):
		if frappe.db.exists("Price List", _PL):
			return
		frappe.get_doc({
			"doctype": "Price List", "price_list_name": _PL,
			"currency": "USD", "selling": 1, "enabled": 1,
		}).insert(ignore_permissions=True)

	def _ensure_item_price(self, item, rate, manhour_rate):
		if frappe.db.exists("Item Price", {"item_code": item, "price_list": _PL, "selling": 1}):
			return
		frappe.get_doc({
			"doctype": "Item Price", "item_code": item, "price_list": _PL,
			"selling": 1, "price_list_rate": rate, "manhour_rate": manhour_rate,
		}).insert(ignore_permissions=True)

	def _customer(self):
		if frappe.db.exists("Customer", _CUST):
			return _CUST
		cg = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		terr = frappe.db.get_value("Territory", {"is_group": 0}, "name")
		frappe.get_doc({
			"doctype": "Customer", "customer_name": _CUST,
			"customer_group": cg, "territory": terr,
		}).insert(ignore_permissions=True)
		return _CUST

	def _draft_contract(self, status="Draft"):
		doc = frappe.get_doc({
			"doctype": "Depot Contract", "customer": self._customer(),
			"status": status, "payment_type": "Cash",
			"currency": "USD", "base_price_list": _PL,
			"valid_from": "2026-01-01", "valid_to": "2030-12-31",
		}).insert(ignore_permissions=True)
		self._contracts.append(doc.name)
		return doc

	# --- resolver -------------------------------------------------------------
	def test_group_membership_and_descendants(self):
		codes = [f"{_PREFIX}-A", f"{_PREFIX}-B", f"{_PREFIX}-E", f"{_PREFIX}-CLEAN"]
		got = set(service_menu.filter_items_by_menu(codes, _MENU))
		# A, B in group G; E in the child group (descendant of G). CLEAN is outside.
		self.assertEqual(got, {f"{_PREFIX}-A", f"{_PREFIX}-B", f"{_PREFIX}-E"})

	def test_extra_items_pull_outsider_in(self):
		# C is in the outsider group, not G — included only because it's pinned as extra.
		got = set(service_menu.filter_items_by_menu([f"{_PREFIX}-C", f"{_PREFIX}-CLEAN"], _MENU))
		self.assertEqual(got, {f"{_PREFIX}-C"})

	def test_missing_or_empty_menu_is_passthrough(self):
		codes = [f"{_PREFIX}-A", f"{_PREFIX}-CLEAN"]
		self.assertFalse(service_menu.is_real_menu("No Such Menu"))
		self.assertEqual(service_menu.filter_items_by_menu(codes, "No Such Menu"), codes)

	def test_inactive_menu_does_not_filter(self):
		frappe.db.set_value("Depot Service Menu", _MENU, "is_active", 0)
		frappe.clear_cache(doctype="Depot Service Menu")
		try:
			self.assertFalse(service_menu.is_real_menu(_MENU))
			codes = [f"{_PREFIX}-A", f"{_PREFIX}-CLEAN"]
			self.assertEqual(service_menu.filter_items_by_menu(codes, _MENU), codes)
		finally:
			frappe.db.set_value("Depot Service Menu", _MENU, "is_active", 1)
			frappe.clear_cache(doctype="Depot Service Menu")

	def test_items_in_menu_lists_members(self):
		got = {r["item_code"] for r in service_menu.items_in_menu(_MENU, txt=_PREFIX)}
		self.assertIn(f"{_PREFIX}-A", got)
		self.assertIn(f"{_PREFIX}-E", got)
		self.assertIn(f"{_PREFIX}-C", got)
		self.assertNotIn(f"{_PREFIX}-CLEAN", got)

	# --- M&R picker honours the seeded Maintenance menu -----------------------
	def test_mr_item_search_scoped_to_maintenance(self):
		# With no repair_order the picker scans all items, then the menu filter applies.
		if not service_menu.is_real_menu(mr.MR_MENU):
			self.skipTest("Maintenance menu not seeded in this site")
		codes = {it["item_code"] for it in mr.mr_item_search(search=_PREFIX)["items"]}
		self.assertIn(f"{_PREFIX}-MR", codes)        # a Maintenance group → in
		self.assertNotIn(f"{_PREFIX}-CLEAN", codes)  # a Cleaning group → out
		self.assertNotIn(f"{_PREFIX}-A", codes)      # test group → out


	# --- every price-list picker declares its catalogue through a menu ---------
	def test_a_menu_exists_for_every_price_list_picker(self):
		"""One menu per flow whose item picker is scoped by a price list. A flow missing from
		here means its filter lives in code, where no operator can see or change it — which is
		how Survey Order and Periodic Test Order ended up offering the whole catalogue."""
		expected = {"Booking", "Cleaning", "Maintenance", "Survey", "Periodic Test"}
		self.assertEqual(set(service_menu.DEFAULT_MENUS), expected)
		# The dev seeder must cover exactly the same flows, or dev and production drift.
		self.assertEqual({name for name, _seq, _groups in seed_dev.MENUS}, expected)

	def test_production_ships_the_menus_without_a_group_mapping(self):
		"""Production seeds the menus EMPTY: there are no Item Prices yet, so a mapping here
		would be fiction — and the previous seeder proved it, pointing every fresh install at
		placeholder groups that had since been renamed. Re-seeding an existing site is a no-op:
		it must never re-assert groups an operator pruned."""
		before = {
			m: set(frappe.get_all("Depot Service Menu Group", filters={"parent": m}, pluck="item_group"))
			for m in service_menu.DEFAULT_MENUS
		}
		self.assertEqual(service_menu.seed_default_menus(), 0)
		after = {
			m: set(frappe.get_all("Depot Service Menu Group", filters={"parent": m}, pluck="item_group"))
			for m in service_menu.DEFAULT_MENUS
		}
		self.assertEqual(before, after)

	def test_dev_menu_mapping_matches_the_real_taxonomy(self):
		"""Every Item Group the DEV seeder maps must actually exist.

		This is the test the old seeder needed: it named the placeholder groups from
		patches.v0_11, those were replaced by the customer's rate-card groups, and nothing
		noticed — fresh installs quietly got menus that filtered nothing."""
		unknown = {
			(name, g)
			for name, _seq, groups in seed_dev.MENUS
			for g in groups
			if not frappe.db.exists("Item Group", g)
		}
		self.assertEqual(unknown, set(), f"dev seeder maps Item Groups that don't exist: {unknown}")
		# A booking prices the lift and nothing else.
		booking = next(groups for name, _seq, groups in seed_dev.MENUS if name == "Booking")
		self.assertEqual(booking, ["LOLO"])

	def test_survey_picker_is_scoped_to_the_survey_menu(self):
		"""A survey charge offers only what the "Survey" menu declares. The no-price-list case
		is the one that used to escape the filter entirely (it returned every sellable item)."""
		group = frappe.db.get_value("Depot Service Menu Group", {"parent": "Survey"}, "item_group")
		self._ensure_item(f"{_PREFIX}-SVY", group)
		codes = {
			r[0]
			for r in survey_order.item_price_query(
				doctype="Item", txt=_PREFIX, searchfield="name", start=0, page_len=20, filters={}
			)
		}
		self.assertIn(f"{_PREFIX}-SVY", codes)
		self.assertNotIn(f"{_PREFIX}-A", codes)      # test group — outside the menu
		self.assertNotIn(f"{_PREFIX}-MR", codes)     # a Maintenance item is not a survey charge

	def test_periodic_test_picker_is_scoped_to_its_menu(self):
		"""Same contract for Periodic Test Order, which had no query on the field at all."""
		group = frappe.db.get_value(
			"Depot Service Menu Group", {"parent": "Periodic Test"}, "item_group"
		)
		self._ensure_item(f"{_PREFIX}-PT", group)
		codes = {
			r[0]
			for r in periodic_test_order.used_item_query(
				doctype="Item", txt=_PREFIX, searchfield="name", start=0, page_len=20, filters={}
			)
		}
		self.assertIn(f"{_PREFIX}-PT", codes)
		self.assertNotIn(f"{_PREFIX}-SVY", codes)    # a survey fee is not a periodic test
		self.assertNotIn(f"{_PREFIX}-A", codes)

	# --- contract paste-import ------------------------------------------------
	def test_import_paste_with_defaults_and_unknown(self):
		c = self._draft_contract()
		text = f"{_PREFIX}-A\n{_PREFIX}-B\t250\nNOPE-UNKNOWN"
		res = depot_contract.import_tariff_lines(c.name, text)
		self.assertEqual(res["added"], 2)
		self.assertEqual(len(res["errors"]), 1)
		c.reload()
		rows = {r.item: r for r in c.tariff_lines}
		self.assertEqual(rows[f"{_PREFIX}-A"].rate, 100.0)   # default from base PL
		self.assertEqual(rows[f"{_PREFIX}-B"].rate, 250.0)   # pasted override
		self.assertEqual(rows[f"{_PREFIX}-A"].uom, "Nos")    # uom default from PL

	def test_import_match_by_item_name(self):
		c = self._draft_contract()
		# Items here have item_name == item_code; resolution by name still works.
		res = depot_contract.import_tariff_lines(c.name, f"{_PREFIX}-A")
		self.assertEqual(res["added"], 1)

	def test_import_replace_clears_first(self):
		c = self._draft_contract()
		depot_contract.import_tariff_lines(c.name, f"{_PREFIX}-A\n{_PREFIX}-B")
		res = depot_contract.import_tariff_lines(c.name, f"{_PREFIX}-A", replace=1)
		c.reload()
		self.assertEqual(len(c.tariff_lines), 1)
		self.assertEqual(res["total_lines"], 1)

	def test_import_blocked_when_not_editable(self):
		c = self._draft_contract(status="Void")
		with self.assertRaises(frappe.ValidationError):
			depot_contract.import_tariff_lines(c.name, f"{_PREFIX}-A")

	def test_base_price_list_lines_for_menu(self):
		# Add C (cleaning group) to the PL too, then filter by the test menu: A, B (group)
		# and C (extra) qualify; a cleaning-only item would not.
		self._ensure_item_price(f"{_PREFIX}-C", 50.0, 0.0)
		self._ensure_item_price(f"{_PREFIX}-CLEAN", 70.0, 0.0)
		got = {ln["item"] for ln in depot_contract.base_price_list_lines_for_menu(_PL, _MENU)}
		self.assertEqual(got, {f"{_PREFIX}-A", f"{_PREFIX}-B", f"{_PREFIX}-C"})
