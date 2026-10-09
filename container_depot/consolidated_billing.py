"""On-demand consolidated billing for postpaid (TOP) customers.

A TOP customer's charges — TOP bookings and their cleaning, M&R and storage —
accrue *unbilled*. The depot triggers :func:`bill_customer`
(the **Generate Invoice** button on the *Order Billing Status* report: pick a
customer + optional window) to sweep everything unbilled into draft Sales
Invoices (PPN applied) and mark each source billed so re-runs never double-charge.

**Currency: one run, one invoice, one currency.** A customer may transact in more than
one currency (e.g. USD bookings + IDR cleaning). Every invoice line keeps the currency and
price its order states, and the run bills everything in ONE currency — the others converted
through their kurs to IDR, the ledger's currency (:func:`bill_units`). Runs used to be able
to raise one invoice per currency instead, tied by ``depot_bill_group``; the user dropped
that (2026-09-28) because two invoices for one bill were easy to get wrong. Old groups still
print as one PDF.

**Reversible.** Each generated invoice is stamped with a rollback manifest
(``depot_billed_sources``) of the orders it swept. Discarding (``on_trash``) or
cancelling (``on_cancel``) the invoice rolls every source back to un-invoiced, so
the customer's orders return to exactly the pre-generate state and can be
generated again (picking up any new orders). Because the manifest also marks the
invoice as *generated*, the lines it billed are locked — item, qty, price and currency
cannot be edited or deleted (:func:`protect_consolidated_items`); to change what is
billed, fix the source order and rollback + re-generate. Hand-added lines stay free.

Only **TOP** charges are swept. Bookings carry a per-order
``payment_type`` — Cash ones settle at the transaction and are skipped here.
Cleaning / M&R / Storage have no per-order payment type; they accrue at the
container-owner level and are only swept here when the customer is postpaid
(``_is_postpaid``); a Cash customer's are billed once a month by
``monthly_invoicing``, which runs these same builders over the month.

Each builder returns a list of **units** — ``{"currency", "lines", "sources"}`` —
where ``lines`` are the invoice-line dicts for one source and ``sources`` are the
rollback descriptors (an order ``{"dt", "name", "currency"}`` or a storage visit
``{"storage_charge", "prev", "to"}``). :func:`bill_units` groups them into invoices.

**An order may carry more than one currency.** A cleaning order, an M&R or a booking
prices each of its rows in the currency its own tariff line states, so one order can carry
both USD and IDR work. Such an order produces one unit PER CURRENCY. A run normally bills
both onto its one invoice, but the preview lets either be ticked alone, and older invoices
were split per currency — so what has already been billed is a per-(order, currency) fact,
read back off the live manifests (:func:`_billed_pairs`) rather than off the order's
``sales_invoice`` link: the link can only name one document, so it says "this order is on
an invoice", not "this order is settled".
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, today

from container_depot import finance, invoicing, pricing, pricing_model, storage

MANIFEST_FIELD = "depot_billed_sources"


def _fallback_currency(customer):
	"""Currency for a source row that carries none: the customer's (contract first)."""
	return pricing_model.currency_for_customer(customer, pricing_model.active_contract(customer))


def _is_postpaid(customer):
	"""True if the customer's Active contract carries a credit relationship (TOP or Both).

	Such customers are billed on demand here. A pure-Cash customer's accruing work is
	billed by the monthly run instead (``monthly_invoicing``), and sweeping it here too
	would double-charge. A Both customer's per-booking Cash charges are still settled at the
	booking; only their accruing (TOP / container-level) charges flow through here."""
	contract = pricing_model.active_contract(customer)
	return bool(contract) and frappe.db.get_value("Depot Contract", contract, "payment_type") in ("TOP", "Both")


def _billed_pairs(customer):
	"""Every ``(doctype, order, currency)`` a LIVE consolidated invoice of this customer
	already carries.

	The manifest is the truth about what has been billed — it is what a rollback gives back,
	and it is cleared the moment an invoice is cancelled or discarded. The order's own
	``sales_invoice`` link cannot answer this: an order billed in two currencies sits on two
	invoices and the link names only one of them, so rolling ONE of them back would either
	strand the other currency as unbillable or re-bill both.

	Scoped to the customer's own invoices, so the scan stays the size of one account's
	billing history rather than the whole ledger.
	"""
	pairs = set()
	for raw in frappe.get_all(
		"Sales Invoice",
		filters={"customer": customer, MANIFEST_FIELD: ["is", "set"]},
		pluck=MANIFEST_FIELD,
	):
		try:
			sources = json.loads(raw) or []
		except Exception:
			continue
		for src in sources:
			if "storage" in src or "storage_charge" in src:
				continue
			pairs.add((src.get("dt"), src.get("name"), src.get("currency")))
	return pairs


def _already_billed(pairs, dt, name, currency, link=None) -> bool:
	"""Whether this order's work IN THIS CURRENCY is already on an invoice.

	A manifest written before billing split per currency names the order alone (no
	``currency`` key); it stands for the WHOLE order, every currency on it.

	``link`` is the order's ``sales_invoice``. A link that no live manifest explains was made
	outside consolidated billing — a Cash invoice raised at the booking, an amended invoice
	relinked, a hand-made one — and it means the order is spoken for whatever its currencies.
	That is the guard the per-doctype query filter used to provide before this gate replaced
	it.
	"""
	if (dt, name, currency) in pairs or (dt, name, None) in pairs:
		return True
	return bool(link) and not any(p[0] == dt and p[1] == name for p in pairs)


def _booking_lines(customer, lo, hi):
	"""Unbilled submitted **TOP** bookings → one unit per booking PER CURRENCY, carrying
	every charge line the booking priced.

	Cash bookings settle at the booking (they carry their own paid invoice), so only
	``payment_type = TOP`` bookings accrue for consolidated billing. A booking with no
	charges bills nothing and is skipped — that is a deliberate free booking, not a gap to
	fill from the tariff. (Before charges existed this re-derived a single lift rate from
	the contract tariff, which could disagree with what the booking itself showed.)

	A booking is always ONE currency — ``ContainerBooking._sync_currency_from_charges``
	refuses to save one whose charge rows disagree, and mirrors theirs onto the document — so
	unlike cleaning and M&R there is nothing to split here. The unit is still built through
	the shared splitter, so what counts as already-billed is decided the same way for every
	category."""
	pairs = _billed_pairs(customer)
	# Dated by the booking's own date (plan_date), never when it was keyed in (user,
	# 2026-10-07); a booking without one (most Tank In) falls back to its creation day.
	rows = frappe.db.sql(
		"""SELECT name, currency, sales_invoice FROM `tabContainer Booking`
		WHERE customer = %s AND payment_type = 'TOP' AND docstatus = 1
			AND COALESCE(plan_date, DATE(creation)) BETWEEN %s AND %s""",
		(customer, getdate(lo), getdate(hi)),
		as_dict=True,
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
		by_ccy = {r.currency or fallback: lines} if lines else {}
		units += _currency_units("Container Booking", r.name, by_ccy, pairs, r.sales_invoice)
	return units


def _currency_units(dt, name, lines_by_currency, pairs, link=None):
	"""One unit per currency of one order, minus the currencies already on an invoice.

	Sorted so a mixed order always produces its units — and therefore its sibling invoices —
	in the same order, run after run.
	"""
	for ccy, lines in lines_by_currency.items():
		for ln in lines:
			# Each line remembers its own currency (it may be converted into another invoice
			# currency) and the order it bills (which locks it on the invoice).
			ln["currency"] = ccy
			ln["source"] = f"{dt}|{name}"
	return [
		{
			"currency": ccy,
			"lines": lines_by_currency[ccy],
			# The currency is part of the rollback descriptor: giving an order back means
			# giving back the half THIS invoice billed, not the whole order.
			"sources": [{"dt": dt, "name": name, "currency": ccy}],
		}
		for ccy in sorted(lines_by_currency)
		if lines_by_currency[ccy] and not _already_billed(pairs, dt, name, ccy, link)
	]


def _cleaning_lines(customer, lo, hi):
	"""Completed, not-yet-billed cleaning for the customer's tanks.

	Each cleaning Service chosen on an order (``cleaning_services``) becomes its own invoice
	line — its own qty at the rate the order carries. The contract only ever seeded that rate
	when the line was added; the invoice bills what the order says, so an order with no priced
	service bills nothing (see :func:`_bills_something`). Each line also brings the labour
	tariff the order quoted (``manhour_rate``) as the invoice line's Manhour.

	Each service row carries its own currency, so an order that mixes them is split into one
	unit per currency and lands on two sibling invoices."""
	fallback_ccy = _fallback_currency(customer)
	pairs = _billed_pairs(customer)
	rows = frappe.get_all(
		"Cleaning Order",
		# The order's own date (Tanggal Cleaning), not when the wash ended (user, 2026-10-02).
		filters={"status": "Completed", "plan_date": ["between", [lo, hi]]},
		fields=["name", "container", "currency", "sales_invoice"],
	)
	units = []
	for r in rows:
		if frappe.db.get_value("Container", r.container, "principal") != customer:
			continue
		services = frappe.get_all(
			"Cleaning Order Service", filters={"parent": r.name},
			fields=["cleaning_item", "item_name", "quantity", "rate", "currency", "manhour_rate"],
			order_by="idx asc",
		)
		by_ccy = {}
		for s in services:
			if not (s.cleaning_item and flt(s.rate) > 0):
				continue
			line = {
				"item_code": s.cleaning_item,
				"description": f"Cleaning {r.name} · {s.item_name or s.cleaning_item}",
				# Baris lama (sebelum kolom Qty ada) tidak punya qty — satu kali pakai.
				"qty": flt(s.quantity) or 1, "rate": s.rate,
			}
			# The order's own labour tariff, as it stands (0 included: the order decides).
			line["manhour"] = flt(s.manhour_rate)
			by_ccy.setdefault(s.currency or r.currency or fallback_ccy, []).append(line)
		units += _currency_units("Cleaning Order", r.name, by_ccy, pairs, r.sales_invoice)
	return units


# Work orders: a completed job carrying a table of used items, billed one invoice line per
# item. Kept as a registry (rather than inlined into the M&R builder) because the shape is
# generic — a work order is told apart only by its label and party field.
_WORK_ORDERS = (
	{
		"doctype": "Repair Order",
		"child": "Repair Used Item",
		# M&R records the tank's owner and always bills them.
		"party_field": "principal",
		"label": "M&R",
		"job_type": "Repair",
	},
	# Uji berkala: Repair Order yang sama, ditagih di seksinya sendiri (menu & tim Periodic
	# Test terpisah dari M&R — container_depot/mr_scope.py).
	{
		"doctype": "Repair Order",
		"child": "Repair Used Item",
		"party_field": "principal",
		"label": "Periodic Test",
		"job_type": "Periodic Test",
	},
)


# Work orders carry billing_status + a sales_invoice back-link, so _mark_billed /
# _unmark_billed treat them as one kind rather than naming each doctype.
_WORK_ORDER_DOCTYPES = frozenset(spec["doctype"] for spec in _WORK_ORDERS)


def _work_order_lines(customer, lo, hi, spec):
	"""Completed, Unbilled work orders of one kind — **one invoice line per used item**.

	Billing item by item (rather than one lump "M&R RO-xxx" line) is what lets the invoice
	charge labour: each line carries the labour tariff its order row quoted, and
	``invoicing.apply_manhour_charge`` totals them once in the header — which is exactly why
	the order itself no longer costs labour (see ``RepairOrder.calculate_totals``).

	Owner-rejected lines are excluded, the same rule the order's own total uses. A line whose
	part is free (rate 0) is still billed: it may carry nothing but labour. An order where
	NOTHING is worth anything — no priced part and no labour tariff — is dropped by
	:func:`_bills_something` instead, so the free job never reaches an invoice.

	Each used-item row carries the currency its own tariff line states, so an order that mixes
	them is split into one unit per currency rather than billed whole in one of the two.
	"""
	rows = frappe.get_all(
		spec["doctype"],
		filters={
			"status": "Completed",
			spec["party_field"]: customer,
			# The order's own date (Tanggal M&R), not when the work ended (user, 2026-10-02).
			"plan_date": ["between", [lo, hi]],
			**({"job_type": spec["job_type"]} if spec.get("job_type") else {}),
		},
		fields=["name", "sales_invoice"],
	)
	fallback_ccy = _fallback_currency(customer)
	pairs = _billed_pairs(customer)
	# Ask the child doctype whether it carries a negotiated labour tariff rather than
	# assuming every work-order child is shaped alike.
	labour_fields = ["manhour_rate"] if frappe.get_meta(spec["child"]).has_field("manhour_rate") else []
	units = []
	for r in rows:
		used = frappe.get_all(
			spec["child"],
			filters={"parent": r.name, "parenttype": spec["doctype"]},
			fields=["item", "item_name", "quantity", "item_rate", "currency", "decision"] + labour_fields,
			order_by="idx asc",
		)
		by_ccy = {}
		for u in used:
			if not u.item or (u.decision or "Pending") == "Rejected":
				continue
			line = {
				"item_code": u.item,
				"description": f"{spec['label']} {r.name} · {u.item_name or u.item}",
				"qty": flt(u.quantity) or 1,
				"rate": flt(u.item_rate),
			}
			# The labour tariff THIS line was quoted at — the order is what the owner approved,
			# so it, not the contract today, is what the invoice bills (0 included).
			if labour_fields:
				line["manhour"] = flt(u.manhour_rate)
			by_ccy.setdefault(u.currency or fallback_ccy, []).append(line)
		units += _currency_units(spec["doctype"], r.name, by_ccy, pairs, r.sales_invoice)
	return units


def _mr_lines(customer, lo, hi):
	"""Completed, Unbilled Repair Orders (see :func:`_work_order_lines`)."""
	return _work_order_lines(customer, lo, hi, _WORK_ORDERS[0])


def _periodic_lines(customer, lo, hi):
	"""Completed, Unbilled Periodic Test orders (see :func:`_work_order_lines`)."""
	return _work_order_lines(customer, lo, hi, _WORK_ORDERS[1])


def _storage_lines(customer, from_date, to_date):
	"""Unbilled storage days, one unit per VISIT, read off the Storage Charge ledger.

	The ledger is the storage policy: each visit carries the free days and charging mode its
	owner had when the tank arrived, and the rate its contract priced that tank's size at
	(``storage_charge._price``). So the bill follows the visit, not today's contract — the
	same rule every order line follows. ``storage.measure`` counts the days: after the free
	days, after what this visit already billed, inside the window. A visit under *Saat Tank
	Keluar* is not billable until it has gated out.

	Visits on a zero rate bill nothing: the contract priced no storage when the tank came in.
	"""
	count_mode = storage.count_mode()
	fallback_ccy = _fallback_currency(customer)
	units = []
	for v in frappe.get_all(
		"Storage Charge",
		filters={"principal": customer, "status": ["!=", "Paid"]},
		fields=[
			"name", "container", "date_in", "date_out", "billing_mode", "free_days",
			"billed_until", "storage_item", "rate", "currency",
		],
		order_by="container asc, date_in asc",
	):
		period = {"start": v.date_in, "end": v.date_out}
		if not flt(v.rate) or not storage.billable_now(period, v.billing_mode or storage.DEFAULT_MODE):
			continue
		m = storage.measure(
			period, from_date, to_date, free_days=v.free_days, billed_until=v.billed_until, mode=count_mode
		)
		days = m["chargeable_days"]
		if days <= 0:
			continue
		ccy = v.currency or fallback_ccy
		units.append({
			"currency": ccy,
			"lines": [{
				"item_code": v.storage_item or pricing.STORAGE_ITEM,
				"description": f"Storage {v.container} {m['charge_from']} s/d {m['charge_to']} ({days} hari)",
				"qty": days,
				"rate": flt(v.rate),
				"currency": ccy,
				"source": f"Storage Charge|{v.name}",
			}],
			# ``prev`` is what rollback restores; ``to`` is what billing moves the visit to.
			"sources": [{
				"storage_charge": v.name,
				"prev": str(v.billed_until) if v.billed_until else None,
				"to": str(m["charge_to"]),
			}],
		})
	return units


# --------------------------------------------------------------------------- #
# Categories — the "sections" a user bills by.
#
# Each is one builder above. The operator picks any combination (Cleaning + M&R, or
# Storage alone, …) and a window; everything downstream — preview, fill, the report's
# selection — works off this registry rather than a hard-coded sweep.
# --------------------------------------------------------------------------- #
CATEGORIES = ("Booking", "Cleaning", "M&R", "Periodic Test", "Storage")

# Bookings carry their own ``payment_type``, so their TOP rows are billable for anyone.
# The rest accrue at the container-owner level with no per-order payment type, and are
# only swept for a postpaid customer — a pure-Cash customer's are the monthly scheduler's
# to bill, and sweeping them here too would double-charge.
_ACCRUAL_CATEGORIES = frozenset({"Cleaning", "M&R", "Periodic Test", "Storage"})

# Storage is deliberately absent: alone among the categories it has no order document to
# read, so it is built from plain dates rather than datetime bounds (see collect_units).
_BUILDERS = {
	"Booking": _booking_lines,
	"Cleaning": _cleaning_lines,
	"M&R": _mr_lines,
	"Periodic Test": _periodic_lines,
}

def _normalize_categories(categories):
	"""Accept a list, a JSON string (from the client) or None (= all) → ordered tuple.

	A null argument reaches the server as "" (jQuery form encoding): Gabungan sends that."""
	if isinstance(categories, str):
		categories = json.loads(categories) if categories.strip() else None
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


def _collect(customer, cats, from_d, to_d, accrual=None):
	"""Collect units for an ALREADY-resolved window and category tuple.

	``accrual`` forces the container-owner categories on or off; by default they are swept
	only for a postpaid customer (the monthly run passes True for its Cash customers)."""
	if from_d > to_d:
		# The billing start date is still ahead of the window: nothing has become billable
		# yet. Not an error — the depot is simply operating before it charges.
		return []
	lo, hi = f"{from_d} 00:00:00", f"{to_d} 23:59:59"
	postpaid = _is_postpaid(customer) if accrual is None else accrual

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
	return [u for u in units if _bills_something(u)]


def _bills_something(unit) -> bool:
	"""True when a unit is actually worth money — the zero-total gate for every category.

	An order that prices out at zero is a free job: a real outcome somebody decided on, not
	a gap to fill from the tariff. It must never become an invoice line, because a zero-value
	receivable is something the customer is asked to settle and owes nothing on. Container
	Booking has enforced this at the source since it grew charges
	(``ContainerBooking._billable_lines``); this is the same rule for cleaning, M&R and
	storage, applied in ONE place so the preview and every fill path agree about what bills.

	Labour still counts as value. An M&R line may carry no part price at all and bill only its
	labour tariff (``manhour``), which the invoice header meets with the hours worked, so
	labour alone keeps an order billable — which is why this asks about the unit, not about
	each line (see :func:`_work_order_lines`)."""
	total = sum(flt(ln.get("qty") or 1) * flt(ln.get("rate")) for ln in unit["lines"])
	labour = sum(flt(ln.get("manhour")) for ln in unit["lines"])
	return total > 0 or labour > 0


def _mark_billed(dt, name, si):
	"""Mark one swept order billed against its currency's Sales Invoice."""
	if dt == "Container Booking":
		frappe.db.set_value(dt, name, {"sales_invoice": si, "payment_status": "Invoiced"}, update_modified=False)
	elif dt in _WORK_ORDER_DOCTYPES:
		frappe.db.set_value(dt, name, {"billing_status": "Client Billed", "sales_invoice": si}, update_modified=False)
	elif dt == "Cleaning Order":
		frappe.db.set_value(dt, name, "sales_invoice", si, update_modified=False)


def _other_invoice_for(dt, name, exclude, customer=None):
	"""Another LIVE consolidated invoice that still carries this order, or None.

	A mixed-currency order may sit on one invoice per currency (ticked apart in the preview,
	or billed before runs stopped splitting). Rolling one of them back gives back only THAT
	currency (its manifest entry goes with it); the order itself is still
	billed, so its link has to move to a sibling rather than be cleared — a cleared link
	reads as "never invoiced" and is what the ``_already_billed`` fallback would trust.

	The LIKE is only a cheap prefilter on the stored JSON; the manifest is parsed to confirm.
	Scoped to the customer when known, so it reads one account's invoices, not the ledger.
	"""
	filters = {MANIFEST_FIELD: ["like", f'%"{name}"%'], "name": ["!=", exclude or ""]}
	if customer:
		filters["customer"] = customer
	for row in frappe.get_all(
		"Sales Invoice",
		filters=filters,
		fields=["name", MANIFEST_FIELD],
	):
		try:
			sources = json.loads(row.get(MANIFEST_FIELD)) or []
		except Exception:
			continue
		if any(src.get("dt") == dt and src.get("name") == name for src in sources):
			return row.name
	return None


def _unmark_billed(dt, name, exclude_invoice=None, customer=None):
	"""Reverse :func:`_mark_billed` — return the order to its pre-generate, un-invoiced
	state so it is billable again.

	Only when nothing else still bills it. An order billed in two currencies is on two
	invoices; rolling one back leaves the other standing, and the order must keep reading as
	invoiced (pointed at the surviving sibling) or the next sweep would bill BOTH halves a
	second time. The currency that was rolled back is billable again all the same — that is
	decided by the manifests, not by this link (see :func:`_billed_pairs`).
	"""
	# A manifest written before a doctype was taken down (Periodic Test Order / Survey
	# Order, v0_66) still names it; rolling back such an invoice must not blow up on a
	# table that no longer exists.
	if not frappe.db.exists("DocType", dt) or not frappe.db.exists(dt, name):
		return
	survivor = _other_invoice_for(dt, name, exclude_invoice, customer)
	if dt == "Container Booking":
		frappe.db.set_value(
			dt, name,
			{"sales_invoice": survivor, "payment_status": "Invoiced" if survivor else "Unpaid"},
			update_modified=False,
		)
	elif dt in _WORK_ORDER_DOCTYPES:
		frappe.db.set_value(
			dt, name,
			{
				"billing_status": "Client Billed" if survivor else "Unbilled",
				"sales_invoice": survivor,
			},
			update_modified=False,
		)
	elif dt == "Cleaning Order":
		frappe.db.set_value(dt, name, "sales_invoice", survivor, update_modified=False)


def _guard_billing(action):
	"""Common gate for every entry point that turns depot work into a receivable."""
	finance.require_enabled(action)
	# This used to be a hardcoded role list, narrowed to System Manager when the old role
	# model was purged on 2026-08-05. It is DocPerm-first now: whoever may create a Sales
	# Invoice may raise one from depot work too — the same rule the ESS layer runs on
	# (ess.guard.require_menu, "DocPerm is the teeth"), and it needs no editing when a role
	# is added, since the billing roles get Sales Invoice through their ERPNext companion
	# role (install.COMPANION_ROLES — Cashier/Accounts User, Finance/Accounts Manager).
	# The invoice itself is inserted with ignore_permissions (invoicing.py), so this IS the
	# gate. System Manager stays admitted on its own: it holds Sales Invoice READ via "All"
	# but no create, so a DocPerm-only check would take billing away from the admin who has
	# it today.
	if not frappe.has_permission("Sales Invoice", ptype="create"):
		frappe.only_for(["System Manager"])


def _unit_key(u):
	"""Stable id for one collected unit — what the preview ticks and the fill filters on.

	A unit is one order IN ONE CURRENCY (or, for storage, one visit), so the currency is
	part of the key: a mixed order shows as two preview rows and either may be billed on its
	own. The key survives a re-collect because it is derived from the source document, not
	from position in the list.
	"""
	return _source_key(u["sources"][0])


def _source_key(src):
	""":func:`_unit_key` of one rollback-manifest entry."""
	if "storage_charge" in src:
		return f"Storage|{src['storage_charge']}"
	if "storage" in src:  # pre-ledger storage manifest: the tank's watermark
		return f"Storage|{src['storage']}"
	return f"{src['dt']}|{src['name']}|{src.get('currency') or ''}"


def _unit_order_key(u):
	"""The unit's ORDER, without its currency — the vocabulary the Order Billing Status
	selection speaks. Ticking an order there bills everything it still owes, in every
	currency it carries."""
	src = u["sources"][0]
	if "storage_charge" in src:
		return f"Storage|{src['storage_charge']}"
	return f"{src['dt']}|{src['name']}"


def _unit_label(u):
	"""Human-readable name of what a unit charges for (an order number, or a storage visit)."""
	src = u["sources"][0]
	return src.get("storage_charge") or src["name"]


def _normalize_keys(keys):
	"""Accept a list, a JSON string (from the client) or None (= take everything)."""
	if isinstance(keys, str):
		keys = json.loads(keys) if keys.strip() else None
	return set(keys) if keys else None


def _stamp_sources(si, sources):
	"""Mark every swept source billed against ``si`` and record the rollback manifest."""
	for src in sources:
		if "storage_charge" in src:
			_move_storage_visit(src["storage_charge"], src["to"], si)
		else:
			_mark_billed(src["dt"], src["name"], si)
	frappe.db.set_value("Sales Invoice", si, MANIFEST_FIELD, json.dumps(sources), update_modified=False)


def _move_storage_visit(visit, billed_until, si):
	"""Set a visit's billing watermark, then let the ledger recount its days and status."""
	from container_depot import storage_charge

	frappe.db.set_value(
		"Storage Charge", visit,
		{"billed_until": getdate(billed_until) if billed_until else None, "sales_invoice": si},
		update_modified=False,
	)
	container = frappe.db.get_value("Storage Charge", visit, "container")
	if container:
		storage_charge.sync(container)


@frappe.whitelist()
def preview_bill(customer, categories=None, from_date=None, to_date=None, sales_invoice=None):
	"""What a bill run would pick up, WITHOUT creating anything — **one row per order**.

	Returns ``{"window", "sections": [{"category", "rows": [...]}], "total_orders", "kurs",
	"company_currency"}`` where each row is ``{"key", "label", "doctype", "name", "tank",
	"date", "detail", "currency", "amount"}`` (the Order Billing Status columns).
	The operator ticks the rows they want and the keys come back to :func:`fill_invoice`, so a
	run can be narrowed to individual orders rather than being all-or-nothing per section.

	With ``sales_invoice`` (a saved draft) the orders it already bills come first, flagged
	``on_invoice``, and the dialog starts from its currency and kurs: the pick then edits that
	invoice in place (see :func:`_refill`).
	``kurs`` is the Currency Exchange default (IDR per unit) for every currency on screen — the
	dialog lets the user change them before converting.

	Read-only: safe to call on every filter change.
	"""
	if not customer:
		frappe.throw(_("Customer wajib diisi."))
	cats = _normalize_categories(categories)
	from_d, to_d = _window(from_date, to_date)
	doc = _draft_of(customer, sales_invoice) if sales_invoice else None

	sections = {}
	currencies = set()
	for cat, row in _invoice_rows(doc) if doc else []:
		currencies.add(row["currency"])
		sections.setdefault(cat, {"category": cat, "rows": []})["rows"].append(row)
	for u in _collect(customer, cats, from_d, to_d):
		currencies.add(u["currency"])
		sec = sections.setdefault(u["category"], {"category": u["category"], "rows": []})
		doctype, name, tank, date = _row_facts(u)
		sec["rows"].append({
			"key": _unit_key(u),
			"label": _unit_label(u),
			"doctype": doctype,
			"name": name,
			"tank": tank,
			"date": date,
			# What the line(s) actually say, so a row is judgeable without opening the order.
			"detail": "; ".join(ln.get("description") or "" for ln in u["lines"])[:180],
			"currency": u["currency"],
			"amount": sum(flt(ln.get("qty") or 1) * flt(ln.get("rate")) for ln in u["lines"]),
		})

	base = invoicing.company_currency()
	locked = invoicing.locked_currency(customer)
	ordered = [sections[c] for c in CATEGORIES if c in sections]
	kurs = {ccy: invoicing.kurs_idr(ccy) for ccy in currencies | {base} | ({locked} - {None})}
	if doc:  # what the invoice already converts at
		kurs.update({r.depot_currency: flt(r.depot_kurs) for r in doc.items if flt(r.depot_kurs)})
		kurs[doc.currency] = flt(doc.conversion_rate)
	return {
		"customer": customer,
		"window": {"from_date": str(from_d), "to_date": str(to_d)},
		"sections": ordered,
		"total_orders": sum(len(s["rows"]) for s in ordered),
		"company_currency": base,
		# Set when the customer's receivable is foreign: the only currency on offer.
		"locked_currency": locked,
		# Set when the pick edits a saved draft: it stays in its own currency.
		"invoice_currency": doc.currency if doc else None,
		"kurs": kurs,
	}


def _draft_of(customer, name):
	"""The saved draft a pick edits, checked: still a draft, this customer's, writable."""
	doc = frappe.get_doc("Sales Invoice", name)
	doc.check_permission("write")
	if doc.docstatus != 0:
		frappe.throw(_("Hanya invoice draft yang bisa diubah ordernya — batalkan invoice-nya dulu."))
	if doc.customer != customer:
		frappe.throw(_("Invoice ini milik {0} — satu invoice hanya untuk satu customer.").format(doc.customer))
	return doc


def _lines_of(doc, src):
	"""The invoice's own lines billed from one manifest entry."""
	if "dt" in src:
		want, ccy = f"{src['dt']}|{src['name']}", src.get("currency")
	else:
		want, ccy = f"Storage Charge|{src['storage_charge']}" if "storage_charge" in src else f"Storage|{src['storage']}", None
	return [r for r in doc.items if r.get("depot_source") == want and (not ccy or r.depot_currency == ccy)]


def _source_category(src):
	"""The pick-list section a manifest entry belongs to."""
	if "dt" not in src:
		return "Storage"
	if src["dt"] == "Repair Order":
		job = frappe.db.get_value("Repair Order", src["name"], "job_type")
		return "Periodic Test" if job == "Periodic Test" else "M&R"
	return {"Container Booking": "Booking", "Cleaning Order": "Cleaning"}.get(src["dt"], src["dt"])


def _invoice_rows(doc):
	"""``(category, row)`` for every order ``doc`` already bills, as ticked pick-list rows."""
	out = []
	for src in _manifest(doc) or []:
		lines = _lines_of(doc, src)
		doctype, name, tank, date = _row_facts({"sources": [src]})
		out.append((_source_category(src), {
			"key": _source_key(src),
			"label": name,
			"doctype": doctype,
			"name": name,
			"tank": tank,
			"date": date,
			"detail": "; ".join(r.description or "" for r in lines)[:180],
			"currency": src.get("currency") or (lines[0].depot_currency if lines else doc.currency),
			"amount": sum(flt(r.qty) * flt(r.depot_price) for r in lines),
			"on_invoice": 1,
		}))
	return out


def _refill(doc, cats, wanted, from_d, to_d, currency, kurs):
	"""Change which orders a saved draft bills, IN PLACE — one invoice, many orders.

	Orders left unticked are given back and their lines removed; newly ticked ones are
	collected fresh and appended. Lines of the orders that stay are not touched, nor are lines
	typed by hand, nor the header — except ``currency``, which may move the whole invoice into
	another currency (every line keeps its own price and converts through its kurs).
	``wanted`` None keeps everything and adds all that matches.
	"""
	current = _manifest(doc) or []
	kept = [s for s in current if wanted is None or _source_key(s) in wanted]
	dropped = [s for s in current if s not in kept]
	gone = {id(r) for s in dropped for r in _lines_of(doc, s)}
	doc.set("items", [r for r in doc.items if id(r) not in gone])
	for s in dropped:
		_give_back(s, doc)

	# Orders still on the manifest (kept or dropped) read as billed, so the collect only
	# brings what is new — except a storage visit already on it, which may have accrued days
	# since: those wait for the next invoice (one visit, one manifest entry per invoice).
	have = {_source_key(s) for s in current}
	units = [
		u for u in _collect(doc.customer, cats, from_d, to_d)
		if (wanted is None or _unit_key(u) in wanted) and _unit_key(u) not in have
	]
	kurs = _normalize_kurs(kurs)
	new_ccy = invoicing.locked_currency(doc.customer) or currency or doc.currency
	if new_ccy != doc.currency:
		doc.currency = new_ccy
		doc.conversion_rate = kurs.get(new_ccy) or invoicing.kurs_idr(new_ccy, doc.posting_date) or 1
	elif kurs.get(doc.currency):
		doc.conversion_rate = kurs[doc.currency]
	for r in doc.items:  # the dialog's kurs is what the whole bill converts at
		if r.depot_currency != doc.currency and kurs.get(r.depot_currency):
			r.depot_kurs = kurs[r.depot_currency]
	invoicing.append_lines(doc, [ln for u in units for ln in u["lines"]], kurs)
	if not doc.items:
		frappe.throw(_("Invoice tidak boleh kosong — centang minimal satu order, atau Cancel invoice-nya."))
	for i, r in enumerate(doc.items, start=1):
		r.idx = i

	doc.flags.depot_refill = True  # protect_consolidated_items: these line changes are the pick
	doc.flags.ignore_permissions = True
	doc.save()
	_stamp_sources(doc.name, kept + [src for u in units for src in u["sources"]])
	return {"invoices": [doc.name]}


def _normalize_kurs(kurs) -> dict:
	if isinstance(kurs, str):
		kurs = json.loads(kurs) if kurs else {}
	return {k: flt(v) for k, v in (kurs or {}).items() if flt(v)}


def bill_units(customer, units, remarks, currency=None, kurs=None, branch=None, header=None):
	"""Turn collected units into ONE draft Sales Invoice and mark every source billed.

	Every line keeps its own currency and is converted into ``currency`` through ``kurs``
	(``{currency: IDR per unit}``; a missing one is read from Currency Exchange). A customer
	whose receivable is foreign is always billed in it (``invoicing.locked_currency``).
	Otherwise, without ``currency`` the invoice takes the units' currency when they share one,
	else the company's — what the Ambil Tagihan dialog preselects. Returns ``{"invoices": [name]}`` (empty when
	nothing bills), a list so callers need not care.
	"""
	lines = [ln for u in units for ln in u["lines"]]
	if not lines:
		return {"invoices": []}
	kurs = _normalize_kurs(kurs)
	# The form's own header (Ambil Tagihan / Pilih Order from an invoice form) wins over what
	# is derived here: it is what the user typed before picking.
	header = (json.loads(header) if header.strip() else {}) if isinstance(header, str) else (header or {})
	# The Invoice Type is what the run billed: one category, or Gabungan for several.
	kinds = {u.get("category") for u in units}
	invoice_type = header.get("depot_invoice_type") or (kinds.pop() if len(kinds) == 1 else None) or "Gabungan"
	ccys = {u["currency"] for u in units}
	currency = (
		invoicing.locked_currency(customer)
		or currency
		or (ccys.pop() if len(ccys) == 1 else invoicing.company_currency())
	)
	si = invoicing.create_draft_sales_invoice(
		customer,
		lines,
		due_days=30,
		posting_date=header.get("posting_date"),
		remarks=remarks,
		currency=currency,
		kurs=kurs,
		branch=branch or header.get("branch"),
		invoice_type=invoice_type,
		address=header.get("customer_address"),
	)
	if not si:
		return {"invoices": []}
	_stamp_sources(si, [src for u in units for src in u["sources"]])
	return {"invoices": [si]}


@frappe.whitelist()
def fill_invoice(
	customer, categories=None, from_date=None, to_date=None, keys=None, sales_invoice=None,
	currency=None, kurs=None, header=None,
):
	"""Run a bill: collect the chosen sections and turn them into draft Sales Invoices.

	``keys`` are the unit keys the operator ticked in the preview (see :func:`preview_bill`);
	omit them to bill everything the filter matches. Selection is applied to a FRESH collect
	rather than to whatever the preview returned, so an order that was billed or edited
	between preview and confirm is re-read rather than trusted from the client.

	``currency`` is the currency to bill everything in (the rest converted through ``kurs``);
	see :func:`bill_units` for the default.

	``header`` is what the form already says (see :func:`bill_units`), so a pick made from an
	unsaved form keeps the Branch, Customer Address, date and Invoice Type typed on it.

	``sales_invoice`` edits that saved draft **in place** (:func:`_refill`): ``keys`` is then the
	whole set it should bill — its current orders left unticked are given back, new ones
	appended. Without it a fresh invoice is created.

	Returns ``{"invoices": [...]}``: one invoice, or none when the window holds nothing
	billable.
	"""
	if not customer:
		frappe.throw(_("Customer wajib diisi."))
	_guard_billing(_("Ambil Tagihan"))
	cats = _normalize_categories(categories)
	wanted = _normalize_keys(keys)
	from_d, to_d = _window(from_date, to_date)

	if sales_invoice:
		return _refill(_draft_of(customer, sales_invoice), cats, wanted, from_d, to_d, currency, kurs)

	units = _collect(customer, cats, from_d, to_d)
	if wanted is not None:
		units = [u for u in units if _unit_key(u) in wanted]
	# Remarks stay empty: they are the user's (user, 2026-09-29); Sumber Tagihan lists the orders.
	return bill_units(customer, units, None, currency, kurs, None, header)


@frappe.whitelist()
def fill_invoice_from_orders(customer, orders, currency=None, kurs=None):
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
		u
		for u in collect_units(customer, None, "2000-01-01", today())
		if _unit_order_key(u) in wanted
	]
	if not units:
		frappe.throw(_("Order yang dipilih sudah ditagih atau tidak menagihkan apa pun."))
	return bill_units(customer, units, None, currency, kurs)


@frappe.whitelist()
def bill_customer(customer, from_date=None, to_date=None):
	"""Sweep every category for a customer into one draft Sales Invoice.

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
	back to un-invoiced (clear links, reset statuses, restore storage watermarks), so
	the customer's orders return to the pre-generate state and can be generated again.

	On ``on_trash`` this runs BEFORE Frappe's link-integrity check, so clearing the
	order→invoice links also unblocks the discard."""
	sources = _manifest(doc)
	if not sources:
		return
	for src in sources:
		_give_back(src, doc)
	# On cancel / discard the invoice survives (docstatus 2); clear its manifest so a later
	# delete does not roll back a second time (the orders may have been re-generated by then).
	if method in ("on_cancel", "on_discard"):
		doc.db_set(MANIFEST_FIELD, None, update_modified=False)


def _give_back(src, doc):
	"""Return one manifest entry of ``doc`` to un-invoiced."""
	if "storage_charge" in src:
		if frappe.db.exists("Storage Charge", src["storage_charge"]):
			# A newer invoice billed the same visit further on: winding the watermark back to
			# this one's start would put the newer invoice's days up for billing again
			# (2026-10-09 audit). The newest goes first.
			later = frappe.db.get_value("Storage Charge", src["storage_charge"], "sales_invoice")
			if later and later != doc.name:
				frappe.throw(
					_("Storage {0} sudah ditagih lanjut di invoice {1} — batalkan invoice {1} dulu.").format(
						src["storage_charge"], later
					),
					title=_("Ada Invoice Lebih Baru"),
				)
			_move_storage_visit(src["storage_charge"], src.get("prev"), None)
	elif "storage" in src:
		# Manifests written before storage billed off the per-visit ledger moved the
		# container's single watermark instead.
		prev = src.get("prev")
		frappe.db.set_value(
			"Container", src["storage"], "storage_billed_until",
			getdate(prev) if prev else None, update_modified=False,
		)
	else:
		_unmark_billed(src.get("dt"), src.get("name"), exclude_invoice=doc.name, customer=doc.customer)


# The fields that name an order's tank(s) and its date, for the pick list and the Sumber
# Tagihan tab. The dates are the ones Order Billing Status shows.
_ROW_FACTS = {
	"Container Booking": ("container_summary", "plan_date"),
	"Cleaning Order": ("container", "plan_date"),
	"Repair Order": ("container", "plan_date"),
}


# The customer's own reference on an order: its Reff Doc, or a booking's DO when it has none.
_CUST_REF = {"Container Booking": ("reff_doc", "do_reference"), "Cleaning Order": ("reff_doc",), "Repair Order": ("reff_doc",)}


def cust_ref(dt, name):
	fields = _CUST_REF.get(dt)
	vals = frappe.db.get_value(dt, name, list(fields), as_dict=True) if fields else None
	return next((vals[f] for f in fields if vals[f]), "") if vals else ""


def stamp_reff_docs(doc, method=None):
	"""before_validate: every order line carries its order's Reff Doc (items grid, OAK Invoice).
	Re-read on every draft save, so a Reff Doc fixed on the order reaches the invoice; frozen
	once the invoice is submitted."""
	if doc.docstatus != 0:
		return
	refs = {}
	for r in doc.get("items") or []:
		src = r.get("depot_source") or ""
		if src not in refs:
			refs[src] = cust_ref(*src.split("|", 1)) if "|" in src else ""
		r.depot_reff_doc = refs[src]


def _row_facts(u):
	"""(doctype, name, tank, date) of the order — or storage visit — a unit bills."""
	src = u["sources"][0]
	if "storage_charge" in src:
		tank = frappe.db.get_value("Storage Charge", src["storage_charge"], "container")
		return "Storage Charge", src["storage_charge"], tank, src.get("to")
	if "storage" in src:  # pre-ledger storage manifest
		return "Container", src["storage"], src["storage"], src.get("to")
	tank_field, date_field = _ROW_FACTS.get(src["dt"], ("container", "modified"))
	tank, date, created = frappe.db.get_value(src["dt"], src["name"], [tank_field, date_field, "creation"]) or (None, None, None)
	date = date or created  # a booking without its own date: the day it was keyed in
	return src["dt"], src["name"], tank, getdate(date) if date else None


@frappe.whitelist()
def invoice_sources(sales_invoice):
	"""The Sumber Tagihan tab (erp_cakra's Connection tab): every order this invoice bills, its
	tank(s) and what it bills in each currency.

	The orders come off the manifest, the same list a rollback gives back; the amounts come off
	the lines' ``depot_source``, which invoices raised before 2026-09-28 do not carry (their
	rows show no amount)."""
	doc = frappe.get_doc("Sales Invoice", sales_invoice)
	doc.check_permission("read")
	amounts = {}
	for r in doc.items:
		if r.get("depot_source"):
			ccys = amounts.setdefault(r.depot_source, {})
			ccy = r.depot_currency or doc.currency
			ccys[ccy] = ccys.get(ccy, 0) + flt(r.qty) * flt(r.depot_price)
	keys = []
	for src in _manifest(doc) or []:
		dt, name = ("Storage Charge", src["storage_charge"]) if "storage_charge" in src else (src.get("dt"), src.get("name"))
		if dt and name and f"{dt}|{name}" not in keys:
			keys.append(f"{dt}|{name}")
	keys += [k for k in amounts if k not in keys]
	rows = []
	for key in keys:
		dt, name = key.split("|", 1)
		# A manifest may still name a doctype that was taken down (v0_66).
		tank_field = _ROW_FACTS.get(dt, ("container",))[0]
		tank = frappe.db.get_value(dt, name, tank_field) if frappe.db.table_exists(dt) else None
		rows.append({
			"doctype": dt, "name": name, "tank": tank, "amounts": amounts.get(key, {}),
			"reff_doc": cust_ref(dt, name),
		})
	return rows


# What a billed line may not change: it has to keep saying what its order says.
_LOCKED_LINE_FIELDS = ("item_code", "qty", "depot_price", "depot_currency", "manhour", "depot_source")


def protect_consolidated_items(doc, method=None):
	"""validate: a line billed from a depot order is locked to that order.

	Its item, qty, price, currency and hours mirror the order; to change what is billed, fix
	the order and re-generate (rollback + collect again). It cannot be deleted either — the
	order would stay marked billed for a line that no longer exists. The kurs and the
	description stay editable, and lines typed by hand are free.

	Detection is per row (``depot_source``), compared with the version last saved, so the
	programmatic creation itself (no prior version) and ERPNext's own recompute pass.
	"""
	before = doc.get_doc_before_save()
	if not before or doc.flags.get("depot_refill"):
		return
	locked = {r.name: r for r in (before.items or []) if r.get("depot_source")}
	now = {r.name: r for r in (doc.items or []) if r.name}
	for name, old in locked.items():
		new = now.get(name)
		if new is None:
			frappe.throw(
				_(
					"Baris {0} ditagih dari {1} dan tidak bisa dihapus. Lepas ordernya lewat "
					"Tambah / Lepas Order."
				).format(old.idx, old.depot_source)
			)
		for f in _LOCKED_LINE_FIELDS:
			a, b = old.get(f), new.get(f)
			if (flt(a) != flt(b)) if f in ("qty", "depot_price", "manhour") else ((a or "") != (b or "")):
				frappe.throw(
					_(
						"Baris {0} ditagih dari {1}: {2} tidak bisa diubah di invoice. Lepas ordernya "
						"lewat Tambah / Lepas Order, perbaiki ordernya, lalu pilih lagi."
					).format(new.idx, old.depot_source, new.meta.get_label(f))
				)
	# A copied row carries its original's source; it is a hand-typed line, not a billed one.
	for r in doc.items or []:
		if r.get("depot_source") and r.name not in locked:
			r.depot_source = None
