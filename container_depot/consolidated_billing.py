"""On-demand consolidated billing for postpaid (TOP) customers.

A TOP customer's bookings — and their orders, cleaning, M&R and storage — accrue
*unbilled*. The depot triggers :func:`bill_customer` (manually, via the **OAK
Billing Run** doctype) to sweep everything unbilled in a date window into ONE
draft Sales Invoice (PPN applied) and mark each source billed so re-runs never
double-charge.

Pricing reuses the same tariff lookup as the per-transaction path; the category
shapes mirror :mod:`container_depot.monthly_invoicing` (whose helpers are reused).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today

from container_depot import invoicing
from container_depot.monthly_invoicing import _active_contract, _days_in_depot
from container_depot.pricing import resolve_tariff_rate


def _booking_lines(customer, lo, hi):
	"""Unbilled (no ``sales_invoice``) submitted bookings → lift-charge lines."""
	rows = frappe.get_all(
		"Isotank Booking",
		filters={
			"customer": customer,
			"docstatus": 1,
			"sales_invoice": ["is", "not set"],
			"creation": ["between", [lo, hi]],
		},
		fields=["name", "contract", "lift_type", "direction"],
	)
	lines, refs = [], []
	for r in rows:
		service = r.lift_type or ("Lift Off" if r.direction == "Tank In" else "Lift On")
		rate = resolve_tariff_rate(r.contract, service)
		if not rate or rate <= 0:
			continue
		qty = frappe.db.count("Isotank Booking Item", {"parent": r.name}) or 1
		lines.append({"description": f"Booking {r.name} · {service} · {qty} ctr", "qty": qty, "rate": rate})
		refs.append(("Isotank Booking", r.name))
	return lines, refs


def _cleaning_lines(customer, lo, hi):
	"""Completed, not-yet-billed cleaning for the customer's tanks (tariff-priced)."""
	rate = resolve_tariff_rate(_active_contract(customer), "Cleaning")
	if not rate or rate <= 0:
		return [], []
	rows = frappe.get_all(
		"Cleaning Order",
		filters={"status": "Completed", "cleaning_end": ["between", [lo, hi]], "sales_invoice": ["is", "not set"]},
		fields=["name", "container"],
	)
	lines, refs = [], []
	for r in rows:
		if frappe.db.get_value("Container", r.container, "principal") != customer:
			continue
		lines.append({"description": f"Cleaning {r.name}", "qty": 1, "rate": rate})
		refs.append(("Cleaning Order", r.name))
	return lines, refs


def _mr_lines(customer, lo, hi):
	"""Completed, Unbilled Repair Orders (stored cost)."""
	rows = frappe.get_all(
		"Repair Order",
		filters={
			"status": "Completed",
			"principal": customer,
			"billing_status": "Unbilled",
			"completion_date": ["between", [lo, hi]],
		},
		fields=["name", "total_cost"],
	)
	lines, refs = [], []
	for r in rows:
		if not r.total_cost or r.total_cost <= 0:
			continue
		lines.append({"description": f"M&R {r.name}", "qty": 1, "rate": r.total_cost})
		refs.append(("Repair Order", r.name))
	return lines, refs


def _storage_lines(customer, from_date, to_date):
	"""Storage days not yet billed (since each container's ``storage_billed_until``
	watermark) × the Storage-per-Day tariff. Returns (lines, containers_to_advance)."""
	rate = resolve_tariff_rate(_active_contract(customer), "Storage per Day")
	if not rate or rate <= 0:
		return [], []
	containers = frappe.get_all("Container", filters={"principal": customer}, pluck="name")
	lines, marks = [], []
	for cname in containers:
		billed_until = frappe.db.get_value("Container", cname, "storage_billed_until")
		start = max(from_date, add_days(getdate(billed_until), 1)) if billed_until else from_date
		if start > to_date:
			continue
		days = _days_in_depot(cname, start, to_date)
		if days <= 0:
			continue
		lines.append({"description": f"Storage {cname} ({days}d)", "qty": days, "rate": rate})
		marks.append(cname)
	return lines, marks


@frappe.whitelist()
def bill_customer(customer, from_date=None, to_date=None):
	"""Sweep a customer's unbilled bookings + orders + cleaning + M&R + storage in
	``[from_date, to_date]`` into ONE draft Sales Invoice (PPN applied).

	Returns the Sales Invoice name, or ``None`` if there is nothing to bill.
	Idempotent: every swept source is marked billed and skipped on re-run.
	"""
	if not customer:
		frappe.throw(_("Customer is required."))
	from_d = getdate(from_date) if from_date else getdate("2000-01-01")
	to_d = getdate(to_date) if to_date else getdate(today())
	lo, hi = f"{from_d} 00:00:00", f"{to_d} 23:59:59"

	lines, refs = [], []
	for builder in (_booking_lines, _cleaning_lines, _mr_lines):
		blines, brefs = builder(customer, lo, hi)
		lines += blines
		refs += brefs
	storage_lines, storage_marks = _storage_lines(customer, from_d, to_d)
	lines += storage_lines

	if not lines:
		return None

	si = invoicing.create_draft_sales_invoice(
		customer,
		lines,
		due_days=30,
		remarks=f"Consolidated billing for {customer} ({from_d} → {to_d})",
		taxes_and_charges=invoicing.PPN_TEMPLATE,
	)
	if not si:
		return None

	# Mark every swept source billed so it is never re-billed.
	for dt, name in refs:
		if dt == "Isotank Booking":
			frappe.db.set_value(dt, name, {"sales_invoice": si, "payment_status": "Invoiced"}, update_modified=False)
		elif dt == "Repair Order":
			frappe.db.set_value(dt, name, "billing_status", "Client Billed", update_modified=False)
		else:  # Cleaning Order
			frappe.db.set_value(dt, name, "sales_invoice", si, update_modified=False)
	for cname in storage_marks:
		frappe.db.set_value("Container", cname, "storage_billed_until", to_d, update_modified=False)

	return si
