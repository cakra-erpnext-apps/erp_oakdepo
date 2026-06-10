import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_datetime, now_datetime

# A single bon/voucher may carry at most this many containers.
MAX_CONTAINERS_PER_ORDER = 2


class OrderBongkar(Document):
	def validate(self):
		_sync_booking(self)
		_validate_booking_code(self, "Tank In")

	def on_update(self):
		_reconcile_codes(self)

	def on_submit(self):
		_log_order_activity(self, "Order Bongkar")

	def on_cancel(self):
		_release_codes(self)

	def on_trash(self):
		# A bon is never deleted — Cancel it (draft or submitted) to release its
		# containers and keep the audit trail. The UI Delete / Duplicate / New
		# actions are stripped in the form script; raw maintenance
		# (frappe.db.delete) bypasses this guard.
		frappe.throw(_("An Order Bongkar cannot be deleted — use Cancel to void it instead."))


def _order_rows(doc: Document):
	"""Authoritative container rows for an order (the ``containers`` child table)."""
	return doc.get("containers") or []


def _log_order_activity(order: Document, activity_type: str):
	"""Append one Container Activity per container row when a bon is submitted
	(shared by Order Bongkar + Order Muat)."""
	from container_depot.operations.container_activity import log_container_activity

	for row in _order_rows(order):
		if row.get("container"):
			log_container_activity(
				row.container, activity_type,
				reference_doctype=order.doctype, reference_name=order.name,
				summary=f"{activity_type} issued" + (f" (shipper {order.get('shipper')})" if order.get("shipper") else ""),
			)


def _sync_booking(doc: Document):
	"""Derive the header ``booking`` from the first container row's Booking Code
	(so a bon always belongs to exactly one booking), then carry the booking's
	Principal (Tank Owner) onto the header."""
	rows = _order_rows(doc)
	if not doc.get("booking") and rows and rows[0].booking_code:
		booking = frappe.db.get_value("Booking Code", rows[0].booking_code, "booking")
		if booking:
			doc.booking = booking
	if doc.get("booking") and doc.meta.has_field("principal") and not doc.get("principal"):
		doc.principal = frappe.db.get_value("Container Booking", doc.booking, "principal")


def _resolve_code_from_container(doc: Document, row) -> None:
	"""Manual grid add: the operator picks a Container (not the hidden Booking
	Code). Resolve its still-pending (``Active``) Booking Code on THIS voucher's
	booking so the row carries a code — keeping a single bon to one booking."""
	if row.booking_code or not doc.get("booking"):
		return
	if not (row.get("container") or row.get("container_no")):
		return
	base = {"booking": doc.booking, "state": "Active"}
	code = None
	if row.get("container"):
		code = frappe.db.get_value("Booking Code", {**base, "container": row.container}, "name")
	if not code and row.get("container_no"):
		code = frappe.db.get_value("Booking Code", {**base, "container_no": row.container_no}, "name")
	if code:
		row.booking_code = code


def _code_owned_by_order(doc: Document, code: str) -> bool:
	"""True if ``code`` is already persisted on THIS order — i.e. it was consumed
	by this very bon (so its ``Used`` state is expected, not an error)."""
	if doc.is_new() or not doc.name:
		return False
	return bool(
		frappe.db.exists(
			"Container Booking Item",
			{"parent": doc.name, "parenttype": doc.doctype, "booking_code": code},
		)
	)


def _validate_booking_code(doc: Document, expected_direction: str):
	"""Validate every container row's Booking Code: right direction, in this
	booking, 1..3 cap. A NEWLY added code must be ``Active`` and unexpired; a code
	already on this order may be ``Used`` (it was consumed by this bon).
	"""
	rows = _order_rows(doc)
	if not (1 <= len(rows) <= MAX_CONTAINERS_PER_ORDER):
		frappe.throw(
			_("An order must have between 1 and {0} containers (got {1}).").format(
				MAX_CONTAINERS_PER_ORDER, len(rows)
			)
		)
	seen = set()
	for row in rows:
		# Manual add picks a Container; back-resolve its Active Booking Code first.
		_resolve_code_from_container(doc, row)
		if not row.booking_code:
			frappe.throw(_("Row {0}: Booking Code is required.").format(row.idx))
		if row.booking_code in seen:
			frappe.throw(_("Booking Code {0} is listed more than once.").format(row.booking_code))
		seen.add(row.booking_code)
		bc = frappe.db.get_value(
			"Booking Code",
			row.booking_code,
			["state", "direction", "container", "container_no", "booking", "expires_at"],
			as_dict=True,
		)
		if not bc:
			frappe.throw(_("Booking Code {0} not found.").format(row.booking_code))
		if bc.direction != expected_direction:
			frappe.throw(
				_("Booking Code {0} is for {1}, not {2}.").format(
					row.booking_code, bc.direction, expected_direction
				)
			)
		if doc.get("booking") and bc.booking and bc.booking != doc.booking:
			frappe.throw(
				_("Booking Code {0} does not belong to booking {1}.").format(
					row.booking_code, doc.booking
				)
			)
		# Active/expiry only applies to a code being newly placed on this order.
		if not _code_owned_by_order(doc, row.booking_code):
			if bc.state != "Active":
				frappe.throw(
					_("Booking Code {0} state is {1}; must be Active.").format(row.booking_code, bc.state)
				)
			if bc.expires_at and get_datetime(bc.expires_at) < now_datetime():
				frappe.throw(_("Booking Code {0} has expired.").format(row.booking_code))
		# Auto-populate the row's container + booking-line detail from the booking line.
		# Order Bongkar reuses Container Booking Item, whose condition / cargo / Tgl.
		# Bongkar are required, so a manually added container inherits the booking's
		# values (the generate path fills these too).
		if not row.get("container_no") and bc.container_no:
			row.container_no = bc.container_no
		item = (
			frappe.db.get_value(
				"Container Booking Item",
				{"parent": bc.booking, "container_no": row.get("container_no")},
				["container", "condition", "cargo", "tanggal_bongkar", "truck_plate",
				 "driver", "driver_phone", "ro", "remarks"],
				as_dict=True,
			)
			if row.get("container_no")
			else None
		)
		if not row.get("container"):
			row.container = bc.container or (item.container if item else None)
		if item:
			for f in (
				"condition", "cargo", "tanggal_bongkar", "truck_plate",
				"driver", "driver_phone", "ro", "remarks",
			):
				if not row.get(f) and item.get(f):
					row.set(f, item.get(f))


def _reconcile_codes(doc: Document):
	"""Keep Booking Code state in step with the bon's container list:
	newly added codes are consumed (Active -> Used); codes removed from the bon
	are released (Used -> Active) so they can be issued on another voucher.
	"""
	current = {r.booking_code for r in _order_rows(doc) if r.booking_code}
	prev = doc.get_doc_before_save()
	previous = {r.booking_code for r in (prev.get("containers") if prev else []) if r.booking_code}
	for code in current - previous:
		if frappe.db.get_value("Booking Code", code, "state") == "Active":
			frappe.db.set_value("Booking Code", code, "state", "Used", update_modified=False)
	for code in previous - current:
		if frappe.db.get_value("Booking Code", code, "state") == "Used":
			frappe.db.set_value("Booking Code", code, "state", "Active", update_modified=False)


def _release_codes(doc: Document):
	"""Free this bon's codes back to Active (e.g. on cancel)."""
	for r in _order_rows(doc):
		if r.booking_code and frappe.db.get_value("Booking Code", r.booking_code, "state") == "Used":
			frappe.db.set_value("Booking Code", r.booking_code, "state", "Active", update_modified=False)


@frappe.whitelist()
def cancel_order(order):
	"""Cancel an Order Bongkar, releasing its Booking Codes back to ``Active`` so the
	containers can be put on a fresh voucher again.

	Works on a DRAFT (a draft can't pass through ``doc.cancel()``, so release the
	codes and set Cancelled directly) and on a SUBMITTED bon (normal cancel →
	``on_cancel`` releases the codes)."""
	doc = frappe.get_doc("Order Bongkar", order)
	if doc.docstatus == 2:
		frappe.throw(_("Order {0} is already cancelled.").format(doc.name))
	if doc.docstatus == 1:
		doc.cancel()
		return doc.name
	# Draft: free the codes, then mark Cancelled directly (parent + child rows).
	_release_codes(doc)
	frappe.db.set_value("Order Bongkar", doc.name, "docstatus", 2, update_modified=False)
	frappe.db.sql(
		"UPDATE `tabContainer Booking Item` SET docstatus = 2 "
		"WHERE parent = %s AND parenttype = 'Order Bongkar'",
		doc.name,
	)
	return doc.name


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def pending_container_query(doctype, txt, searchfield, start, page_len, filters):
	"""Containers still issuable onto a bon for a booking: those carrying an
	``Active`` Booking Code on that booking (i.e. not yet placed on a voucher).
	Drives the manual container picker in an Order Bongkar grid so one voucher
	can only mix containers from the SAME booking."""
	booking = (filters or {}).get("booking")
	if not booking:
		return []
	like = f"%{txt or ''}%"
	return frappe.db.sql(
		"""
		SELECT DISTINCT c.name, c.container_no
		FROM `tabContainer` c
		INNER JOIN `tabBooking Code` bc
			ON (bc.container = c.name OR bc.container_no = c.container_no)
		WHERE bc.booking = %(booking)s AND bc.state = 'Active'
		  AND (c.name LIKE %(like)s OR c.container_no LIKE %(like)s)
		ORDER BY c.container_no
		LIMIT {start}, {page_len}
		""".format(start=cint(start), page_len=cint(page_len)),
		{"booking": booking, "like": like},
	)
