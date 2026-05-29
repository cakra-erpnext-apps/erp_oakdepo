import frappe
from frappe.model.document import Document
import datetime
import hashlib

class GateEntry(Document):
	def before_insert(self):
		"""Generate gate entry ID"""
		self.gate_entry_id = self.generate_gate_entry_id()

	def generate_gate_entry_id(self):
		"""Generate unique gate entry ID"""
		timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
		unique = hashlib.md5(f"{timestamp}{frappe.generate_hash()[:10]}".encode()).hexdigest()[:8].upper()
		return f"GE-{unique}"

	def before_save(self):
		"""Auto-populate container info"""
		if self.container_no and not self.get("container"):
			# Try to find container by container_no
			container = frappe.db.get_value("Container", {"container_no": self.container_no}, "name")
			if container:
				self.container = container

	def validate(self):
		"""Validate gate entry.

		If a Booking Code is set, it short-circuits the legacy Voucher payment
		check — the Booking Code already encodes payment status (an Active code
		was only issued after Cash invoice paid / TOP credit cleared).
		"""
		if self.booking_code:
			bc = frappe.db.get_value(
				"Booking Code",
				self.booking_code,
				["state", "container_no"],
				as_dict=True,
			)
			if not bc:
				frappe.throw(f"Booking Code {self.booking_code} not found.")
			if bc.state not in ("Active", "Used"):
				frappe.throw(
					f"Booking Code {self.booking_code} state is {bc.state}; cannot pass the gate."
				)
			if bc.container_no and self.container_no and bc.container_no.upper() != self.container_no.upper():
				frappe.throw(
					f"Container {self.container_no} does not match Booking Code container {bc.container_no}."
				)
			return
		if self.voucher:
			voucher = frappe.get_doc("Voucher", self.voucher)
			if not voucher.payment_status:
				frappe.throw("Voucher payment not verified. Cannot proceed with gate entry.")

	def before_submit(self):
		"""Set status on submit"""
		self.status = "Gate_In_Completed"

	def on_submit(self):
		"""Update container status on gate entry submission"""
		container_ref = self.get("container") or self.container_no
		if container_ref and frappe.db.exists("Container", container_ref):
			container = frappe.get_doc("Container", container_ref)
			container.status = "Gate_In"
			container.eir_in_date = self.gate_in_timestamp or datetime.datetime.now()
			container.save(ignore_permissions=True)
		
		# Generate and log UN/EDIFACT CODECO message
		self.generate_codeco_message()

	def generate_codeco_message(self):
		"""Generate a standard UN/EDIFACT CODECO Gate-In message segment text"""
		timestamp = (self.gate_in_timestamp or datetime.datetime.now()).strftime("%Y%m%d%H%M")
		date_simple = (self.gate_in_timestamp or datetime.datetime.now()).strftime("%y%m%d")
		time_simple = (self.gate_in_timestamp or datetime.datetime.now()).strftime("%H%M")
		
		# Fetch container info
		container_type = "ISO Tank"
		principal = "UNKNOWN"
		if self.container_no and frappe.db.exists("Container", self.container_no):
			container_info = frappe.db.get_value("Container", self.container_no, ["container_type", "principal"], as_dict=True)
			if container_info:
				container_type = container_info.container_type or "ISO Tank"
				principal = container_info.principal or "UNKNOWN"

		edi_segments = [
			f"UNB+UNOA:2+OAKDEPOT+{principal.replace(' ', '')}+{date_simple}:{time_simple}+1'",
			f"UNH+1+CODECO:D:95B:UN'",
			f"BGM+34+{self.name}+9'",
			f"TDT+20++30++{self.truck_plate or 'UNKNOWN'}:146'",
			f"NAD+CA+{principal.upper()}'",
			f"EQD+CN+{self.container_no}++++5'",
			f"DTM+7:{timestamp}:203'",
			f"CNT+1:1'",
			f"UNT+9+1'",
			f"UNZ+1+1'"
		]
		
		edi_text = "\n".join(edi_segments)
		
		# Log as a system comment on the document
		frappe.get_doc({
			"doctype": "Comment",
			"comment_type": "Comment",
			"reference_doctype": self.doctype,
			"reference_name": self.name,
			"content": f"<h4>Generated UN/EDIFACT CODECO EDI Message</h4><pre>{edi_text}</pre>",
			"comment_email": "system@oakdepot.com",
			"comment_by": "System"
		}).insert(ignore_permissions=True)

		return edi_text
