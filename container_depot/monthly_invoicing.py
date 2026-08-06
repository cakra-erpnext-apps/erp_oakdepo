"""Monthly categorized invoice generation (Tank Owner billing).

Aggregates a prior month's depot activity into one OAK Monthly Invoice per
(customer, period, category): Cleaning / M&R / Periodic Test / Storage /
Order Service. Each
invoice's ``on_submit`` then issues a native ERPNext Sales Invoice with PPN.

Invoked monthly by :func:`container_depot.tasks.generate_monthly_invoices`, but
``generate_monthly_invoices(period="YYYY-MM")`` can also be called directly.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_months, get_first_day, get_last_day, getdate, today

from container_depot import finance
from container_depot.pricing import CLEANING_ITEM, STORAGE_ITEM, resolve_tariff_rate

# Lift on/off charges are billed at the BOOKING (Cash: paid at submit; TOP: swept
# by consolidated_billing). The voucher (Order Bongkar/Muat) is operational only,
# so there is no order-based billing category here.
CATEGORIES = ("Cleaning", "M&R", "Periodic Test", "Storage")


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
	"""True if the customer's Active contract carries a credit relationship (TOP or
	Both). Such customers are billed on-demand via ``consolidated_billing.bill_customer``
	(postpaid accrual), so the monthly scheduler must skip them to avoid double-billing.
	A Both customer's per-booking Cash charges are still settled at the booking; only
	their accruing (TOP / container-level) charges flow through consolidated billing."""
	return frappe.db.get_value(
		"Depot Contract", {"customer": customer, "status": "Active"}, "payment_type"
	) in ("TOP", "Both")


# --------------------------------------------------------------------------- #
# Category builders — each returns a list of OAK Monthly Invoice Item dicts.
# --------------------------------------------------------------------------- #
def _work_order_items(customer, from_date, to_date, doctype, party_field, label):
	"""Work-order charges for the monthly scheduler — ONE lump line per order.

	Work orders (M&R, Periodic Test) are a TOP arrangement in practice, so they are normally
	swept by ``consolidated_billing._work_order_lines`` instead, which bills item by item
	precisely so the Sales Invoice can charge labour off each ``item_code``. This monthly
	path only fires for a pure-Cash customer, and an OAK Monthly Invoice has no manhour
	machinery at all — so a charge landing here carries **parts only, no labour**. Kept as a
	safety net; if Cash work orders ever become real, this is what has to learn about labour.
	"""
	lo, hi = _bounds(from_date, to_date)
	rows = frappe.get_all(
		doctype,
		filters={"status": "Completed", party_field: customer, "completion_date": ["between", [lo, hi]]},
		fields=["name", "container", "total_cost", "completion_date"],
	)
	return [
		{
			"container": r.container,
			"reference_doctype": doctype,
			"reference_name": r.name,
			"description": f"{label} {r.name}",
			"service_date": getdate(r.completion_date),
			"amount": r.total_cost or 0,
		}
		for r in rows
	]


def _mr_items(customer, from_date, to_date):
	return _work_order_items(customer, from_date, to_date, "Repair Order", "principal", "M&R")


def _periodic_items(customer, from_date, to_date):
	return _work_order_items(
		customer, from_date, to_date, "Periodic Test Order", "billed_to", "Periodic Test"
	)


def _cleaning_items(customer, from_date, to_date):
	lo, hi = _bounds(from_date, to_date)
	fallback_rate = resolve_tariff_rate(_active_contract(customer), CLEANING_ITEM)
	rows = frappe.get_all(
		"Cleaning Order",
		filters={"status": "Completed", "cleaning_end": ["between", [lo, hi]]},
		fields=["name", "container", "cleaning_end"],
	)
	items = []
	for r in rows:
		if frappe.db.get_value("Container", r.container, "principal") != customer:
			continue
		# Bill each chosen cleaning Service (owner-price-list rate) as its own line; orders
		# with no priced service fall back to one line at the contract's flat cleaning tariff.
		services = frappe.get_all(
			"Cleaning Order Service", filters={"parent": r.name},
			fields=["cleaning_item", "item_name", "rate"], order_by="idx asc",
		)
		priced = [s for s in services if s.cleaning_item and s.rate and s.rate > 0]
		emit = (
			[(s.cleaning_item, s.item_name or s.cleaning_item, s.rate) for s in priced]
			if priced
			else [(CLEANING_ITEM, None, fallback_rate)]
		)
		for item_code, item_name, rate in emit:
			desc = f"Cleaning {r.name}" + (f" · {item_name}" if item_name else "")
			items.append({
				"container": r.container,
				"reference_doctype": "Cleaning Order",
				"reference_name": r.name,
				"description": desc,
				"service_date": getdate(r.cleaning_end),
				"amount": rate,
			})
	return items


def _storage_items(customer, from_date, to_date):
	"""Best-effort storage accrual: days a tank sat in the depot during the
	window (last gate-in -> gate-out / window end) x the Storage per Day tariff."""
	rate = resolve_tariff_rate(_active_contract(customer), STORAGE_ITEM)
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
		if m.to_status in ("Gate_In", "In_Depot", "Available") and gate_in is None:
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
	"Periodic Test": _periodic_items,
	"Storage": _storage_items,
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

	Runs monthly from the scheduler, so with finance off it simply does nothing rather
	than raising — nobody is there to read an error at 02:00 on the 1st.
	"""
	if not finance.is_enabled():
		return 0
	period, from_date, to_date = _period_window(period)
	customers = frappe.get_all(
		"Customer",
		filters={"is_tank_owner": 1},
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
