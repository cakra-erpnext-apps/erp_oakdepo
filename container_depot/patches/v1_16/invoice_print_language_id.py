"""Print invoices in Indonesian (user, 2026-09-30).

The OAK Invoice now prints in its Print Language, which ERPNext copies from the customer.
Every customer carried the site's default (English) without anyone choosing it, so move the
unchosen ones — English or empty — and their invoices to Indonesian. A customer billed in
English is set back on the Customer (Print Language), an invoice on the invoice.
"""

import frappe


def execute():
	unchosen = ["", "en", "en-US"]
	if frappe.db.exists("Language", "id"):
		frappe.db.set_value("Language", "id", "enabled", 1)
	for dt in ("Customer", "Sales Invoice"):
		frappe.db.sql(
			f"update `tab{dt}` set language = 'id' where ifnull(language, '') in %(unchosen)s",
			{"unchosen": unchosen},
		)
