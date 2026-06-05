import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime

# A single bon/voucher may carry at most this many containers.
MAX_CONTAINERS_PER_ORDER = 3


class OrderBongkar(Document):
	def validate(self):
		_sync_booking(self)
		_validate_booking_code(self, "Tank In")

	def on_update(self):
		_reconcile_codes(self)

	def on_cancel(self):
		_release_codes(self)


def _order_rows(doc: Document):
	"""Authoritative container rows for an order (the ``containers`` child table)."""
	return doc.get("containers") or []


def _sync_booking(doc: Document):
	"""Derive the header ``booking`` from the first container row's Booking Code
	(so a bon always belongs to exactly one booking)."""
	rows = _order_rows(doc)
	if not doc.get("booking") and rows and rows[0].booking_code:
		booking = frappe.db.get_value("Booking Code", rows[0].booking_code, "booking")
		if booking:
			doc.booking = booking


def _code_owned_by_order(doc: Document, code: str) -> bool:
	"""True if ``code`` is already persisted on THIS order — i.e. it was consumed
	by this very bon (so its ``Used`` state is expected, not an error)."""
	if doc.is_new() or not doc.name:
		return False
	return bool(
		frappe.db.exists(
			"Order Container Item",
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
		# Auto-populate row container fields if blank.
		if not row.get("container") and bc.container:
			row.container = bc.container
		if not row.get("container_no") and bc.container_no:
			row.container_no = bc.container_no


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
