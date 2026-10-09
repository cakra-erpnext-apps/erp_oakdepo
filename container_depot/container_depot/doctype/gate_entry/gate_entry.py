import frappe
from frappe import _
from frappe.model.document import Document
import datetime
import hashlib

from frappe.utils import getdate


class GateEntry(Document):
	def before_discard(self):
		# A gate record is an audit log of a visit: discarding it (docstatus 2) dropped the
		# visit out of storage billing while its status still read open. It closes through
		# its bon (Order Bongkar / Muat void), never on its own.
		frappe.throw(_("Gate Entry tidak bisa di-discard — batalkan bon-nya."))

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
				frappe.throw(_("Booking Code {0} not found.").format(self.booking_code))
			if bc.state not in ("Active", "Used"):
				frappe.throw(
					_("Booking Code {0} state is {1}; cannot pass the gate.").format(self.booking_code, bc.state)
				)
			if bc.container_no and self.container_no and bc.container_no.upper() != self.container_no.upper():
				frappe.throw(
					_("Container {0} does not match Booking Code container {1}.").format(self.container_no, bc.container_no)
				)

	def on_update(self):
		# A gate log stays a draft for the whole visit, so a truck / driver corrected on it is an
		# ordinary save — and it is the booking line's, like a Revisi Data on a submitted one.
		before = self.get_doc_before_save()
		if before:
			revision_apply(self, before)

	def before_submit(self):
		"""Set status on submit"""
		self.status = "Gate_In_Completed"

	def on_submit(self):
		"""Update container status on gate entry submission"""
		from container_depot.container_depot.container_activity import log_container_activity

		container_ref = self.get("container") or self.container_no
		if container_ref and frappe.db.exists("Container", container_ref):
			from container_depot.container_depot.container_status import IN_DEPOT, PRESENT

			container = frappe.get_doc("Container", container_ref)
			from_status = container.status
			# Inbound rule: a tank must NOT already be inside a depot to gate in.
			if container.status in PRESENT:
				frappe.throw(
					_("Container {0} sudah ada di depo (status {1}) — tidak bisa gate-in lagi.").format(
						container.container_no or container.name, container.status
					)
				)
			container.status = IN_DEPOT
			# A kiosk arrival has no bon: the day it came in is the gate's own day.
			self.in_date = getdate(self.gate_in_timestamp or datetime.datetime.now())
			self.db_set("in_date", self.in_date, update_modified=False)
			container.in_date = self.in_date
			container.out_date = None
			container.save(ignore_permissions=True)
			# In_Depot means "here WITH open work". A tank that arrives with nothing open
			# — no EIR draft, no cleaning, no M&R — is already free to leave, so the
			# arrival settles on the computed state instead of parking on In_Depot until
			# some order happens to fire a recompute.
			from container_depot.container_depot.container_status import recompute_availability

			recompute_availability(container.name)
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

	def before_cancel(self):
		from container_depot.container_depot.bon_revision import _assert_storage_not_invoiced

		_assert_storage_not_invoiced(self, _("Gate Entry tidak bisa dibatalkan"))

	def on_cancel(self):
		"""Void a gate entry: take back the arrival it stamped, and say so on the record.

		``on_submit`` is what puts a tank inside — ``In_Depot`` plus an ``in_date`` — so
		cancelling has to give both back, or a tank let in on a gate entry that no longer
		exists stands in the yard for good. Only the arrival THIS record made is undone: a
		tank that has since gated out is on a later chapter of its visit and is left as it
		is. Open work does NOT hold it any more (user, 2026-10-09 — same rule as
		``order_bongkar._release_container_arrival``): it used to, and the record went void
		while the tank silently stayed In_Depot. It goes back to ``Booked`` while the booking
		its code came from still expects it, else ``Gate_Out``.

		The status Select is moved to ``Cancelled`` for the same reason as the EIR's: Riwayat
		Gate reads ``status``, not docstatus, so a cancelled record would otherwise keep
		reading as a live visit.
		"""
		from container_depot.container_depot.container_activity import log_container_activity
		from container_depot.container_depot.container_status import PRESENT

		self.db_set("status", "Cancelled", update_modified=False)
		container_ref = self.get("container") or frappe.db.get_value(
			"Container", {"container_no": self.container_no}
		)
		if not container_ref or not frappe.db.exists("Container", container_ref):
			return
		cur = frappe.db.get_value(
			"Container", container_ref, ["status", "in_date"], as_dict=True
		)
		if not cur or cur.status not in PRESENT:
			return
		# ...and the arrival on the tank has to be the one THIS record wrote. A tank arrived
		# by a bon (`order_bongkar._sync_container_arrival`) carries that document's stamp,
		# and voiding a gate log beside it is no reason to send the tank back out.
		# A record with no Tanggal Masuk, or a different one, did not let this tank in.
		if not self.in_date or not cur.in_date or getdate(cur.in_date) != getdate(self.in_date):
			return
		# Through the ORM under the automation flag, never a raw write: `Container.on_update`
		# is what logs the Status Movement and re-derives the storage visit, so an arrival
		# taken back underneath it would leave the tank's audit trail ending at a status it
		# no longer has. The flag only bypasses the manual-transition guard.
		booking = self.get("booking_code") and frappe.db.get_value(
			"Booking Code", self.booking_code, "booking"
		)
		live = booking and frappe.db.get_value(
			"Container Booking", booking, ["docstatus", "booking_status"], as_dict=True
		)
		back_to = "Booked" if live and live.docstatus < 2 and live.booking_status != "Cancelled" else "Gate_Out"
		frappe.flags.in_status_automation = True
		try:
			tank = frappe.get_doc("Container", container_ref)
			tank.status = back_to
			tank.in_date = None
			from container_depot.container_depot.doctype.order_bongkar.order_bongkar import _last_out_date

			tank.out_date = _last_out_date(self.container_no)  # on_submit cleared it
			tank.save(ignore_permissions=True)
		finally:
			frappe.flags.in_status_automation = False
		log_container_activity(
			container_ref, "Status Change",
			reference_doctype=self.doctype, reference_name=self.name,
			from_status=cur.status, to_status=back_to,
			performed_by=self.get("security_guard"),
			summary="Gate Entry dibatalkan — kedatangan tank dibatalkan",
		)

	def onload(self):
		# Revisi Data / Tolak Revisi on the Desk form (public/js/revision.js).
		if self.docstatus == 1:
			from container_depot.container_depot import revision

			self.set_onload("revision_state", revision.state(self))

	def before_update_after_submit(self):
		# Revisi Data — a finished record corrected in place (revision.py).
		if self.flags.get("revision"):
			from container_depot.container_depot import revision

			revision.check(self)

	def on_update_after_submit(self):
		if self.flags.get("revision"):
			from container_depot.container_depot import revision

			revision.after(self)

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


# --- Revisi Data hooks (revision.py) ---------------------------------------------------
# A finished gate record corrects who drove, which truck and which guard. The gate times stay:
# the visit and its storage are counted from them (storage.visit_for falls back on them) —
# the day in/out itself is corrected on the bon (Revisi Bon).
REVISION_LOCKED = (
	"gate_entry_id", "status", "booking_code", "depot", "order_doctype", "order_ref",
	"container_no", "gate_in_timestamp", "gate_out_timestamp", "eir_reference",
	"inspection_status", "in_date", "out_date", "order_muat",
)
REVISION_PWA_FIELDS = ("truck_plate", "driver_name")


def revision_invoice(doc):
	return None  # a gate record is not priced


def revision_apply(doc, before) -> None:
	"""``revision.py`` hook: the truck / driver are the booking line's — the visit's arrival
	bon's when it has one, else its departure bon's — so a correction goes there and comes
	back to the bon, its EIR and this record (order_generation.push_follower_to_line)."""
	from container_depot.container_depot.order_generation import push_follower_to_line

	if doc.get("order_doctype") == "Order Bongkar":
		push_follower_to_line(doc, before, "Order Bongkar", doc.get("order_ref"))
	else:
		push_follower_to_line(doc, before, "Order Muat", doc.get("order_muat") or doc.get("order_ref"))


def revision_blocker(doc):
	if doc.status == "Cancelled":
		return _("Gate record ini sudah dibatalkan.")
	return None
