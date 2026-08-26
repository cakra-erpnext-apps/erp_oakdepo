"""Storage Charges — hari menginap per tank, dan berapa hari yang boleh ditagih.

One row per **depot visit**, not per container: a tank that came, left, and came back
appears twice, because that is two stays and two bills. Both ways a depot charges storage
are the same list under a different filter:

* **Saat Tank Keluar** — nothing until the tank gates out, then the whole visit at once.
* **Berjalan (Periodik)** — charged period by period while the tank is still inside, with
  the tail billed when it finally leaves.

Which one applies is **not** a filter the operator picks: it is negotiated per tank owner
and read from their ``Depot Contract.storage_billing_mode`` (see
``storage.billing_mode_for``). The default filter, *Sesuai Kontrak*, therefore shows each
owner exactly what their own contract allows to be charged — an on-exit owner's tanks stay
hidden while they are still inside. The stay-status filters beside it ignore the contract
and are there to inspect the yard, not to bill it.

The two modes cannot double-charge each other because they read the same interval and both
subtract what has already been billed — whatever a running run took is gone from the front
of the closing bill. That "already billed" comes from the visit's own **Storage Charge**
row, not from the container: one watermark per container could not say *"kunjungan Juli
belum ditagih, kunjungan Agustus sudah"*, and silently dropped the July days.

**Only the newest visit is listed by default.** A tank's history belongs in the Storage
Charge list, not in a billing worksheet. The *Semua kunjungan* switch brings the older ones
back — and any older visit still carrying unbilled days is listed regardless, because a
default that hides money owed is a default that loses it.

**This report raises nothing.** It is the days ledger; no Sales Invoice, no watermark
move, nothing written at all. Every figure is recomputed on open, so a corrected gate
timestamp shows up immediately.

Rates are best-effort and may well be 0 — the day count is what is being verified here,
and a rate card can be filled in afterwards without any of the days changing (see
``pricing.storage_rate_for``). The **Sumber** column says which record each stay's dates
came from, because a storage day the customer disputes has to be traceable to a gate
record rather than to an audit row written whenever someone happened to save the tank.
"""

from __future__ import annotations

import frappe
from frappe.utils import get_first_day, get_last_day, getdate, today

from container_depot import storage, storage_charge
from container_depot.container_depot.container_status import AVAILABLE, GATE_OUT, IN_DEPOT
from container_depot.monthly_invoicing import _active_contract
from container_depot.pricing import storage_rate_for

# The "Cara Charge" filter. BY_CONTRACT is the real one — it shows each owner exactly
# what their contract says may be charged. The other three ignore the contract and filter
# by the stay's own state; they are inspection tools ("what is sitting in my yard right
# now"), not billing views.
FILTER_BY_CONTRACT = "Sesuai Kontrak"
FILTER_RUNNING = "Masih Menginap"
FILTER_CLOSED = "Sudah Keluar"
FILTER_ALL = "Semua"

STAY_RUNNING = "Masih Menginap"
STAY_CLOSED = "Sudah Keluar"

# Tanks that can possibly have a stay. Booked is a reservation — the tank has never
# arrived, so there is nothing to charge for.
STATUSES = (IN_DEPOT, AVAILABLE, GATE_OUT)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return _columns(), _data(filters)


def _columns():
	return [
		{"fieldname": "container", "label": "Container", "fieldtype": "Link", "options": "Container", "width": 130},
		{"fieldname": "principal", "label": "Tank Owner", "fieldtype": "Link", "options": "Customer", "width": 170},
		{"fieldname": "size", "label": "Size", "fieldtype": "Data", "width": 70},
		{"fieldname": "stay_status", "label": "Stay", "fieldtype": "Data", "width": 110},
		{"fieldname": "billing_mode", "label": "Cara Charge (Kontrak)", "fieldtype": "Data", "width": 160},
		{"fieldname": "in_date", "label": "Masuk", "fieldtype": "Datetime", "width": 150},
		{"fieldname": "out_date", "label": "Keluar", "fieldtype": "Datetime", "width": 150},
		{"fieldname": "stay_days", "label": "Hari Menginap", "fieldtype": "Int", "width": 110},
		{"fieldname": "free_days", "label": "Free Days", "fieldtype": "Int", "width": 90},
		{"fieldname": "billed_until", "label": "Ditagih s/d", "fieldtype": "Date", "width": 100},
		{"fieldname": "chargeable_days", "label": "Hari Ditagih", "fieldtype": "Int", "width": 105},
		{"fieldname": "charge_from", "label": "Tagih Dari", "fieldtype": "Date", "width": 100},
		{"fieldname": "charge_to", "label": "Tagih s/d", "fieldtype": "Date", "width": 100},
		{"fieldname": "item", "label": "Item Tarif", "fieldtype": "Link", "options": "Item", "width": 160},
		{"fieldname": "currency", "label": "Curr", "fieldtype": "Link", "options": "Currency", "width": 70},
		{"fieldname": "rate", "label": "Rate/Hari", "fieldtype": "Currency", "options": "currency", "width": 110},
		{"fieldname": "amount", "label": "Perkiraan", "fieldtype": "Currency", "options": "currency", "width": 130},
		{"fieldname": "source", "label": "Sumber", "fieldtype": "Data", "width": 130},
		{"fieldname": "gate_entry", "label": "Gate Entry", "fieldtype": "Link", "options": "Gate Entry", "width": 140},
		{"fieldname": "depot", "label": "Depot", "fieldtype": "Link", "options": "Depot", "width": 100},
		{"fieldname": "storage_charge", "label": "Storage Charge", "fieldtype": "Link", "options": "Storage Charge", "width": 150},
		{"fieldname": "charge_status", "label": "Status", "fieldtype": "Data", "width": 100},
	]


def _window(filters):
	"""The period being looked at — defaults to the current month."""
	from_date = getdate(filters.from_date) if filters.from_date else get_first_day(getdate(today()))
	to_date = getdate(filters.to_date) if filters.to_date else get_last_day(getdate(today()))
	return from_date, to_date


def _containers(filters):
	where = {"status": ["in", STATUSES]}
	for field in ("principal", "depot"):
		if filters.get(field):
			where[field] = filters[field]
	if filters.get("container"):
		where["name"] = filters["container"]
	return frappe.get_all(
		"Container",
		filters=where,
		fields=["name", "container_no", "principal", "size", "status", "depot", "storage_billed_until"],
		order_by="principal asc, container_no asc",
	)


def _data(filters):
	from_date, to_date = _window(filters)
	mode = filters.get("mode")
	mode_count = storage.count_mode()
	containers = _containers(filters)
	periods = storage.periods_for_many(containers)
	ledger = _ledger([c.name for c in containers])

	# Per-owner lookups, resolved once each: every tank a principal owns shares them.
	free_days, modes, rates = {}, {}, {}
	rows = []
	for c in containers:
		if c.principal not in free_days:
			free_days[c.principal] = storage.free_days_for(c.principal)
			modes[c.principal] = storage.billing_mode_for(c.principal)
		visits = periods.get(c.name) or []
		newest = max((getdate(p["start"]) for p in visits), default=None)
		for period in visits:
			entry = ledger.get(_ledger_key(c.name, period)) or {}
			row = storage.measure(
				period, from_date, to_date,
				free_days=free_days[c.principal],
				billed_until=entry.get("billed_until"),
				mode=mode_count,
			)
			if not _visible(period, newest, row, filters):
				continue
			if not _in_scope(row, period, from_date, to_date, mode, modes[c.principal], mode_count):
				continue
			key = (c.principal, c.size)
			if key not in rates:
				rates[key] = _rate(c.principal, c.size)
			rate, item, currency = rates[key]
			rows.append({
				"container": c.name,
				"principal": c.principal,
				"size": c.size,
				"stay_status": STAY_RUNNING if row["is_open"] else STAY_CLOSED,
				"billing_mode": modes[c.principal],
				"in_date": period["start"],
				"out_date": period["end"],
				"stay_days": row["stay_days"],
				"free_days": row["free_days"],
				"billed_until": entry.get("billed_until"),
				"chargeable_days": row["chargeable_days"],
				"charge_from": row["charge_from"],
				"charge_to": row["charge_to"],
				"item": item,
				"currency": currency,
				"rate": rate,
				"amount": rate * row["chargeable_days"],
				"source": row["source"],
				"gate_entry": row["ref"],
				"depot": c.depot,
				"storage_charge": entry.get("name"),
				"charge_status": entry.get("status"),
			})

	if not filters.get("show_zero"):
		rows = [r for r in rows if r["chargeable_days"] > 0]
	rows.sort(key=lambda r: (r["principal"] or "", r["container"], r["in_date"]))
	return rows


def _in_scope(row, period, from_date, to_date, mode, policy, mode_count) -> bool:
	"""Does this stay belong in the answer?

	Two gates. First the **Cara Charge** filter: either the owner's contract decides
	(``Sesuai Kontrak`` — an owner billed on exit hides their tanks that are still inside,
	because those are not chargeable to them yet), or the operator overrides it to look at
	one kind of stay regardless of contract.

	Then the **window**: a stay is in scope when it OVERLAPS it — started on or before the
	window ends, and had not already finished before it began. A stay wholly in the past is
	not "0 days", it is a different period's business, so it is dropped rather than listed
	as an empty row.
	"""
	if mode == FILTER_RUNNING and not row["is_open"]:
		return False
	if mode == FILTER_CLOSED and row["is_open"]:
		return False
	if mode in ("", None, FILTER_BY_CONTRACT) and not storage.billable_now(period, policy):
		return False
	if getdate(period["start"]) > to_date:
		return False
	return row["is_open"] or storage.last_billable_day(period, to_date, mode_count) >= from_date


def _ledger(containers):
	"""``{(container, key): row}`` of the Storage Charge ledger for these tanks.

	One query for the lot. Keyed the same way :mod:`storage_charge` keys a visit — by Gate
	Entry when there is one, by the arrival date when there is not — so a row lines up with
	the period it belongs to even for the tanks that have no gate record.
	"""
	if not containers:
		return {}
	out = {}
	for r in frappe.get_all(
		"Storage Charge",
		filters={"container": ["in", containers]},
		fields=["name", "container", "gate_entry", "date_in_key", "billed_until", "status"],
	):
		if r.gate_entry:
			out[(r.container, r.gate_entry)] = r
		out.setdefault((r.container, r.date_in_key), r)
	return out


def _ledger_key(container, period):
	return (container, period.get("ref") or str(getdate(period["start"])))


def _visible(period, newest, row, filters) -> bool:
	"""Newest visit only, unless asked otherwise — or unless the visit still owes days.

	The exception is the point. A tank that left in July unbilled and came back in August is
	exactly the case a per-visit ledger exists for; hiding it behind a "newest only" default
	would reintroduce, in the UI, the loss the ledger was built to stop.
	"""
	if filters.get("all_visits") or newest is None:
		return True
	return getdate(period["start"]) == newest or row["chargeable_days"] > 0


def _rate(principal, size):
	"""``(rate, item, currency)`` for one owner + size, from their active contract."""
	contract = _active_contract(principal) if principal else None
	rate, item = storage_rate_for(contract, size)
	currency = (frappe.db.get_value("Depot Contract", contract, "currency") if contract else None) or (
		frappe.defaults.get_global_default("currency") or frappe.db.get_default("currency") or "IDR"
	)
	return rate, item, currency
