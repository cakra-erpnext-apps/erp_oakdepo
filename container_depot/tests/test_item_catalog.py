"""Katalog item bersama (container_depot.item_catalog) + fallback mata uangnya.

Yang dikunci di sini adalah perubahan 2026-09-07: picker item TIDAK lagi dibatasi kontrak
customer (dan menu item yang dulu menyaringnya sudah dihapus), sebagai gantinya item yang
paling sering dipakai naik ke halaman pertama. Ditambah satu hal yang menahan akibat buruknya — baris tanpa Item
Price tetap punya mata uang (mengikuti customer, jatuh ke IDR), bukan None.

Semua fixture berawalan ``ZZ-CAT-TEST`` dan dihapus di tearDown.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot import pricing_model
from container_depot.container_depot import item_catalog

_PREFIX = "ZZ-CAT-TEST"
_CUST = "ZZ Cat Test Customer"
_PRINCIPAL = "ZZ Cat Test Principal"
_OTHER_CUST = "ZZ Cat Other Customer"


class TestItemCatalog(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._orders = []
		self._containers = []
		group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"
		for suffix in ("A", "B", "C"):
			self._item(f"{_PREFIX}-{suffix}", group)
		self._customer(_PRINCIPAL)
		item_catalog.clear_popular_cache()

	def tearDown(self):
		for name in self._orders:
			frappe.db.delete("Repair Used Item", {"parent": name})
			frappe.db.delete("Repair Order", {"name": name})
		for name in self._containers:
			frappe.db.delete("Container", {"name": name})
		for suffix in ("A", "B", "C"):
			frappe.db.delete("Item", {"name": f"{_PREFIX}-{suffix}"})
		for name in frappe.get_all(
			"Depot Contract", filters={"customer": ("in", [_CUST, _OTHER_CUST])}, pluck="name"
		):
			frappe.db.delete("Tariff Rate", {"parent": name})
			frappe.db.delete("Depot Contract", {"name": name})
		frappe.db.delete("Customer", {"name": ("in", [_CUST, _OTHER_CUST, _PRINCIPAL])})
		item_catalog.clear_popular_cache()
		frappe.db.commit()
		super().tearDown()

	# --- fixtures ---------------------------------------------------------------
	def _item(self, code, group):
		if frappe.db.exists("Item", code):
			return code
		frappe.get_doc({
			"doctype": "Item", "item_code": code, "item_name": code, "item_group": group,
			"stock_uom": "Nos", "is_stock_item": 0, "is_sales_item": 1,
		}).insert(ignore_permissions=True)
		return code

	def _customer(self, name, **extra):
		if frappe.db.exists("Customer", name):
			return name
		frappe.get_doc({
			"doctype": "Customer", "customer_name": name, "customer_type": "Company",
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
			or "All Customer Groups",
			"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name")
			or "All Territories",
			**extra,
		}).insert(ignore_permissions=True)
		return name

	def _repair_order_using(self, item_code):
		container = frappe.get_doc({
			"doctype": "Container", "container_no": f"{_PREFIX}{len(self._containers)}",
			"container_type": "ISO Tank", "status": "In_Depot", "principal": _PRINCIPAL,
		}).insert(ignore_permissions=True).name
		self._containers.append(container)
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": container, "status": "Draft",
			"used_items": [{"item": item_code, "qty": 1}],
		}).insert(ignore_permissions=True).name
		self._orders.append(ro)
		return ro

	# --- katalog terbuka ---------------------------------------------------------
	def test_search_offers_items_no_contract_prices(self):
		"""Tidak satu pun item fixture ada di kontrak mana pun — semuanya tetap ditawarkan."""
		codes = {r["item_code"] for r in item_catalog.search_items(txt=_PREFIX, page_length=50)}
		self.assertEqual(codes, {f"{_PREFIX}-A", f"{_PREFIX}-B", f"{_PREFIX}-C"})

	def test_disabled_item_stays_hidden(self):
		"""Membuka katalog bukan berarti item mati ikut muncul."""
		frappe.db.set_value("Item", f"{_PREFIX}-C", "disabled", 1)
		try:
			codes = {r["item_code"] for r in item_catalog.search_items(txt=_PREFIX, page_length=50)}
			self.assertNotIn(f"{_PREFIX}-C", codes)
		finally:
			frappe.db.set_value("Item", f"{_PREFIX}-C", "disabled", 0)

	# --- urutan "sering dipakai" -------------------------------------------------
	def test_most_used_item_comes_first(self):
		"""B dipakai di dua M&R, A dan C tidak pernah — B harus naik ke depan meski namanya
		berada di tengah secara alfabetis."""
		self._repair_order_using(f"{_PREFIX}-B")
		self._repair_order_using(f"{_PREFIX}-B")
		item_catalog.clear_popular_cache()
		self.assertIn(f"{_PREFIX}-B", item_catalog.popular_items("mr"))
		rows = item_catalog.search_items(txt=_PREFIX, context="mr", page_length=50)
		self.assertEqual(rows[0]["item_code"], f"{_PREFIX}-B")
		# sisanya tetap alfabetis
		self.assertEqual(
			[r["item_code"] for r in rows[1:]], [f"{_PREFIX}-A", f"{_PREFIX}-C"]
		)

	def test_usage_of_one_flow_does_not_reorder_another(self):
		"""Pemakaian di M&R tidak boleh mengangkat item di picker cleaning."""
		self._repair_order_using(f"{_PREFIX}-B")
		item_catalog.clear_popular_cache()
		self.assertNotIn(f"{_PREFIX}-B", item_catalog.popular_items("cleaning"))

	def test_paging_stays_honest(self):
		"""Potongan halaman terjadi SESUDAH pengurutan, jadi halaman pertama tidak pernah
		kehilangan item yang seharusnya di depan."""
		self._repair_order_using(f"{_PREFIX}-B")
		item_catalog.clear_popular_cache()
		first = item_catalog.search_items(txt=_PREFIX, context="mr", page_length=1)
		self.assertEqual([r["item_code"] for r in first], [f"{_PREFIX}-B"])
		second = item_catalog.search_items(txt=_PREFIX, context="mr", start=1, page_length=1)
		self.assertEqual([r["item_code"] for r in second], [f"{_PREFIX}-A"])

	# --- mata uang baris yang kontraknya tidak menghargai -----------------------
	def test_currency_follows_own_contract_then_customer_then_company(self):
		"""Urutan mata uang baris di luar rate card, dari yang paling mengikat.

		Kontrak MILIK customer menang duluan — harganya memang tertulis dalam mata uang itu.
		Kontrak milik pihak LAIN tidak: dulu pertanyaannya price list, dan price list apa pun
		menang di langkah pertama, sehingga katalog site menutupi ``Customer.default_currency``
		dan customer USD tanpa kontrak selamanya jatuh ke IDR.
		"""
		from frappe.utils import add_days, today

		self._customer(_CUST, default_currency="SGD")
		self._customer(_OTHER_CUST)
		foreign = frappe.get_doc({
			"doctype": "Depot Contract", "customer": _OTHER_CUST, "currency": "USD",
			"status": "Draft", "payment_type": "Cash",
			"valid_from": today(), "valid_to": add_days(today(), 365),
		}).insert(ignore_permissions=True).name

		# Kontrak orang lain: mata uang tagihan customer yang dipakai, bukan currency kontrak itu.
		self.assertEqual(pricing_model.currency_for_customer(_CUST, foreign), "SGD")
		self.assertEqual(pricing_model.currency_for_customer(_CUST), "SGD")

		# Kontraknya sendiri: kontraknya yang menang.
		frappe.db.set_value("Depot Contract", foreign, "customer", _CUST, update_modified=False)
		self.assertEqual(pricing_model.currency_for_customer(_CUST, foreign), "USD")

		self.assertEqual(
			pricing_model.currency_for_customer(None), pricing_model.company_currency()
		)

	def test_currency_is_never_empty(self):
		self.assertTrue(pricing_model.currency_for_customer("No Such Customer", "No Such Contract"))
