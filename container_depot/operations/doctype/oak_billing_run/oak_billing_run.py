"""OAK Billing Run — the depot's manual trigger for consolidated postpaid billing.

Pick a customer (+ optional window) and submit: every unbilled booking / order /
cleaning / M&R / storage charge is swept into one draft Sales Invoice (PPN) via
``consolidated_billing.bill_customer``, and linked back here for audit.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from container_depot.consolidated_billing import bill_customer


class OAKBillingRun(Document):
	def on_submit(self):
		si = bill_customer(self.customer, self.from_date, self.to_date)
		if not si:
			frappe.throw(
				_("No unbilled charges found for {0} in the selected window.").format(self.customer)
			)
		self.db_set("sales_invoice", si, update_modified=False)
		self.db_set(
			"total", frappe.db.get_value("Sales Invoice", si, "grand_total") or 0, update_modified=False
		)
