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

		A Booking Code encodes payment status (an Active code is only issued
		after the Cash invoice is paid / TOP credit cleared), so an Active or
		Used code is what clears the gate.
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

	def before_submit(self):
		"""Set status on submit"""
		self.status = "Gate_In_Completed"

	def on_submit(self):
		"""Update container status on gate entry submission"""
		from container_depot.operations.container_activity import log_container_activity

		container_ref = self.get("container") or self.container_no
		if container_ref and frappe.db.exists("Container", container_ref):
			from container_depot.operations.container_status import IN_DEPOT, PRESENT

			container = frappe.get_doc("Container", container_ref)
			from_status = container.status
			# Inbound rule: a tank must NOT already be inside a depot to gate in.
			if container.status in PRESENT:
				frappe.throw(
					f"Container {container.container_no or container.name} sudah ada di depo "
					f"(status {container.status}) — tidak bisa gate-in lagi."
				)
			container.status = IN_DEPOT
			container.eir_in_date = self.gate_in_timestamp or datetime.datetime.now()
			container.save(ignore_permissions=True)
			log_container_activity(
				container.name, "Gate In",
				reference_doctype=self.doctype, reference_name=self.name,
				from_status=from_status, to_status=IN_DEPOT,
				performed_by=self.get("security_guard"),
				activity_time=self.gate_in_timestamp,
				summary=f"Gate-in (Booking Code {self.booking_code})" if self.booking_code else "Gate-in",
			)

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
