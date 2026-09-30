"""Dummy unbilled orders for trying Pilih Order on a Sales Invoice with 30+ rows.

Dev only. One customer, ``DMYB Billing Co`` (Active contract: Both, NET 30, IDR, with a
Billing address), and 34 finished orders nobody has billed yet, spread over the last 60 days
so the date filter has something to narrow:

- 12 TOP Tank In bookings (Lift Off per tank; 3 of them in USD),
- 10 completed Cleaning Orders (3 mixing a USD and an IDR row, so they list twice),
- 8 completed M&R Repair Orders and 4 completed Periodic Tests (with manhour tariffs).

Everything carries the ``DMYB`` marker (customer, tank numbers ``DMBU…``, DO reference and the
orders' Reff Doc), and
``clear`` removes exactly that — including any invoice or payment raised for the customer
while trying it out — without leaving Deleted Document tombstones.

    bench --site oakdepo.localhost execute container_depot.dummy_billing.seed
    bench --site oakdepo.localhost execute container_depot.dummy_billing.clear
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, today

CUSTOMER = "DMYB Billing Co"
DEPOT = "OAK1"
LIFT_OFF = "Lift Off"
CLEANING = ["Standard Clean", "Steam Cleaning / Wash", "Flushing", "Foodgrade Clean"]
REPAIRS = [
	"Renew Relief Valve Envelope Gasket",
	"Footvalve - Dismantle & Clean",
	"Butterfly Valve - Dismantle & Clean",
	"Renew Swingbolt - Standard Type",
]
PERIODIC = "2.5 Years Periodic Test"


def seed():
	frappe.set_user("Administrator")
	clear()
	_customer()
	branch = frappe.db.get_value("Depot", DEPOT, "branch")
	n = 0

	def tank():
		nonlocal n
		n += 1
		return f"DMBU{n:07d}"

	for i in range(12):
		usd = i % 4 == 3
		tanks = [tank() for _ in range(1 + i % 3)]
		b = frappe.get_doc({
			"doctype": "Container Booking",
			"direction": "Tank In",
			"customer": CUSTOMER,
			"contract": _contract(),
			"payment_type": "TOP",
			"depot": DEPOT,
			"branch": branch,
			"do_reference": f"DMYB/DO/{2600 + i}",
			"items": [{"container_no": t} for t in tanks],
			"charges": [{"item": LIFT_OFF, "qty": len(tanks), "rate": 15 if usd else 250000}],
		})
		b.flags.ignore_mandatory = True
		b.insert(ignore_permissions=True)
		b.submit()
		if usd:
			frappe.db.set_value("Container Booking", b.name, "currency", "USD", update_modified=False)
		# The pick list dates a booking by its creation.
		frappe.db.sql(
			"update `tabContainer Booking` set creation = %s where name = %s",
			(f"{_day(i * 5)} 09:00:00", b.name),
		)

	for i in range(10):
		rows = [{"cleaning_item": CLEANING[i % 4], "quantity": 1, "rate": 750000 + 50000 * i,
			"currency": "IDR", "manhour_rate": 50000}]
		if i % 3 == 2:
			rows.append({"cleaning_item": "Residue Disposal", "quantity": 1, "rate": 35, "currency": "USD",
				"manhour_rate": 3})
		co = frappe.get_doc({"doctype": "Cleaning Order", "container": _tank(tank()), "reff_doc": f"DMYB/CLN/{300 + i}",
			"cleaning_services": rows})
		co.flags.ignore_mandatory = True
		co.insert(ignore_permissions=True)
		frappe.db.set_value("Cleaning Order", co.name, {"status": "Completed", "cleaning_end": _day(i * 6 + 1)},
			update_modified=False)

	for i in range(12):
		periodic = i >= 8
		items = [{"item": PERIODIC, "quantity": 1, "item_rate": 1500000, "currency": "IDR", "manhour_rate": 0}] if periodic else [
			{"item": REPAIRS[(i + k) % 4], "quantity": 1 + k, "item_rate": 125000 * (k + 1), "currency": "IDR",
				"manhour_rate": 60000}
			for k in range(1 + i % 3)
		]
		ro = frappe.get_doc({
			"doctype": "Repair Order", "container": _tank(tank()), "status": "Draft", "billing_status": "Unbilled",
			"reff_doc": f"DMYB/{'PT' if periodic else 'MR'}/{400 + i}", "used_items": items,
		})
		ro.flags.ignore_mandatory = True
		ro.insert(ignore_permissions=True)
		frappe.db.set_value("Repair Order", ro.name, {
			"status": "Completed", "billing_status": "Unbilled", "principal": CUSTOMER,
			"completion_date": _day(i * 5 + 2), "job_type": "Periodic Test" if periodic else "Repair",
		}, update_modified=False)

	frappe.db.commit()
	print(f"seeded 34 orders for {CUSTOMER} on {n} DMBU tanks")


def clear():
	frappe.set_user("Administrator")
	tanks = frappe.get_all("Container", filters={"container_no": ["like", "DMBU%"]}, pluck="name")
	bookings = frappe.get_all("Container Booking", filters={"customer": CUSTOMER}, pluck="name")
	cleanings = frappe.get_all("Cleaning Order", filters={"container": ["in", tanks or [""]]}, pluck="name")
	repairs = frappe.get_all("Repair Order", filters={"container": ["in", tanks or [""]]}, pluck="name")
	contracts = frappe.get_all("Depot Contract", filters={"customer": CUSTOMER}, pluck="name")
	invoices = frappe.get_all("Sales Invoice", filters={"customer": CUSTOMER}, pluck="name")
	payments = frappe.get_all("Payment Entry", filters={"party": CUSTOMER}, pluck="name")

	def wipe(dt, names, children=()):
		if not names:
			return
		for child in children:
			frappe.db.delete(child, {"parent": ["in", names]})
		frappe.db.delete(dt, {"name": ["in", names]})

	for voucher in invoices + payments:
		for ledger in ("GL Entry", "Payment Ledger Entry"):
			frappe.db.delete(ledger, {"voucher_no": voucher})
	wipe("Payment Entry", payments, ("Payment Entry Reference", "Payment Entry Deduction", "Payment Entry Line"))
	wipe("Sales Invoice", invoices, ("Sales Invoice Item", "Sales Taxes and Charges", "Payment Schedule",
		"Item Wise Tax Detail", "Sales Invoice Advance", "Sales Invoice Payment"))
	wipe("Booking Code", frappe.get_all("Booking Code", filters={"booking": ["in", bookings or [""]]}, pluck="name"))
	wipe("Container Booking", bookings, ("Container Booking Item", "Container Booking Charge"))
	wipe("Cleaning Order", cleanings, ("Cleaning Order Service",))
	wipe("Repair Order", repairs, ("Repair Used Item",))
	for dt in ("Container Activity", "Container Movement", "Storage Charge", "Leak Check"):
		if tanks and frappe.db.exists("DocType", dt) and frappe.db.has_column(dt, "container"):
			frappe.db.delete(dt, {"container": ["in", tanks]})
	wipe("Container", tanks)
	wipe("Depot Contract", contracts, ("Tariff Rate",))
	docs = bookings + cleanings + repairs + contracts + invoices + payments
	if docs:
		frappe.db.delete("Notification Log", {"document_name": ["in", docs]})
	frappe.db.delete("Notification Log", {"subject": ["like", f"%{CUSTOMER}%"]})
	addresses = frappe.get_all("Dynamic Link", filters={"link_doctype": "Customer", "link_name": CUSTOMER,
		"parenttype": "Address"}, pluck="parent")
	wipe("Address", addresses, ("Dynamic Link",))
	wipe("Customer", frappe.get_all("Customer", filters={"name": CUSTOMER}, pluck="name"))
	frappe.db.commit()
	print(f"cleared {len(bookings)} bookings, {len(cleanings)} cleanings, {len(repairs)} repairs, "
		f"{len(invoices)} invoices, {len(tanks)} tanks")


def _day(days_ago):
	return add_days(today(), -min(days_ago, 60))


def _tank(no):
	return frappe.get_doc({
		"doctype": "Container", "container_no": no, "container_type": "ISO Tank",
		"status": "In_Depot", "depot": DEPOT, "principal": CUSTOMER,
	}).insert(ignore_permissions=True).name


def _contract():
	return frappe.db.get_value("Depot Contract", {"customer": CUSTOMER, "status": "Active"}, "name")


def _customer():
	frappe.get_doc({
		"doctype": "Customer", "customer_name": CUSTOMER, "customer_type": "Company",
		"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
		"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
	}).insert(ignore_permissions=True)
	frappe.get_doc({
		"doctype": "Address", "address_title": CUSTOMER, "address_type": "Billing",
		"address_line1": "Jl. Dummy Tagihan No. 1", "city": "Surabaya", "country": "Indonesia",
		"is_primary_address": 1, "links": [{"link_doctype": "Customer", "link_name": CUSTOMER}],
	}).insert(ignore_permissions=True)
	tariff = [LIFT_OFF, "Lift On", "Residue Disposal", PERIODIC] + CLEANING + REPAIRS
	frappe.get_doc({
		"doctype": "Depot Contract", "customer": CUSTOMER, "currency": "IDR", "status": "Active",
		"payment_type": "Both", "payment_terms": "NET 30", "credit_limit": 10_000_000_000,
		"valid_from": add_days(today(), -90), "valid_to": add_days(today(), 365),
		"tariff_lines": [{"item": item, "rate": 250000, "manhour_rate": 50000} for item in tariff],
	}).insert(ignore_permissions=True)
