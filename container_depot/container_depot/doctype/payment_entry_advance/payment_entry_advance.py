# Copyright (c) 2026, OakDepo and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PaymentEntryAdvance(Document):
	"""An advance on a Purchase Order (Payment Entry, Advance Payable tab).

	payment_entry._apply_advance turns each row into a native reference to the order, so
	ERPNext books it as the advance it is and keeps the order's Advance Paid.
	"""
