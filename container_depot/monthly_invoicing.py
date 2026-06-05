"""Monthly categorized invoice generation (Tank Owner billing).

Aggregates a prior month's depot activity into one OAK Monthly Invoice per
(customer, period, category): Cleaning / M&R / Storage / Order Service. Each
invoice's ``on_submit`` then issues a native ERPNext Sales Invoice with PPN.

Invoked monthly by :func:`container_depot.tasks.generate_monthly_invoices`, but
``generate_monthly_invoices(period="YYYY-MM")`` can also be called directly.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_months, get_first_day, get_last_day, getdate, today

from container_depot.pricing import resolve_tariff_rate

CATEGORIES = ("Cleaning", "M&R", "Storage", "Order Service")


def _period_window(period=None):
	"""Return (period_str, from_date, to_date). Defaults to the prior month."""
	if period:
		anchor = getdate(period + "-01")
	else:
		anchor = add_months(get_first_day(getdate(today())), -1)
	return anchor.strftime("%Y-%m"), get_first_day(anchor), get_last_day(anchor)


def _bounds(from_date, to_date):
	return f"{from_date} 00:00:00", f"{to_date} 23:59:59"


def _active_contract(customer):
	return frappe.db.get_value("Depot Contract", {"customer": customer, "status": "Active"}, "name")


def _is_postpaid(customer):
	"""True if the customer's Active contract is TOP. TOP customers are billed
	on-demand via ``consolidated_billing.bill_customer`` (postpaid accrual), so the
	monthly scheduler must skip them to avoid double-billing."""
	return (
		frappe.db.get_value("Depot Contract", {"customer": customer, "status": "Active"}, "payment_type")
		== "TOP"
	)


def _order_customer(order_name, doctype):
	code = frappe.db.get_value(doctype, order_name, "booking_code")
	if not code:
		return None
	booking = frappe.db.get_value("Booking Code", code, "booking")
	return frappe.db.get_value("Isotank Booking", booking, "customer") if booking else None


# --------------------------------------------------------------------------- #
# Category builders — each returns a list of OAK Monthly Invoice Item dicts.
# --------------------------------------------------------------------------- #
def _mr_items(customer, from_date, to_date):
	lo, hi = _bounds(from_date, to_date)
	rows = frappe.get_all(
		"Repair Order",
		filters={"status": "Completed", "principal": customer, "completion_date": ["between", [lo, hi]]},
		fields=["name", "container", "total_cost", "completion_date"],
	)
	return [
		{
			"container": r.container,
			"reference_doctype": "Repair Order",
			"reference_name": r.name,
			"description": f"M&R {r.name}",
			"service_date": getdate(r.completion_date),
			"amount": r.total_cost or 0,
		}
		for r in rows
	]


def _cleaning_items(customer, from_date, to_date):
	lo, hi = _bounds(from_date, to_date)
	rate = resolve_tariff_rate(_active_contract(customer), "Cleaning")
	rows = frappe.get_all(
		"Cleaning Order",
		filters={"status": "Completed", "cleaning_end": ["between", [lo, hi]]},
		fields=["name", "container", "cleaning_end"],
	)
	items = []
	for r in rows:
		if frappe.db.get_value("Container", r.container, "principal") != customer:
			continue
		items.append({
			"container": r.container,
			"reference_doctype": "Cleaning Order",
			"reference_name": r.name,
			"description": f"Cleaning {r.name}",
			"service_date": getdate(r.cleaning_end),
			"amount": rate,
		})
	return items


def _order_service_items(customer, from_date, to_date):
	lo, hi = _bounds(from_date, to_date)
	items = []
	for doctype in ("Order Bongkar", "Order Muat"):
		rows = frappe.get_all(
			doctype,
			filters={"creation": ["between", [lo, hi]], "total_amount": [">", 0]},
			fields=["name", "container", "total_amount", "order_type", "creation"],
		)
		for r in rows:
			if _order_customer(r.name, doctype) != customer:
				continue
			items.append({
				"container": r.container,
				"reference_doctype": doctype,
				"reference_name": r.name,
				"description": f"{r.order_type or 'Order'} {r.name}",
				"service_date": getdate(r.creation),
				"amount": r.total_amount or 0,
			})
	return items


def _storage_items(customer, from_date, to_date):
	"""Best-effort storage accrual: days a tank sat in the depot during the
	window (last gate-in -> gate-out / window end) x the Storage per Day tariff."""
	rate = resolve_tariff_rate(_active_contract(customer), "Storage per Day")
	if not rate:
		return []
	containers = frappe.get_all("Container", filters={"principal": customer}, pluck="name")
	items = []
	for cname in containers:
		days = _days_in_depot(cname, from_date, to_date)
		if days <= 0:
			continue
		items.append({
			"container": cname,
			"reference_doctype": "Container",
			"reference_name": cname,
			"description": f"Storage {cname} ({days}d)",
			"service_date": to_date,
			"days": days,
			"rate": rate,
			"amount": days * rate,
		})
	return items


def _days_in_depot(container, from_date, to_date):
	"""Days the container was in the depot during [from_date, to_date]."""
	lo, hi = _bounds(from_date, to_date)
	moves = frappe.get_all(
		"Container Movement",
		filters={"container": container, "event_type": ["in", ["Status", "Combined"]], "movement_timestamp": ["<=", hi]},
		fields=["to_status", "movement_timestamp"],
		order_by="movement_timestamp asc",
	)
	if not moves:
		return 0
	gate_in = None
	for m in moves:
		if m.to_status in ("Gate_In", "Available") and gate_in is None:
			gate_in = getdate(m.movement_timestamp)
		if m.to_status == "Gate_Out":
			gate_in = None
	if gate_in is None:
		return 0
	start = max(gate_in, from_date)
	return max(0, (to_date - start).days + 1)


_BUILDERS = {
	"Cleaning": _cleaning_items,
	"M&R": _mr_items,
	"Storage": _storage_items,
	"Order Service": _order_service_items,
}


def create_monthly_invoice(customer, period, category, from_date, to_date, items):
	"""Create a draft OAK Monthly Invoice. Skips empty sets and duplicates."""
	if not items:
		return None
	if frappe.db.exists(
		"OAK Monthly Invoice",
		{"customer": customer, "period": period, "category": category, "docstatus": ["<", 2]},
	):
		return None
	doc = frappe.get_doc({
		"doctype": "OAK Monthly Invoice",
		"customer": customer,
		"period": period,
		"category": category,
		"from_date": from_date,
		"to_date": to_date,
		"status": "Unpaid",
		"items": items,
	})
	doc.insert(ignore_permissions=True)
	return doc.name


def generate_monthly_invoices(period=None):
	"""Generate categorized monthly invoices for all Tank Owner customers.

	Returns the count of invoices created. Idempotent per (customer, period,
	category).
	"""
	period, from_date, to_date = _period_window(period)
	customers = frappe.get_all(
		"Customer",
		filters={"oak_customer_type": ["in", ["Tank Owner", "Both"]]},
		pluck="name",
	)
	created = 0
	for customer in customers:
		if _is_postpaid(customer):
			continue  # TOP → billed on-demand via consolidated_billing.bill_customer
		for category in CATEGORIES:
			items = _BUILDERS[category](customer, from_date, to_date)
			if create_monthly_invoice(customer, period, category, from_date, to_date, items):
				created += 1
	if created:
		frappe.db.commit()
	return created
