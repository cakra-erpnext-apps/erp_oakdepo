"""Storage Charges — hari menginap per tank, dan berapa hari yang belum ditagih.

**No filters, and that is the design.** The report opens on every tank that has ever
stayed, showing each one's newest visit, over its whole recorded history — no period, no
mode, nothing pre-narrowed. A ledger that filters itself before being asked is a ledger
whose blank spots read as "tidak ada".

One box remains: **Container**. Setting it is how the older visits are read — the report
switches from "newest visit per tank" to "every visit of this tank". That is the drill-down,
and it is the only thing that changes what rows exist.

The newest row still has to answer for what is behind it, so it carries
``older_unpaid_days``: the days the tank's earlier visits are still owed. Without it,
"newest only" would hide exactly the money the per-visit ledger exists to protect — a tank
that left in July unbilled and came back in August would look settled.

Both ways a depot charges storage are the same rows:

* **Saat Tank Keluar** — nothing until the tank gates out, then the whole visit at once.
* **Berjalan (Periodik)** — charged period by period while the tank is still inside, with
  the tail billed when it finally leaves.

Which applies to an owner is negotiated, not picked per run: read from their
``Depot Contract.storage_billing_mode`` and shown on every row. They cannot double-charge
each other because both read the same interval and both subtract what has already been
billed — and that comes from the visit's own **Storage Charge** row, not from the
container: one watermark per container could not say *"kunjungan Juli belum ditagih,
kunjungan Agustus sudah"*, and silently dropped the July days.

**This report raises nothing.** No Sales Invoice, no watermark move, nothing written at
all. Every figure is recomputed on open, so a corrected gate timestamp shows up
immediately.

Rates are best-effort and may well be 0 — the day count is what is being verified here, and
a rate card can be filled in afterwards without any of the days changing (see
``pricing.storage_rate_for``). The **Sumber** column says which record each stay's dates
came from, because a storage day the customer disputes has to be traceable to a gate record
rather than to an audit row written whenever someone happened to save the tank.
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate, today

from container_depot import storage, storage_charge
from container_depot.container_depot.container_status import AVAILABLE, GATE_OUT, IN_DEPOT
from container_depot.monthly_invoicing import _active_contract
from container_depot.pricing import storage_rate_for

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
		{"fieldname": "chargeable_days", "label": "Hari Belum Ditagih", "fieldtype": "Int", "width": 130},
		{"fieldname": "older_unpaid_days", "label": "Kunjungan Lama Belum Ditagih (hari)", "fieldtype": "Int", "width": 220},
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


# No date filter: the report covers the tank's whole recorded history. A storage ledger
# asked "berapa hari belum ditagih" has one honest answer, and it is not "in the month you
# happened to be looking at" — a window silently turned days outside it into zero.
EPOCH = "1900-01-01"


def _containers(filters):
	"""The tanks in the answer.

	``principal`` / ``depot`` are honoured when passed but are NOT filters in the UI: the
	report opens unfiltered on purpose, and Container is the only box on it. They stay
	because callers (and tests) scope by them programmatically.
	"""
	where = {"status": ["in", STATUSES]}
	for field in ("principal", "depot"):
		if filters.get(field):
			where[field] = filters[field]
	if filters.get("container"):
		where["name"] = filters["container"]
	return frappe.get_all(
		"Container",
		filters=where,
		fields=["name", "container_no", "principal", "size", "status", "depot"],
		order_by="principal asc, container_no asc",
	)


def _data(filters):
	from_date, to_date = getdate(EPOCH), getdate(today())
	mode_count = storage.count_mode()
	drilled = bool(filters.get("container"))
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
		visits = sorted(periods.get(c.name) or [], key=lambda p: getdate(p["start"]))
		if not visits:
			continue

		measured = []
		for period in visits:
			entry = ledger.get(_ledger_key(c.name, period)) or {}
			measured.append((period, entry, storage.measure(
				period, from_date, to_date,
				free_days=free_days[c.principal],
				billed_until=entry.get("billed_until"),
				mode=mode_count,
			)))

		# One row per tank — its newest visit — unless the operator has drilled into a
		# single container, which is how the older visits are read. What the newest row
		# must NOT do is hide that money is still owed behind it, so the older visits'
		# unbilled days are carried onto it as a number: see the tank, see the backlog,
		# then set the Container filter to see the visits themselves.
		shown = measured if drilled else measured[-1:]
		older_unpaid = 0 if drilled else sum(m["chargeable_days"] for _, _, m in measured[:-1])

		key = (c.principal, c.size)
		if key not in rates:
			rates[key] = _rate(c.principal, c.size)
		rate, item, currency = rates[key]
		for period, entry, row in shown:
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
				"older_unpaid_days": older_unpaid,
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

	rows.sort(key=lambda r: (r["principal"] or "", r["container"], r["in_date"]))
	return rows


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


def _rate(principal, size):
	"""``(rate, item, currency)`` for one owner + size, from their active contract."""
	contract = _active_contract(principal) if principal else None
	rate, item = storage_rate_for(contract, size)
	currency = (frappe.db.get_value("Depot Contract", contract, "currency") if contract else None) or (
		frappe.defaults.get_global_default("currency") or frappe.db.get_default("currency") or "IDR"
	)
	return rate, item, currency
