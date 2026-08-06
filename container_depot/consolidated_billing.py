"""On-demand consolidated billing for postpaid (TOP) customers.

A TOP customer's charges — TOP bookings, TOP survey orders, and their cleaning,
M&R, periodic tests and storage — accrue *unbilled*. The depot triggers :func:`bill_customer`
(the **Generate Invoice** button on the *Order Billing Status* report: pick a
customer + optional window) to sweep everything unbilled into draft Sales
Invoices (PPN applied) and mark each source billed so re-runs never double-charge.

**One draft Sales Invoice per currency.** A customer may transact in more than one
currency (e.g. USD bookings + IDR surveys). ERPNext invoices are single-currency,
so charges are grouped by their order's currency and each currency gets its own
draft invoice, billed in that currency (value-as-is, conversion_rate 1). Never
force everything onto the company default (IDR) — that mis-states USD charges.

**Reversible.** Each generated invoice is stamped with a rollback manifest
(``depot_billed_sources``) of the orders it swept. Discarding (``on_trash``) or
cancelling (``on_cancel``) the invoice rolls every source back to un-invoiced, so
the customer's orders return to exactly the pre-generate state and can be
generated again (picking up any new orders). Because the manifest also marks the
invoice as *generated*, its line items are frozen — you cannot delete/edit lines
(:func:`protect_consolidated_items`); to change what is billed, fix the source
order and rollback + re-generate.

Only **TOP** charges are swept. Bookings and Survey Orders carry a per-order
``payment_type`` — Cash ones settle at the transaction and are skipped here.
Cleaning / M&R / Periodic Test / Storage have no per-order payment type; they accrue at the
container-owner level and are only swept when the customer is postpaid
(``_is_postpaid``), otherwise the monthly scheduler bills them and sweeping here
too would double-charge.

Each builder returns a list of **units** — ``{"currency", "lines", "sources"}`` —
where ``lines`` are the invoice-line dicts for one source and ``sources`` are the
rollback descriptors (an order ``{"dt", "name"}`` or a storage container
``{"storage", "prev"}``). :func:`bill_customer` groups units by currency.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, today

from container_depot import finance, invoicing
from container_depot.monthly_invoicing import _active_contract, _days_in_depot, _is_postpaid
from container_depot.pricing import CLEANING_ITEM, STORAGE_ITEM, resolve_tariff_rate

MANIFEST_FIELD = "depot_billed_sources"


def _default_currency():
	return (
		frappe.defaults.get_global_default("currency")
		or frappe.db.get_default("currency")
		or "IDR"
	)


def _fallback_currency(customer):
	"""Currency to use when a source doc has none — the customer's active Depot
	Contract currency (the tariff/price-list currency), else the company default."""
	contract = _active_contract(customer)
	ccy = frappe.db.get_value("Depot Contract", contract, "currency") if contract else None
	return ccy or _default_currency()


def _booking_lines(customer, lo, hi):
	"""Unbilled (no ``sales_invoice``) submitted **TOP** bookings → one unit per booking,
	carrying every charge line the booking priced.

	Cash bookings settle at the booking (they carry their own paid invoice), so only
	``payment_type = TOP`` bookings accrue for consolidated billing. A booking with no
	charges bills nothing and is skipped — that is a deliberate free booking, not a gap to
	fill from the tariff. (Before charges existed this re-derived a single lift rate from
	the contract tariff, which could disagree with what the booking itself showed.)"""
	rows = frappe.get_all(
		"Container Booking",
		filters={
			"customer": customer,
			"payment_type": "TOP",
			"docstatus": 1,
			"sales_invoice": ["is", "not set"],
			"creation": ["between", [lo, hi]],
		},
		fields=["name", "currency"],
	)
	fallback = _fallback_currency(customer)
	units = []
	for r in rows:
		charges = frappe.get_all(
			"Container Booking Charge",
			filters={"parent": r.name, "parenttype": "Container Booking"},
			fields=["item", "item_name", "qty", "rate"],
			order_by="idx asc",
		)
		lines = [
			{
				"item_code": c.item,
				"description": f"Booking {r.name} · {c.item_name or c.item}",
				"qty": c.qty or 1,
				"rate": c.rate,
			}
			for c in charges
			if c.rate and c.rate > 0
		]
		if not lines:
			continue
		units.append({
			"currency": r.currency or fallback,
			"lines": lines,
			"sources": [{"dt": "Container Booking", "name": r.name}],
		})
	return units


def _cleaning_lines(customer, lo, hi):
	"""Completed, not-yet-billed cleaning for the customer's tanks.

	Each cleaning Service chosen on an order (``cleaning_services``) becomes its own invoice
	line, billed at the rate locked from the owner's Price List at cleaning time. Orders with
	no priced service fall back to ONE line at the contract's flat ``CLEANING_ITEM`` tariff."""
	fallback_rate = resolve_tariff_rate(_active_contract(customer), CLEANING_ITEM)
	fallback_ccy = _fallback_currency(customer)
	rows = frappe.get_all(
		"Cleaning Order",
		filters={"status": "Completed", "cleaning_end": ["between", [lo, hi]], "sales_invoice": ["is", "not set"]},
		fields=["name", "container", "currency"],
	)
	units = []
	for r in rows:
		if frappe.db.get_value("Container", r.container, "principal") != customer:
			continue
		services = frappe.get_all(
			"Cleaning Order Service", filters={"parent": r.name},
			fields=["cleaning_item", "item_name", "rate"], order_by="idx asc",
		)
		priced = [s for s in services if s.cleaning_item and s.rate and s.rate > 0]
		lines = []
		if priced:
			for s in priced:
				lines.append({
					"item_code": s.cleaning_item,
					"description": f"Cleaning {r.name} · {s.item_name or s.cleaning_item}",
					"qty": 1, "rate": s.rate,
				})
		elif fallback_rate and fallback_rate > 0:
			lines.append({"item_code": CLEANING_ITEM, "description": f"Cleaning {r.name}", "qty": 1, "rate": fallback_rate})
		if not lines:
			continue
		units.append({
			"currency": r.currency or fallback_ccy,
			"lines": lines,
			"sources": [{"dt": "Cleaning Order", "name": r.name}],
		})
	return units


# Work orders: a completed job carrying a table of used items, billed one invoice line per
# item. M&R and the Periodic Test are the same thing to accounting — the tank is worked on,
# parts and services are consumed, the owner is charged — and differ only in which work it
# was. So they are billed by one function and told apart by a label and a party field.
_WORK_ORDERS = (
	{
		"doctype": "Repair Order",
		"child": "Repair Used Item",
		# M&R records the tank's owner and always bills them.
		"party_field": "principal",
		"label": "M&R",
	},
	{
		"doctype": "Periodic Test Order",
		"child": "Periodic Used Item",
		# The periodic test carries an explicit ``billed_to`` (defaulted to the owner in
		# validate, but overridable), so the bill follows it rather than the owner.
		"party_field": "billed_to",
		"label": "Periodic Test",
	},
)


# Both carry billing_status + a sales_invoice back-link, so _mark_billed / _unmark_billed
# treat them as one kind rather than naming each doctype.
_WORK_ORDER_DOCTYPES = frozenset(spec["doctype"] for spec in _WORK_ORDERS)


def _work_order_lines(customer, lo, hi, spec):
	"""Completed, Unbilled work orders of one kind — **one invoice line per used item**.

	Billing item by item (rather than one lump "M&R RO-xxx" line) is what lets the invoice
	charge labour: :func:`invoicing.create_draft_sales_invoice` stamps each line with the
	manhour the customer's contract books for that ``item_code``, and ``apply_manhour_charge``
	totals them once in the header. A lump line carries no item_code and would book zero
	hours — which is exactly why the order itself no longer costs labour (see
	``RepairOrder.calculate_totals``).

	Owner-rejected lines are excluded, the same rule the order's own total uses. A line whose
	part is free (rate 0) is still billed: it may carry nothing but labour.
	"""
	rows = frappe.get_all(
		spec["doctype"],
		filters={
			"status": "Completed",
			spec["party_field"]: customer,
			"billing_status": "Unbilled",
			"completion_date": ["between", [lo, hi]],
		},
		fields=["name"],
	)
	fallback_ccy = _fallback_currency(customer)
	units = []
	for r in rows:
		used = frappe.get_all(
			spec["child"],
			filters={"parent": r.name, "parenttype": spec["doctype"]},
			fields=["item", "item_name", "quantity", "item_rate", "currency", "decision"],
			order_by="idx asc",
		)
		lines, currencies = [], set()
		for u in used:
			if not u.item or (u.decision or "Pending") == "Rejected":
				continue
			lines.append({
				"item_code": u.item,
				"description": f"{spec['label']} {r.name} · {u.item_name or u.item}",
				"qty": flt(u.quantity) or 1,
				"rate": flt(u.item_rate),
			})
			if u.currency:
				currencies.add(u.currency)
		if not lines:
			continue
		units.append({
			# An order can only be linked to ONE invoice (``_mark_billed`` writes a single
			# sales_invoice), so a mixed-currency order is billed whole in the customer's
			# currency rather than split across two invoices it could not both point at.
			"currency": currencies.pop() if len(currencies) == 1 else fallback_ccy,
			"lines": lines,
			"sources": [{"dt": spec["doctype"], "name": r.name}],
		})
	return units


def _mr_lines(customer, lo, hi):
	"""Completed, Unbilled Repair Orders (see :func:`_work_order_lines`)."""
	return _work_order_lines(customer, lo, hi, _WORK_ORDERS[0])


def _periodic_lines(customer, lo, hi):
	"""Completed, Unbilled Periodic Test Orders (see :func:`_work_order_lines`)."""
	return _work_order_lines(customer, lo, hi, _WORK_ORDERS[1])


def _survey_lines(customer, lo, hi):
	"""Unbilled (no ``sales_invoice``) submitted **TOP** Survey Orders billed to the
	customer (``paid_to``) → one line per priced charge row.

	Cash surveys raise their own draft invoice at submit and are skipped here."""
	rows = frappe.get_all(
		"Survey Order",
		filters={
			"paid_to": customer,
			"payment_type": "TOP",
			"docstatus": 1,
			"sales_invoice": ["is", "not set"],
			"creation": ["between", [lo, hi]],
		},
		fields=["name", "currency"],
	)
	fallback = _fallback_currency(customer)
	units = []
	for row in rows:
		charges = frappe.get_all(
			"Survey Order Charge", filters={"parent": row.name},
			fields=["item", "price", "container_no", "container", "survey_date"], order_by="idx asc",
		)
		lines = []
		for c in charges:
			if not c.item or flt(c.price) <= 0:
				continue
			ref = c.container_no or c.container or ""
			desc = f"Survey {row.name}" + (f" · {ref}" if ref else "")
			lines.append({"item_code": c.item, "description": desc, "qty": 1, "rate": flt(c.price)})
		if not lines:
			continue
		units.append({
			"currency": row.currency or fallback,
			"lines": lines,
			"sources": [{"dt": "Survey Order", "name": row.name}],
		})
	return units


def _storage_lines(customer, from_date, to_date):
	"""Storage days not yet billed (since each container's ``storage_billed_until``
	watermark) × the Storage-per-Day tariff (contract currency).

	Returns a list of 0 or 1 unit; each storage source records the container's
	previous watermark so rollback can restore it."""
	rate = resolve_tariff_rate(_active_contract(customer), STORAGE_ITEM)
	if not rate or rate <= 0:
		return []
	containers = frappe.get_all("Container", filters={"principal": customer}, pluck="name")
	lines, sources = [], []
	for cname in containers:
		prev = frappe.db.get_value("Container", cname, "storage_billed_until")
		start = max(from_date, add_days(getdate(prev), 1)) if prev else from_date
		if start > to_date:
			continue
		days = _days_in_depot(cname, start, to_date)
		if days <= 0:
			continue
		lines.append({"description": f"Storage {cname} ({days}d)", "qty": days, "rate": rate})
		sources.append({"storage": cname, "prev": str(prev) if prev else None})
	if not lines:
		return []
	return [{"currency": _fallback_currency(customer), "lines": lines, "sources": sources}]


def _mark_billed(dt, name, si):
	"""Mark one swept order billed against its currency's Sales Invoice."""
	if dt == "Container Booking":
		frappe.db.set_value(dt, name, {"sales_invoice": si, "payment_status": "Invoiced"}, update_modified=False)
	elif dt in _WORK_ORDER_DOCTYPES:
		frappe.db.set_value(dt, name, {"billing_status": "Client Billed", "sales_invoice": si}, update_modified=False)
	elif dt == "Survey Order":
		# Link the (draft) SI; the Sales Invoice → Survey Order bridge (hooks.doc_events)
		# advances invoice_status to Unpaid/Paid once it is submitted & settled.
		frappe.db.set_value(dt, name, {"sales_invoice": si, "invoice_status": "Draft"}, update_modified=False)
	elif dt == "Cleaning Order":
		frappe.db.set_value(dt, name, "sales_invoice", si, update_modified=False)


def _unmark_billed(dt, name):
	"""Reverse :func:`_mark_billed` — return the order to its pre-generate, un-invoiced
	state so it is billable again."""
	if not frappe.db.exists(dt, name):
		return
	if dt == "Container Booking":
		frappe.db.set_value(dt, name, {"sales_invoice": None, "payment_status": "Unpaid"}, update_modified=False)
	elif dt in _WORK_ORDER_DOCTYPES:
		frappe.db.set_value(dt, name, {"billing_status": "Unbilled", "sales_invoice": None}, update_modified=False)
	elif dt == "Survey Order":
		frappe.db.set_value(dt, name, {"sales_invoice": None, "invoice_status": "Not Invoiced"}, update_modified=False)
	elif dt == "Cleaning Order":
		frappe.db.set_value(dt, name, "sales_invoice", None, update_modified=False)


@frappe.whitelist()
def bill_customer(customer, from_date=None, to_date=None):
	"""Sweep a customer's unbilled TOP bookings + surveys + cleaning + M&R + periodic tests + storage
	in ``[from_date, to_date]`` into draft Sales Invoices — **one per currency** (PPN
	applied), each billed in its own currency, each stamped with a rollback manifest.

	Returns the list of created Sales Invoice names (``[]`` when there is nothing to
	bill). Idempotent: every swept source is marked billed and skipped on re-run, so a
	re-generate after a rollback resyncs with the customer's current orders.
	"""
	if not customer:
		frappe.throw(_("Customer is required."))
	finance.require_enabled(_("Generate Invoice"))
	# Guarded entry point: creating receivables is limited to billing roles. Called
	# from the Order Billing Status report's "Generate Invoice" button (whitelisted).
	# Administrator / test runs bypass via frappe.only_for.
	# The billing roles (Commercial / Admin Ops / Management / Cashier / Container Depot)
	# were removed on 2026-08-05 pending a role redesign — until then only System Manager
	# may raise invoices. Widen this list again with the new roles.
	frappe.only_for(["System Manager"])
	from_d = getdate(from_date) if from_date else getdate("2000-01-01")
	to_d = getdate(to_date) if to_date else getdate(today())
	# Never bill behind the date the depot started charging. Without this, a site that ran
	# operations-only for months and then switched finance on would sweep the whole backlog
	# into one invoice on the first click.
	floor = finance.start_date()
	if floor and from_d < floor:
		from_d = floor
	lo, hi = f"{from_d} 00:00:00", f"{to_d} 23:59:59"

	units = []
	# Per-order TOP charges: bookings + survey orders carry their own payment_type, so
	# these are swept for any customer (a Both/Cash customer can still book/survey TOP).
	for builder in (_booking_lines, _survey_lines):
		units += builder(customer, lo, hi)
	# Contract-level accruals (cleaning / M&R / storage) have no per-order payment type.
	# Only sweep them for postpaid (TOP / Both) customers — a pure-Cash customer's are
	# billed by the monthly scheduler, so sweeping here too would double-charge.
	if _is_postpaid(customer):
		for builder in (_cleaning_lines, _mr_lines, _periodic_lines):
			units += builder(customer, lo, hi)
		units += _storage_lines(customer, from_d, to_d)

	if not units:
		return []

	# Group charges by currency → one draft Sales Invoice per currency.
	groups = {}
	for u in units:
		g = groups.setdefault(u["currency"], {"lines": [], "sources": []})
		g["lines"] += u["lines"]
		g["sources"] += u["sources"]

	created = []
	for ccy, g in groups.items():
		if not g["lines"]:
			continue
		si = invoicing.create_draft_sales_invoice(
			customer,
			g["lines"],
			due_days=30,
			remarks=f"Consolidated billing for {customer} ({from_d} → {to_d}) · {ccy}",
			taxes_and_charges=invoicing.PPN_TEMPLATE,
			currency=ccy,
		)
		if not si:
			continue
		created.append(si)
		for src in g["sources"]:
			if "storage" in src:
				frappe.db.set_value("Container", src["storage"], "storage_billed_until", to_d, update_modified=False)
			else:
				_mark_billed(src["dt"], src["name"], si)
		# Stamp the rollback manifest so discard/cancel can restore these sources.
		frappe.db.set_value("Sales Invoice", si, MANIFEST_FIELD, json.dumps(g["sources"]), update_modified=False)

	return created


# --------------------------------------------------------------------------- #
# Sales Invoice bridges (hooks.doc_events) — every handler is a no-op unless the
# invoice carries a depot billed-sources manifest, so ordinary ERPNext invoices
# (and the per-transaction Cash booking/survey invoices, which never set it) are
# untouched.
# --------------------------------------------------------------------------- #
def _manifest(doc):
	raw = doc.get(MANIFEST_FIELD) if hasattr(doc, "get") else getattr(doc, MANIFEST_FIELD, None)
	if not raw:
		return None
	try:
		return json.loads(raw)
	except Exception:
		return None


def rollback_billed_sources(doc, method=None):
	"""on_trash / on_cancel: roll every order swept into this consolidated invoice
	back to un-invoiced (clear links, reset statuses, restore storage watermark), so
	the customer's orders return to the pre-generate state and can be generated again.

	On ``on_trash`` this runs BEFORE Frappe's link-integrity check, so clearing the
	order→invoice links also unblocks the discard."""
	sources = _manifest(doc)
	if not sources:
		return
	for src in sources:
		if "storage" in src:
			prev = src.get("prev")
			frappe.db.set_value(
				"Container", src["storage"], "storage_billed_until",
				getdate(prev) if prev else None, update_modified=False,
			)
		else:
			_unmark_billed(src.get("dt"), src.get("name"))
	# On cancel the invoice survives (docstatus 2); clear its manifest so a later delete
	# does not roll back a second time (the orders may have been re-generated by then).
	if method == "on_cancel":
		doc.db_set(MANIFEST_FIELD, None, update_modified=False)


def protect_consolidated_items(doc, method=None):
	"""validate: a generated (consolidated) invoice's line items may not be **deleted**
	by hand — the invoice mirrors its source orders; to drop a charge, fix the order then
	rollback + re-generate.

	Detection is by child-row name (a removed generated row disappears from ``items``),
	so this never trips on ERPNext's own recompute or on submit/payment (those keep the
	same rows) — it only blocks an actual row deletion. No-op on the programmatic
	creation itself (no prior version) and on any invoice without a manifest."""
	if not _manifest(doc):
		return
	before = doc.get_doc_before_save()
	if not before:
		return  # first insert (bill_customer builds the lines) — allow
	kept = {r.name for r in (doc.items or []) if r.name}
	removed = [r for r in (before.items or []) if r.name and r.name not in kept]
	if removed:
		frappe.throw(
			_(
				"Faktur ini dibuat lewat Generate — item tidak boleh dihapus. "
				"Perbaiki order sumbernya lalu rollback (batalkan) & generate ulang."
			)
		)
