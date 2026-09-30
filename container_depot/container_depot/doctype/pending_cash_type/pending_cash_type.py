import re

import frappe
from frappe import _
from frappe.model.document import Document


class PendingCashType(Document):
	def validate(self):
		# The code goes into the kasbon number (PC-{code}-OD-26-0001), so it has to be
		# something a document name can carry.
		code = (self.numbering_code or self.code or "").strip()
		if not re.fullmatch(r"[A-Za-z0-9._-]+", code):
			frappe.throw(_("Kode <b>{0}</b> hanya boleh huruf, angka, titik, strip dan garis bawah.").format(code))
