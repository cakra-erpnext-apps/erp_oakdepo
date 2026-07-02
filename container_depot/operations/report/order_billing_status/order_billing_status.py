"""Order Billing Status — one list of every order across the 4 order types with
its billing/invoice state.

Unions Container Booking, Cleaning Order, Repair Order and Survey Order into a
single, normalized list so the depot can see — in one place — which orders are
already invoiced/paid and, crucially, which **TOP** (postpaid/termin) orders are
still un-invoiced and ready to be swept into one consolidated Sales Invoice via
``consolidated_billing.bill_customer``.

Read-only monitor (Phase 1). No billing logic lives here — amounts/status are
read from the orders' stored fields, and TOP-vs-Cash for cleaning/repair reuses
the same ``_is_postpaid`` authority as the billing engine.

Each order carries its own currency (IDR / USD), so the Amount column is bound to
the per-row ``currency`` and formatted in that currency. Booking/Cleaning/Survey
store a ``currency`` field; Repair Order has none, so its currency is read from the
owner's active Depot Contract (falling back to the company default).

The report is role-gated (see its .json ``roles``) to internal commercial roles;
queries run with ``ignore_permissions`` and would otherwise expose every
customer's data to a portal Customer, so it must NOT be opened to Customer.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt, getdate

from container_depot.monthly_invoicing import _active_contract, _is_postpaid
from container_depot.operations.doctype.survey_order.survey_order import (
	_survey_invoice_status,
)

ORDER_TYPES = ("Container Booking", "Cleaning Order", "Repair Order", "Survey Order")


def execute(filters=None):
	filters = filters or {}
	order_type = filters.get("order_type")
	ctx = {
		"postpaid": {},              # customer -> bool (memoized _is_postpaid)
		"currency": {},              # customer -> contract currency (memoized)
		"default": _default_currency(),
	}

	rows = []
	if not order_type or order_type == "Container Booking":
		rows += _booking_rows(filters, ctx)
	if not order_type or order_type == "Cleaning Order":
		rows += _cleaning_rows(filters, ctx)
	if not order_type or order_type == "Repair Order":
		rows += _repair_rows(filters, ctx)
	if not order_type or order_type == "Survey Order":
		rows += _survey_rows(filters, ctx)

	# payment_type / invoice_status are derived, so filter them after building rows.
	pt = filters.get("payment_type")
	inv = filters.get("invoice_status")
	if pt:
		rows = [r for r in rows if r["payment_type"] == pt]
	if inv:
		rows = [r for r in rows if r["invoice_status"] == inv]

	rows.sort(key=lambda r: (r["date"] or getdate("1900-01-01")), reverse=True)
	return _columns(), rows


def _columns():
	return [
		{"fieldname": "order_type", "label": "Order Type", "fieldtype": "Data", "width": 130},
		{"fieldname": "order", "label": "Order", "fieldtype": "Dynamic Link", "options": "order_type", "width": 150},
		{"fieldname": "customer", "label": "Customer", "fieldtype": "Link", "options": "Customer", "width": 190},
		{"fieldname": "date", "label": "Date", "fieldtype": "Date", "width": 100},
		{"fieldname": "payment_type", "label": "Payment", "fieldtype": "Data", "width": 80},
		{"fieldname": "currency", "label": "Currency", "fieldtype": "Link", "options": "Currency", "width": 80},
		{"fieldname": "amount", "label": "Amount", "fieldtype": "Currency", "options": "currency", "width": 130},
		{"fieldname": "invoice_status", "label": "Invoice Status", "fieldtype": "Data", "width": 120},
		{"fieldname": "sales_invoice", "label": "Sales Invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 160},
	]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _default_currency():
	return (
		frappe.defaults.get_global_default("currency")
		or frappe.db.get_default("currency")
		or "IDR"
	)


def _apply_date(f: dict, field: str, filters: dict) -> None:
	"""Add a range condition on ``field`` from the report's from/to filters."""
	frm, to = filters.get("from_date"), filters.get("to_date")
	if frm and to:
		f[field] = ["between", [f"{frm} 00:00:00", f"{to} 23:59:59"]]
	elif frm:
		f[field] = [">=", f"{frm} 00:00:00"]
	elif to:
		f[field] = ["<=", f"{to} 23:59:59"]


def _si_status(sales_invoice):
	"""Normalized invoice status for an order linked to a Sales Invoice.

	Reuses the Survey Order → SI mapper (Not Invoiced / Draft / Unpaid / Partly
	Paid / Overdue / Paid / Cancelled)."""
	if not sales_invoice:
		return "Not Invoiced"
	return _survey_invoice_status(sales_invoice)


def _postpaid(customer, ctx) -> bool:
	"""Memoized ``_is_postpaid`` (TOP/Both active contract) per execute() call."""
	if not customer:
		return False
	cache = ctx["postpaid"]
	if customer not in cache:
		cache[customer] = bool(_is_postpaid(customer))
	return cache[customer]


def _contract_currency(customer, ctx):
	"""Currency of the customer's active Depot Contract (memoized), for order types
	that don't store their own currency (Repair Order). Falls back to the default."""
	if not customer:
		return ctx["default"]
	cache = ctx["currency"]
	if customer not in cache:
		contract = _active_contract(customer)
		cache[customer] = (
			frappe.db.get_value("Depot Contract", contract, "currency") if contract else None
		)
	return cache[customer] or ctx["default"]


# --------------------------------------------------------------------------- #
# Per-doctype row builders
# --------------------------------------------------------------------------- #
def _booking_rows(filters, ctx):
	f = {"docstatus": 1}
	if filters.get("customer"):
		f["customer"] = filters["customer"]
	_apply_date(f, "creation", filters)
	recs = frappe.get_all(
		"Container Booking",
		filters=f,
		fields=["name", "customer", "creation", "payment_type", "lift_amount", "currency", "sales_invoice"],
		ignore_permissions=True,
	)
	return [
		{
			"order_type": "Container Booking",
			"order": r.name,
			"customer": r.customer,
			"date": getdate(r.creation),
			"payment_type": r.payment_type,
			"currency": r.currency or ctx["default"],
			"amount": flt(r.lift_amount),
			"invoice_status": _si_status(r.sales_invoice),
			"sales_invoice": r.sales_invoice,
		}
		for r in recs
	]


def _cleaning_rows(filters, ctx):
	f = {"status": "Completed"}
	_apply_date(f, "cleaning_end", filters)
	recs = frappe.get_all(
		"Cleaning Order",
		filters=f,
		fields=["name", "container", "cleaning_end", "cleaning_total", "currency", "sales_invoice"],
		ignore_permissions=True,
	)
	want_customer = filters.get("customer")
	out = []
	for r in recs:
		owner = frappe.db.get_value("Container", r.container, "principal") if r.container else None
		if want_customer and owner != want_customer:
			continue
		out.append({
			"order_type": "Cleaning Order",
			"order": r.name,
			"customer": owner,
			"date": getdate(r.cleaning_end),
			"payment_type": "TOP" if _postpaid(owner, ctx) else "Cash",
			"currency": r.currency or ctx["default"],
			"amount": flt(r.cleaning_total),
			"invoice_status": _si_status(r.sales_invoice),
			"sales_invoice": r.sales_invoice,
		})
	return out


def _repair_rows(filters, ctx):
	f = {"status": "Completed"}
	if filters.get("customer"):
		f["principal"] = filters["customer"]
	_apply_date(f, "completion_date", filters)
	recs = frappe.get_all(
		"Repair Order",
		filters=f,
		fields=["name", "principal", "completion_date", "total_cost", "billing_status", "sales_invoice"],
		ignore_permissions=True,
	)
	# Repair now carries a sales_invoice back-link (set on Generate), so its live invoice
	# status reads from the SI like the others; else fall back to billing_status. Currency
	# has no field on Repair — it comes from the owner's active Depot Contract.
	def _repair_status(r):
		if r.sales_invoice:
			return _si_status(r.sales_invoice)
		return "Not Invoiced" if r.billing_status == "Unbilled" else "Billed"

	return [
		{
			"order_type": "Repair Order",
			"order": r.name,
			"customer": r.principal,
			"date": getdate(r.completion_date),
			"payment_type": "TOP" if _postpaid(r.principal, ctx) else "Cash",
			"currency": _contract_currency(r.principal, ctx),
			"amount": flt(r.total_cost),
			"invoice_status": _repair_status(r),
			"sales_invoice": r.sales_invoice,
		}
		for r in recs
	]


def _survey_rows(filters, ctx):
	f = {"docstatus": 1}
	if filters.get("customer"):
		f["paid_to"] = filters["customer"]
	_apply_date(f, "creation", filters)
	recs = frappe.get_all(
		"Survey Order",
		filters=f,
		fields=["name", "paid_to", "creation", "payment_type", "total", "currency", "sales_invoice", "invoice_status"],
		ignore_permissions=True,
	)
	return [
		{
			"order_type": "Survey Order",
			"order": r.name,
			"customer": r.paid_to,
			"date": getdate(r.creation),
			"payment_type": r.payment_type,
			"currency": r.currency or ctx["default"],
			"amount": flt(r.total),
			# Survey Order keeps its own invoice_status synced from the linked SI.
			"invoice_status": r.invoice_status or "Not Invoiced",
			"sales_invoice": r.sales_invoice,
		}
		for r in recs
	]
