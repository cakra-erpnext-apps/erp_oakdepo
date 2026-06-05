import frappe
from frappe import _
from frappe.model.document import Document

from container_depot import invoicing, pricing


class OrderBongkar(Document):
	def validate(self):
		_validate_booking_code(self, "Tank In")
		_fill_qr_image(self)
		_compute_amount(self)

	def on_submit(self):
		_invoice_order(self)


def _validate_booking_code(doc: Document, expected_direction: str):
	"""Ensure the linked Booking Code is Active and matches the order direction."""
	if not doc.booking_code:
		return
	bc = frappe.db.get_value(
		"Booking Code",
		doc.booking_code,
		["state", "direction", "container", "container_no", "expires_at"],
		as_dict=True,
	)
	if not bc:
		frappe.throw(_("Booking Code {0} not found.").format(doc.booking_code))
	if bc.direction != expected_direction:
		frappe.throw(
			_("Booking Code {0} is for {1}, not {2}.").format(
				doc.booking_code, bc.direction, expected_direction
			)
		)
	if bc.state != "Active":
		frappe.throw(_("Booking Code {0} state is {1}; must be Active.").format(doc.booking_code, bc.state))
	# Auto-populate container fields if blank.
	if not doc.container and bc.container:
		doc.container = bc.container
	if not doc.container_no and bc.container_no:
		doc.container_no = bc.container_no


def _fill_qr_image(doc: Document):
	if doc.qr_code or not doc.booking_code:
		return
	qr = frappe.db.get_value("Booking Code", doc.booking_code, "qr_image")
	if qr:
		doc.qr_code = qr


def _compute_amount(doc: Document):
	"""Derive total_amount (and unit rate) from price_per_container or tariff."""
	total, rate = pricing.order_amount(doc)
	doc.total_amount = total
	if not doc.price_per_container and rate:
		doc.price_per_container = rate


def _order_customer(doc: Document):
	"""Customer behind an order, via its Booking Code -> Isotank Booking."""
	if not doc.booking_code:
		return None
	booking = frappe.db.get_value("Booking Code", doc.booking_code, "booking")
	if not booking:
		return None
	return frappe.db.get_value("Isotank Booking", booking, "customer")


def _invoice_order(doc: Document):
	"""Best-effort: auto-generate a Draft Sales Invoice (due +30d) for the order.

	Skipped when there's nothing to bill (rate 0), an invoice already exists, or
	the order's contract is TOP (postpaid) — TOP orders accrue and are swept later
	by ``consolidated_billing.bill_customer``. Never blocks the submit.
	"""
	if doc.get("sales_invoice") or not (doc.total_amount and doc.total_amount > 0):
		return
	contract = pricing.contract_for_order(doc)
	if contract and frappe.db.get_value("Depot Contract", contract, "payment_type") == "TOP":
		return  # accrue to the customer's consolidated bill
	customer = _order_customer(doc)
	if not customer:
		return
	try:
		si = invoicing.create_draft_sales_invoice(
			customer,
			[{
				"description": f"{doc.doctype} {doc.name} · {doc.order_type or ''} · {doc.container_no or ''}".strip(),
				"qty": doc.quantity or 1,
				"rate": doc.price_per_container or 0,
			}],
			due_days=30,
			remarks=f"Auto-generated from {doc.doctype} {doc.name}",
		)
		if si:
			doc.db_set("sales_invoice", si, update_modified=False)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"auto-invoice failed: {doc.doctype} {doc.name}")
