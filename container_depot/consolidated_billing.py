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

	**One unit per container**, like every other builder returns one unit per order. That is
	what makes a single tank tickable on its own in the billing preview; lumping every
	container into one unit would force the operator to take all the storage or none.
	Each source records the container's previous watermark so rollback can restore it."""
	rate = resolve_tariff_rate(_active_contract(customer), STORAGE_ITEM)
	if not rate or rate <= 0:
		return []
	containers = frappe.get_all("Container", filters={"principal": customer}, pluck="name")
	currency = _fallback_currency(customer)
	units = []
	for cname in containers:
		prev = frappe.db.get_value("Container", cname, "storage_billed_until")
		start = max(from_date, add_days(getdate(prev), 1)) if prev else from_date
		if start > to_date:
			continue
		days = _days_in_depot(cname, start, to_date)
		if days <= 0:
			continue
		units.append({
			"currency": currency,
			# Carry the item, like every other builder does. Without it the line fell through
			# to the generic depot service item, so storage revenue was indistinguishable from
			# cleaning or M&R in any per-item sales report — and the contract's manhour for it
			# was never stamped on the line.
			"lines": [{
				"item_code": STORAGE_ITEM,
				"description": f"Storage {cname} ({days}d)",
				"qty": days,
				"rate": rate,
			}],
			"sources": [{"storage": cname, "prev": str(prev) if prev else None}],
		})
	return units


# --------------------------------------------------------------------------- #
# Categories — the "sections" a user bills by.
#
# Each is one builder above. The operator picks any combination (Cleaning + M&R, or
# Storage alone, …) and a window; everything downstream — preview, fill, the report's
# selection — works off this registry rather than a hard-coded sweep.
# --------------------------------------------------------------------------- #
CATEGORIES = ("Booking", "Survey", "Cleaning", "M&R", "Periodic Test", "Storage")

# Bookings and Survey Orders carry their own ``payment_type``, so their TOP rows are
# billable for anyone. The rest accrue at the container-owner level with no per-order
# payment type, and are only swept for a postpaid customer — a pure-Cash customer's are
# the monthly scheduler's to bill, and sweeping them here too would double-charge.
_ACCRUAL_CATEGORIES = frozenset({"Cleaning", "M&R", "Periodic Test", "Storage"})

# Storage is deliberately absent: alone among the categories it has no order document to
# read, so it is built from plain dates rather than datetime bounds (see collect_units).
_BUILDERS = {
	"Booking": _booking_lines,
	"Survey": _survey_lines,
	"Cleaning": _cleaning_lines,
	"M&R": _mr_lines,
	"Periodic Test": _periodic_lines,
}

# Shared billing number across the per-currency invoices of one run (see _issue_group).
GROUP_FIELD = "depot_bill_group"


def _normalize_categories(categories):
	"""Accept a list, a JSON string (from the client) or None (= all) → ordered tuple."""
	if isinstance(categories, str):
		categories = json.loads(categories)
	if not categories:
		return CATEGORIES
	wanted = set(categories)
	unknown = wanted - set(CATEGORIES)
	if unknown:
		frappe.throw(_("Section tidak dikenal: {0}").format(", ".join(sorted(unknown))))
	# Keep CATEGORIES' order so invoice lines always come out in the same sequence.
	return tuple(c for c in CATEGORIES if c in wanted)


def _window(from_date, to_date):
	"""Resolve the bill window, clamped to the date the depot started charging.

	Without the floor a run with no ``from_date`` reaches back to 2000-01-01, so a site that
	operated for months before switching finance on would sweep its whole backlog into one
	invoice on the first click.

	The floor may legitimately push ``from_d`` past ``to_d`` — that is a site whose billing
	start date has not arrived yet, and it must bill *nothing* rather than raise. So only a
	window the **user** typed backwards is an error; callers read an inverted window as an
	empty one (see :func:`collect_units`).
	"""
	from_d = getdate(from_date) if from_date else getdate("2000-01-01")
	to_d = getdate(to_date) if to_date else getdate(today())
	if from_date and to_date and from_d > to_d:
		frappe.throw(_("Tanggal awal ({0}) melewati tanggal akhir ({1}).").format(from_d, to_d))
	floor = finance.start_date()
	if floor and from_d < floor:
		from_d = floor
	return from_d, to_d


def collect_units(customer, categories=None, from_date=None, to_date=None):
	"""Every unbilled charge unit for ``customer`` in the window, per chosen category.

	The one collector behind preview, fill and the report's selection — so what the operator
	is shown and what the invoice ends up carrying can never drift apart. Each unit is tagged
	with the category that produced it, which is what lets the preview group by section.

	Takes RAW dates and resolves the window itself. Callers that have already resolved one
	(preview / fill, which need the window for their own output) use :func:`_collect` instead —
	re-windowing an already-floored pair would read the floor's own output as a user error.
	"""
	return _collect(customer, _normalize_categories(categories), *_window(from_date, to_date))


def _collect(customer, cats, from_d, to_d):
	"""Collect units for an ALREADY-resolved window and category tuple."""
	if from_d > to_d:
		# The billing start date is still ahead of the window: nothing has become billable
		# yet. Not an error — the depot is simply operating before it charges.
		return []
	lo, hi = f"{from_d} 00:00:00", f"{to_d} 23:59:59"
	postpaid = _is_postpaid(customer)

	units = []
	for cat in cats:
		if cat in _ACCRUAL_CATEGORIES and not postpaid:
			continue
		got = (
			_storage_lines(customer, from_d, to_d)
			if cat == "Storage"
			else _BUILDERS[cat](customer, lo, hi)
		)
		for u in got:
			u["category"] = cat
		units += got
	return units


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


def _guard_billing(action):
	"""Common gate for every entry point that turns depot work into a receivable."""
	finance.require_enabled(action)
	# Creating receivables is limited to billing roles. Administrator / test runs bypass via
	# frappe.only_for. The billing roles (Commercial / Admin Ops / Management / Cashier /
	# Container Depot) were removed on 2026-08-05 pending a role redesign — until then only
	# System Manager may raise invoices. Widen this list again with the new roles.
	frappe.only_for(["System Manager"])


def _unit_key(u):
	"""Stable id for one collected unit — what the preview ticks and the fill filters on.

	Every builder returns one unit per source, so a unit is always exactly one order (or, for
	storage, one container). The key survives a re-collect because it is derived from the
	source document, not from position in the list.
	"""
	src = u["sources"][0]
	return f"Storage|{src['storage']}" if "storage" in src else f"{src['dt']}|{src['name']}"


def _unit_label(u):
	"""Human-readable name of what a unit charges for (an order number, or a container)."""
	src = u["sources"][0]
	return src["storage"] if "storage" in src else src["name"]


def _normalize_keys(keys):
	"""Accept a list, a JSON string (from the client) or None (= take everything)."""
	if isinstance(keys, str):
		keys = json.loads(keys)
	return set(keys) if keys else None


def _by_currency(units):
	"""Group units into ``{currency: {"lines": [...], "sources": [...]}}``.

	ERPNext invoices are single-currency — ``Sales Invoice Item`` has no currency of its
	own and its rate is always read in the header's — so charges in different currencies
	can never share one document. They become sibling invoices instead, tied together by
	a shared billing number (see :func:`_issue_group`).
	"""
	groups = {}
	for u in units:
		g = groups.setdefault(u["currency"], {"lines": [], "sources": []})
		g["lines"] += u["lines"]
		g["sources"] += u["sources"]
	return {ccy: g for ccy, g in groups.items() if g["lines"]}


def _stamp_sources(si, sources, to_d):
	"""Mark every swept source billed against ``si`` and record the rollback manifest."""
	for src in sources:
		if "storage" in src:
			frappe.db.set_value(
				"Container", src["storage"], "storage_billed_until", to_d, update_modified=False
			)
		else:
			_mark_billed(src["dt"], src["name"], si)
	frappe.db.set_value("Sales Invoice", si, MANIFEST_FIELD, json.dumps(sources), update_modified=False)


def _issue_group(invoices):
	"""Tie one run's per-currency invoices together under a single billing number.

	The customer is handed ONE bill; that it is several documents underneath is an ERPNext
	constraint, not something they should have to reconcile. The first invoice's name is the
	number, and the print format renders every member of the group as one PDF with a page
	per currency (see the OAK Invoice template).
	"""
	if not invoices:
		return None
	group = invoices[0]
	for si in invoices:
		frappe.db.set_value("Sales Invoice", si, GROUP_FIELD, group, update_modified=False)
	return group


@frappe.whitelist()
def preview_bill(customer, categories=None, from_date=None, to_date=None):
	"""What a bill run would pick up, WITHOUT creating anything — **one row per order**.

	Returns ``{"window", "sections": [{"category", "rows": [...]}], "total_orders"}`` where
	each row is ``{"key", "label", "detail", "currency", "amount"}``. The operator ticks the
	rows they want and the keys come back to :func:`fill_invoice`, so a run can be narrowed
	to individual orders rather than being all-or-nothing per section.

	Read-only: safe to call on every filter change.
	"""
	if not customer:
		frappe.throw(_("Customer wajib diisi."))
	cats = _normalize_categories(categories)
	from_d, to_d = _window(from_date, to_date)

	sections = {}
	for u in _collect(customer, cats, from_d, to_d):
		sec = sections.setdefault(u["category"], {"category": u["category"], "rows": []})
		sec["rows"].append({
			"key": _unit_key(u),
			"label": _unit_label(u),
			# What the line(s) actually say, so a row is judgeable without opening the order.
			"detail": "; ".join(ln.get("description") or "" for ln in u["lines"])[:180],
			"currency": u["currency"],
			"amount": sum(flt(ln.get("qty") or 1) * flt(ln.get("rate")) for ln in u["lines"]),
		})

	ordered = [sections[c] for c in CATEGORIES if c in sections]
	return {
		"customer": customer,
		"window": {"from_date": str(from_d), "to_date": str(to_d)},
		"sections": ordered,
		"total_orders": sum(len(s["rows"]) for s in ordered),
	}


def _rollback_and_discard(doc):
	"""Give back everything a generated draft took, then delete it.

	Emptying the invoice in place is not an option: ERPNext refuses to save a Sales Invoice
	with no items, so "clear the lines" can only mean "discard the document". That is also
	the honest model — a generated invoice IS its sweep, and a sweep that has been rolled
	back has nothing left to be.
	"""
	rollback_billed_sources(doc)
	# Drop the manifest first, or on_trash would roll the same sources back a second time —
	# by then they may already belong to the run that is replacing this one.
	frappe.db.set_value("Sales Invoice", doc.name, MANIFEST_FIELD, None, update_modified=False)
	frappe.delete_doc("Sales Invoice", doc.name, force=True, ignore_permissions=True)


@frappe.whitelist()
def fill_invoice(customer, categories=None, from_date=None, to_date=None, keys=None, sales_invoice=None):
	"""Run a bill: collect the chosen sections and turn them into draft Sales Invoices.

	``keys`` are the unit keys the operator ticked in the preview (see :func:`preview_bill`);
	omit them to bill everything the filter matches. Selection is applied to a FRESH collect
	rather than to whatever the preview returned, so an order that was billed or edited
	between preview and confirm is re-read rather than trusted from the client.

	``sales_invoice`` re-runs an existing generated draft **in place** — its previous sweep is
	rolled back first, so re-running after changing the filters never double-charges and never
	strands an order as billed against lines that are gone. Without it a fresh set is created.

	Returns ``{"invoices": [...], "group": "..."}``: one invoice per currency, all sharing a
	billing number. ``invoices`` is empty when the window holds nothing billable.
	"""
	if not customer:
		frappe.throw(_("Customer wajib diisi."))
	_guard_billing(_("Ambil Tagihan"))
	cats = _normalize_categories(categories)
	wanted = _normalize_keys(keys)
	from_d, to_d = _window(from_date, to_date)

	# Re-run: give back everything the previous run took before collecting again, or those
	# orders would be invisible to the collector (they are marked billed) and silently dropped.
	if sales_invoice:
		target = frappe.get_doc("Sales Invoice", sales_invoice)
		if target.docstatus != 0:
			frappe.throw(_("Hanya draft yang bisa di-generate ulang — batalkan invoice-nya dulu."))
		if target.customer != customer:
			frappe.throw(
				_("Invoice ini milik {0} — satu invoice hanya untuk satu customer.").format(target.customer)
			)
		_rollback_and_discard(target)

	units = _collect(customer, cats, from_d, to_d)
	if wanted is not None:
		units = [u for u in units if _unit_key(u) in wanted]
	groups = _by_currency(units)
	if not groups:
		return {"invoices": [], "group": None}

	created = []
	for ccy, g in groups.items():
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
		_stamp_sources(si, g["sources"], to_d)

	return {"invoices": created, "group": _issue_group(created)}


@frappe.whitelist()
def fill_invoice_from_orders(customer, orders):
	"""Bill an explicitly chosen set of orders — the Order Billing Status selection path.

	``orders`` is a list of ``{"doctype", "name"}``. Unlike :func:`fill_invoice` this bills
	exactly what was ticked rather than everything a filter matches, so the operator gets what
	they saw on screen. Storage cannot arrive here: it has no order document to tick, and is
	billed by section from the invoice form instead.
	"""
	if not customer:
		frappe.throw(_("Customer wajib diisi."))
	_guard_billing(_("Buat Invoice"))
	if isinstance(orders, str):
		orders = json.loads(orders)
	if not orders:
		frappe.throw(_("Tidak ada order yang dipilih."))

	# Same key vocabulary the invoice-form preview uses, so both selection paths filter a
	# fresh collect identically — a ticked order bills byte-for-byte like a filtered one.
	wanted = {f"{o['doctype']}|{o['name']}" for o in orders}
	units = [
		u for u in collect_units(customer, None, "2000-01-01", today()) if _unit_key(u) in wanted
	]
	if not units:
		frappe.throw(_("Order yang dipilih sudah ditagih atau tidak menagihkan apa pun."))

	groups = _by_currency(units)
	created = []
	to_d = getdate(today())
	for ccy, g in groups.items():
		si = invoicing.create_draft_sales_invoice(
			customer,
			g["lines"],
			due_days=30,
			remarks=f"Consolidated billing for {customer} · {len(wanted)} order dipilih · {ccy}",
			taxes_and_charges=invoicing.PPN_TEMPLATE,
			currency=ccy,
		)
		if not si:
			continue
		created.append(si)
		_stamp_sources(si, g["sources"], to_d)
	return {"invoices": created, "group": _issue_group(created)}


@frappe.whitelist()
def bill_customer(customer, from_date=None, to_date=None):
	"""Sweep every category for a customer into draft Sales Invoices — one per currency.

	Kept as the all-categories shorthand over :func:`fill_invoice`. Returns the list of
	created invoice names, as it always has.
	"""
	return fill_invoice(customer, None, from_date, to_date)["invoices"]


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
