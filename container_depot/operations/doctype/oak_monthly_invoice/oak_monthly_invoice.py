import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from container_depot import invoicing

# PPN rate for the doctype-level display total. The generated Sales Invoice
# applies the same rate natively via the PPN tax template (authoritative).
PPN_RATE = 0.11


class OAKMonthlyInvoice(Document):
	def validate(self):
		self._compute_totals()
		self._guard_unique_period()

	def _compute_totals(self):
		subtotal = sum(flt(i.amount) for i in (self.items or []))
		self.subtotal = subtotal
		self.ppn = round(subtotal * PPN_RATE, 2)
		self.total = self.subtotal + self.ppn

	def _guard_unique_period(self):
		"""One monthly invoice per (customer, period, category)."""
		dup = frappe.db.exists(
			"OAK Monthly Invoice",
			{
				"customer": self.customer,
				"period": self.period,
				"category": self.category,
				"name": ["!=", self.name],
				"docstatus": ["<", 2],
			},
		)
		if dup:
			frappe.throw(
				_("A {0} invoice for {1} / {2} already exists ({3}).").format(
					self.category, self.customer, self.period, dup
				)
			)

	def on_submit(self):
		"""Generate the native ERPNext Sales Invoice (with PPN) for this period."""
		if self.sales_invoice or not (self.total and self.total > 0):
			return
		lines = [
			{
				"description": (i.description or i.container or self.category),
				"qty": 1,
				"rate": flt(i.amount),
			}
			for i in (self.items or [])
		]
		try:
			si = invoicing.create_draft_sales_invoice(
				self.customer,
				lines,
				due_days=30,
				remarks=f"OAK {self.category} invoice {self.period} ({self.name})",
				taxes_and_charges=invoicing.PPN_TEMPLATE,
			)
			if si:
				self.db_set("sales_invoice", si, update_modified=False)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"monthly invoice SI failed: {self.name}")
