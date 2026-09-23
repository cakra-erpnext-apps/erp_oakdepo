"""Monthly categorized invoice generation (Tank Owner billing).

Aggregates a prior month's depot activity into one OAK Monthly Invoice per
(customer, period, category, CURRENCY): Cleaning / M&R / Periodic Test / Storage. Each
invoice's ``on_submit`` then issues a native ERPNext Sales Invoice with PPN.

Currency is part of that key because an order prices each of its rows in the
currency that row's tariff line states — one cleaning order may carry both USD
and IDR work — and a Sales Invoice can only ever be raised in one. So every
builder returns its items tagged with a currency, and the generator splits them:
two currencies are two invoices, never one that reads dollars as rupiah. Same
rule ``consolidated_billing`` bills the TOP side by.

Invoked monthly by :func:`container_depot.tasks.generate_monthly_invoices`, but
``generate_monthly_invoices(period="YYYY-MM")`` can also be called directly.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_months, flt, get_first_day, get_last_day, getdate, today

from container_depot import finance, storage
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


def _contract_currency(customer):
	"""Currency of the customer's active Depot Contract — what an order's rows fall back to
	when they carry none of their own, and the company default when there is no contract."""
	contract = _active_contract(customer)
	ccy = frappe.db.get_value("Depot Contract", contract, "currency") if contract else None
	return (
		ccy
		or frappe.defaults.get_global_default("currency")
		or frappe.db.get_default("currency")
		or "IDR"
	)


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
def _work_order_items(customer, from_date, to_date, doctype, party_field, label, job_type=None):
	"""Work-order charges for the monthly scheduler — ONE lump line per order.

	Work orders (M&R) are a TOP arrangement in practice, so they are normally
	swept by ``consolidated_billing._work_order_lines`` instead, which bills item by item
	precisely so the Sales Invoice can charge labour off each ``item_code``. This monthly
	path only fires for a pure-Cash customer, and an OAK Monthly Invoice has no manhour
	machinery at all — so a charge landing here carries **parts only, no labour**. Kept as a
	safety net; if Cash work orders ever become real, this is what has to learn about labour.

	A completed order that cost nothing bills nothing — carrying it here would raise an
	OAK Monthly Invoice line worth 0 for work that was given away.

	One lump line PER CURRENCY: the order's own ``total_cost`` is a plain numeric roll-up
	that adds every row together whatever it is priced in, so the lines are summed off the
	used-item rows instead. Owner-rejected rows are left out, the same rule the order's own
	total and the TOP sweep use.
	"""
	lo, hi = _bounds(from_date, to_date)
	rows = frappe.get_all(
		doctype,
		filters={
			"status": "Completed", party_field: customer, "completion_date": ["between", [lo, hi]],
			**({"job_type": job_type} if job_type else {}),
		},
		fields=["name", "container", "completion_date"],
	)
	fallback = _contract_currency(customer)
	items = []
	for r in rows:
		by_ccy = {}
		for u in frappe.get_all(
			"Repair Used Item",
			filters={"parent": r.name, "parenttype": doctype},
			fields=["amount", "currency", "decision"],
		):
			if (u.decision or "Pending") == "Rejected":
				continue
			ccy = u.currency or fallback
			by_ccy[ccy] = by_ccy.get(ccy, 0) + flt(u.amount)
		for ccy, amount in sorted(by_ccy.items()):
			if amount <= 0:
				continue
			items.append({
				"container": r.container,
				"reference_doctype": doctype,
				"reference_name": r.name,
				"description": f"{label} {r.name}",
				"service_date": getdate(r.completion_date),
				"amount": amount,
				"currency": ccy,
			})
	return items


def _mr_items(customer, from_date, to_date):
	return _work_order_items(customer, from_date, to_date, "Repair Order", "principal", "M&R", "Repair")


def _periodic_items(customer, from_date, to_date):
	# Repair Order ber-job_type Periodic Test — kategorinya sendiri (container_depot/mr_scope.py).
	return _work_order_items(
		customer, from_date, to_date, "Repair Order", "principal", "Periodic Test", "Periodic Test"
	)


def _cleaning_items(customer, from_date, to_date):
	lo, hi = _bounds(from_date, to_date)
	fallback_rate = resolve_tariff_rate(_active_contract(customer), CLEANING_ITEM)
	fallback_ccy = _contract_currency(customer)
	rows = frappe.get_all(
		"Cleaning Order",
		filters={"status": "Completed", "cleaning_end": ["between", [lo, hi]]},
		fields=["name", "container", "cleaning_end"],
	)
	items = []
	for r in rows:
		if frappe.db.get_value("Container", r.container, "principal") != customer:
			continue
		# Bill each chosen cleaning Service (owner-price-list rate) as its own line; an order
		# that chose NO service falls back to one line at the contract's flat cleaning tariff.
		# An order that chose services and priced them all at zero is a free job — it bills
		# nothing, and the tariff is not substituted for that decision (the same rule
		# consolidated_billing._bills_something applies to the on-demand path).
		services = frappe.get_all(
			"Cleaning Order Service", filters={"parent": r.name},
			fields=["cleaning_item", "item_name", "quantity", "rate", "currency"], order_by="idx asc",
		)
		priced = [s for s in services if s.cleaning_item and s.rate and s.rate > 0]
		if priced:
			# Baris lama (sebelum kolom Qty ada) tidak punya qty — satu kali pakai.
			emit = [
				(
					s.item_name or s.cleaning_item,
					(flt(s.quantity) or 1) * flt(s.rate),
					s.currency or fallback_ccy,
				)
				for s in priced
			]
		elif not services and fallback_rate and fallback_rate > 0:
			emit = [(None, fallback_rate, fallback_ccy)]
		else:
			continue
		for item_name, amount, ccy in emit:
			desc = f"Cleaning {r.name}" + (f" · {item_name}" if item_name else "")
			items.append({
				"container": r.container,
				"reference_doctype": "Cleaning Order",
				"reference_name": r.name,
				"description": desc,
				"service_date": getdate(r.cleaning_end),
				"amount": amount,
				"currency": ccy,
			})
	return items


def _storage_items(customer, from_date, to_date):
	"""Best-effort storage accrual: days a tank sat in the depot during the
	window (last gate-in -> gate-out / window end) x the Storage per Day tariff."""
	rate = resolve_tariff_rate(_active_contract(customer), STORAGE_ITEM)
	if not rate:
		return []
	# Storage is priced by ONE contract tariff line, so it has one currency by construction.
	currency = _contract_currency(customer)
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
			"currency": currency,
		})
	return items


def _days_in_depot(container, from_date, to_date):
	"""Days the container was in the depot during [from_date, to_date].

	Delegates to the storage days engine so billing reads the same stay dates as the
	Storage Charges report — Gate Entry, else the EIR dates, else the status trail."""
	return storage.days_in_depot(container, getdate(from_date), getdate(to_date))


_BUILDERS = {
	"Cleaning": _cleaning_items,
	"M&R": _mr_items,
	"Periodic Test": _periodic_items,
	"Storage": _storage_items,
}


def create_monthly_invoice(customer, period, category, from_date, to_date, items, currency=None):
	"""Create a draft OAK Monthly Invoice in ONE currency. Skips empty sets and duplicates.

	``items`` carry a ``currency`` key for grouping (see :func:`generate_monthly_invoices`);
	it is not a column on the child row, so it is dropped before the rows are written.
	"""
	if not items:
		return None
	currency = currency or _contract_currency(customer)
	if frappe.db.exists(
		"OAK Monthly Invoice",
		{
			"customer": customer, "period": period, "category": category,
			"currency": currency, "docstatus": ["<", 2],
		},
	):
		return None
	doc = frappe.get_doc({
		"doctype": "OAK Monthly Invoice",
		"customer": customer,
		"period": period,
		"category": category,
		"currency": currency,
		"from_date": from_date,
		"to_date": to_date,
		"status": "Unpaid",
		"items": [{k: v for k, v in item.items() if k != "currency"} for item in items],
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
		default_ccy = _contract_currency(customer)
		for category in CATEGORIES:
			# One invoice per currency: a month's work may be priced in more than one, and a
			# Sales Invoice can only ever be raised in one of them.
			by_ccy = {}
			for item in _BUILDERS[category](customer, from_date, to_date):
				by_ccy.setdefault(item.get("currency") or default_ccy, []).append(item)
			for ccy in sorted(by_ccy):
				if create_monthly_invoice(
					customer, period, category, from_date, to_date, by_ccy[ccy], ccy
				):
					created += 1
	if created:
		frappe.db.commit()
	return created
