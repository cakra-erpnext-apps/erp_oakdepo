"""Monthly billing for Cash tank owners.

A Cash customer's accruing work — cleaning, M&R, periodic test, storage — has no booking to
be paid at, so once a month the scheduler bills it: one draft Sales Invoice per category, for
everything still unbilled up to the end of the previous month.

It runs the SAME collectors and the same invoice builder as **Ambil Tagihan**
(``consolidated_billing``), so a monthly invoice carries the same lines, locks and rollback
manifest as one raised by hand: every order it bills is marked billed, and cancelling or
discarding the draft gives them back. That is what keeps the two paths from billing one order
twice — a customer who moves from Cash to TOP finds last month's orders already spoken for.

It used to raise an intermediate OAK Monthly Invoice that someone had to submit before any
Sales Invoice existed, and which never marked its orders billed. That doctype stays for the
records it already holds; nothing creates new ones.

Invoked monthly by :func:`container_depot.tasks.generate_monthly_invoices`;
``generate_monthly_invoices(period="YYYY-MM")`` bills up to the end of that month instead.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_months, get_first_day, get_last_day, getdate, today

from container_depot import consolidated_billing as cb
from container_depot import finance

CATEGORIES = ("Cleaning", "M&R", "Periodic Test", "Storage")


def _period_window(period=None):
	"""Return (period_str, from_date, to_date). Defaults to the prior month."""
	if period:
		anchor = getdate(period + "-01")
	else:
		anchor = add_months(get_first_day(getdate(today())), -1)
	return anchor.strftime("%Y-%m"), get_first_day(anchor), get_last_day(anchor)


def generate_monthly_invoices(period=None):
	"""Bill every Cash tank owner's unbilled work up to the end of ``period``.

	Returns the number of draft Sales Invoices created. Idempotent: what one run billed is on
	that run's manifests, so the next run finds nothing left.

	The window starts at the depot's billing start date rather than at the first of the
	month, so work a missed run (or a finance switch that was off) left behind is picked up
	by the next one instead of being stranded.

	Runs from the scheduler, so with finance off it simply does nothing rather than raising —
	nobody is there to read an error at 02:00 on the 1st.
	"""
	if not finance.is_enabled():
		return 0
	period, _from, month_end = _period_window(period)
	from_d, to_d = cb._window(None, month_end)
	created = 0
	for customer in frappe.get_all("Customer", filters={"is_tank_owner": 1}, pluck="name"):
		if cb._is_postpaid(customer):
			continue  # TOP → billed on demand (Ambil Tagihan)
		for category in CATEGORIES:
			units = cb._collect(customer, (category,), from_d, to_d, accrual=True)
			if units:
				out = cb.bill_units(customer, units, f"Tagihan bulanan {category} s/d {period}")
				created += len(out["invoices"])
	if created:
		frappe.db.commit()
	return created
