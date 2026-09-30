"""Pending Cash in erp_cakra's shape (2026-09-30).

* ``bank_account`` was the Kas/Bank GL account; it is now the company's Bank Account (rekening),
  as on the Payment Entry. Each value is repointed to the Bank Account on that GL account, or
  cleared when there is none — the journal already posted keeps its account either way.
* ``payment_no`` / ``settled`` (and the Completed status) are new rollups of the Payment
  Entries drawing on each Pending Cash.
* The Payment Entry form script changed with it: its meta is cached on the DocType's
  ``modified``, which an ERPNext doctype's JSON will not bump for us.
"""

import frappe
from frappe.utils import now


def execute():
	from container_depot.container_depot.doctype.pending_cash.pending_cash import sync_document_links

	for name, value in frappe.db.sql(
		"SELECT name, bank_account FROM `tabPending Cash` WHERE IFNULL(bank_account, '') != ''"
	):
		if not frappe.db.exists("Bank Account", value):
			ba = frappe.db.get_value("Bank Account", {"account": value, "is_company_account": 1}, "name")
			frappe.db.set_value("Pending Cash", name, "bank_account", ba, update_modified=False)
	sync_document_links(frappe.get_all("Pending Cash", pluck="name"))
	frappe.db.set_value("DocType", "Payment Entry", "modified", now(), update_modified=False)
	frappe.clear_cache(doctype="Payment Entry")
