"""Sales Invoice controller override.

"Don't Post to GL", the erp_cakra way: a ticked invoice submits without a journal, and so
without Payment Ledger rows either: it never shows as outstanding, and the Payment Entry
document picker (which reads that ledger) does not offer it.

No Payment Terms Template: the Payment Term is a label (depot_payment_term).
"""

from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice


class DepotSalesInvoice(SalesInvoice):
	def make_gl_entries(self, *args, **kwargs):
		if self.get("dont_post_to_gl"):
			return
		return super().make_gl_entries(*args, **kwargs)

	def set_payment_schedule(self):
		# ERPNext fills the template from the customer's default (set_missing_values, inside
		# validate) and would then date the schedule — and check the Due Date — against it. The
		# Due Date is the user's (invoicing.header_rules), so a draft carries no template.
		if self.docstatus == 0:
			self.payment_terms_template = None
		return super().set_payment_schedule()
