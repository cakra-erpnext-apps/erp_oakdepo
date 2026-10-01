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

	def test_merge_same_lines_adds_up_the_qty(self):
		si = _invoice()
		si.append("items", {"item_name": "Materai tempel", "description": "Materai tempel", "qty": 2, "rate": 10000, "amount": 20000})
		si.append("items", {"item_name": "Materai tempel", "description": "Materai tempel", "qty": 1, "rate": 12000, "amount": 12000})
		self.assertEqual(len(invoice_groups(si)["groups"][1]["rows"]), 4)
		si.depot_print_merge = 1
		rows = invoice_groups(si)["groups"][1]["rows"]
		# Same description and price: one line, qty and amount added; another price stays apart.
		self.assertEqual([(r["text"], r["qty"], r["amount"]) for r in rows],
			[("Materai tempel", 3.0, 30000.0), ("Lift Off", 1.0, 179220.0), ("Materai tempel", 1.0, 12000.0)])
		self.assertEqual(invoice_groups(si)["groups"][1]["total"], 221220.0)
		# A printed Ref Cust. / No. Tank column joins the match: another ref stays its own line.
		si.items[0].depot_reff_doc, si.items[3].depot_reff_doc = "PO-1", "PO-2"
		self.assertEqual(len(invoice_groups(si)["groups"][1]["rows"]), 3)
		si.depot_print_cust_ref = 1
		self.assertEqual([r["cust_ref"] for r in invoice_groups(si)["groups"][1]["rows"]], ["PO-1", "", "PO-2", ""])

	def test_renders_in_its_print_language(self):
		self._lang("id")
		html = frappe.get_print("Sales Invoice", None, "OAK Invoice", doc=_invoice())
		for text in ("INVOICE", "DRAFT – BELUM FINAL", "STORAGE", "LAIN-LAIN", "Terbilang", "Jatuh Tempo", "rupiah", "footer-html"):
			self.assertIn(text, html)
		# Invoice Type and the kurs rows are off the page (user, 2026-10-01); a foreign line
		# still states its kurs on the line itself.
		self.assertNotIn("Tipe Invoice", html)
		self.assertNotIn("Kurs USD", html)
		self._lang("en")
		html = frappe.get_print("Sales Invoice", None, "OAK Invoice", doc=_invoice())
		for text in ("DRAFT – NOT FINAL", "OTHERS", "Amount in Words", "Due Date", "only."):
			self.assertIn(text, html)
		self.assertNotIn("Terbilang", html)
		# Our order number stays off the page: the customer reconciles by their own reference.
		self.assertNotIn("GONE-1", html)
		# Invoice Title heads the page in place of INVOICE.
		si = _invoice()
		si.depot_invoice_title = "DEBIT NOTE"
		self.assertIn("DEBIT NOTE", frappe.get_print("Sales Invoice", None, "OAK Invoice", doc=si))
		# Cust. Ref / Tank No. columns print only when ticked.
		self.assertNotIn("TANK NO.", html)
		si.depot_print_tank = 1
		self.assertIn("TANK NO.", frappe.get_print("Sales Invoice", None, "OAK Invoice", doc=si))

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
