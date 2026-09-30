"""OAK Invoice: the helpers its layout stands on, and that it renders at all.

Nothing is saved: the invoice is built in memory and printed from there.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot import consolidated_billing, invoicing
from container_depot.print_utils import invoice_groups, terbilang


def _invoice():
	company = invoicing.get_default_company()
	base = frappe.get_cached_value("Company", company, "default_currency")
	si = frappe.new_doc("Sales Invoice")
	si.update({"company": company, "customer": "Invoice Print Test Co", "currency": base, "conversion_rate": 1})
	for row in (
		{"item_name": "Materai tempel", "description": "Materai tempel", "qty": 1, "rate": 10000, "amount": 10000},
		{"item_name": "Storage", "description": "Storage TANK0000001 2026-09-01 s/d 2026-09-10 (10 hari)",
			"qty": 10, "rate": 50000, "amount": 500000, "depot_source": "Storage|TANK0000001"},
		{"item_name": "Lift Off", "description": "Booking GONE-1 · Lift Off", "qty": 1, "rate": 179220,
			"amount": 179220, "depot_currency": "USD", "depot_price": 10, "depot_kurs": 17922,
			"depot_source": "Container Booking|GONE-1"},
	):
		si.append("items", row)
	return si


class TestInvoicePrint(FrappeTestCase):
	def _lang(self, lang):
		old = frappe.local.lang
		frappe.local.lang = lang
		self.addCleanup(setattr, frappe.local, "lang", old)

	def test_terbilang(self):
		self._lang("id")
		self.assertEqual(
			terbilang(19624289),
			"Sembilan belas juta enam ratus dua puluh empat ribu dua ratus delapan puluh sembilan rupiah",
		)
		self.assertEqual(terbilang(35.5, "USD"), "Tiga puluh lima dolar Amerika Serikat lima puluh sen")
		self.assertEqual(terbilang(-1200), "Minus seribu dua ratus rupiah")

	def test_groups_follow_the_pick_list(self):
		out = invoice_groups(_invoice())
		# Storage before a line whose order is gone, hand-typed lines last.
		self.assertEqual([g["key"] for g in out["groups"]], ["Storage", ""])
		storage, rest = out["groups"]
		self.assertEqual(storage["rows"][0]["tank"], "TANK0000001")
		self.assertEqual(storage["total"], 500000)
		self.assertEqual([r["ref"] for r in rest["rows"]], ["", "GONE-1"])
		# An order line drops its "Booking X ·" prefix: the order has its own column.
		self.assertEqual([r["text"] for r in rest["rows"]], ["Materai tempel", "Lift Off"])
		self.assertEqual(out["kurs"], {"USD": [17922.0]})

	def test_renders_in_its_print_language(self):
		self._lang("id")
		html = frappe.get_print("Sales Invoice", None, "OAK Invoice", doc=_invoice())
		for text in ("INVOICE", "DRAFT – BELUM FINAL", "STORAGE", "LAIN-LAIN", "Terbilang", "Jatuh Tempo", "rupiah", "footer-html"):
			self.assertIn(text, html)
		self._lang("en")
		html = frappe.get_print("Sales Invoice", None, "OAK Invoice", doc=_invoice())
		for text in ("DRAFT – NOT FINAL", "OTHERS", "Amount in Words", "Due Date", "only."):
			self.assertIn(text, html)
		self.assertNotIn("Terbilang", html)
		# Our order number stays off the page: the customer reconciles by their own reference.
		self.assertNotIn("GONE-1", html)

	def test_order_lines_carry_the_reff_doc(self):
		si = _invoice()
		with patch.object(consolidated_billing, "cust_ref", lambda dt, name: f"REF-{name}"):
			consolidated_billing.stamp_reff_docs(si)
			self.assertEqual([r.depot_reff_doc for r in si.items], ["", "REF-TANK0000001", "REF-GONE-1"])
			# Submitted: what was billed stays.
			si.docstatus = 1
			si.items[2].depot_reff_doc = "OLD"
			consolidated_billing.stamp_reff_docs(si)
			self.assertEqual(si.items[2].depot_reff_doc, "OLD")
		self.assertEqual(invoice_groups(si)["groups"][1]["rows"][1]["cust_ref"], "OLD")
