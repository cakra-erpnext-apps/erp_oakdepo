"""Storage (menginap) day accounting — how long a tank actually sat in the depot.

This is the **days** engine, deliberately separate from billing: it answers "berapa hari
tank ini menginap, dan berapa hari yang boleh ditagih" and stops there. Nothing here
creates an invoice; the Storage Charges report reads it, and the billing paths can be
pointed at it later.

Two questions have to be answered before a day can be charged, and they are the two ways
a depot charges storage:

* **Closed** — the tank has gated out, so the stay is a finished interval (in -> out).
* **Running** — the tank is still inside, so the stay is open and accrues up to a cutoff
  date the operator picks.

Both are the same interval arithmetic; only the end differs. That is why they share one
calculator instead of being two features: mixing them can never double-charge, because a
stay produces ONE interval whichever way you look at it, and
``Container.storage_billed_until`` (the watermark the billing paths already keep) trims
whatever was billed before off its front.

**Where the dates come from.** Three sources, in descending order of trust, picked per
container — never merged, so a tank's history is read from one story rather than stitched
from three that may disagree:

1. ``Gate Entry`` — one record spans a whole visit, and there is one per visit. Its
   ``in_date`` / ``out_date`` are the bons' Tanggal Bongkar / Tanggal Muat — the day the tank
   came in and the day it left (``visit_dates``, user 2026-10-07) — never the moment somebody
   pressed Submit, and never an EIR's date. The only source that can describe a tank that
   came, left, and came back.
2. ``Container Movement`` — the status audit trail. Timestamped when the status was
   *saved*, not when the truck actually moved, so it is a fallback: right to the day for
   same-day data entry, wrong for anything entered late.
3. ``Container.in_date`` / ``out_date`` — last resort, and only ever the LAST visit (both
   fields are overwritten on re-entry).

Each row reports which source it used, because a storage bill that cannot be traced to a
gate record is a bill the customer will argue with.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, cint, date_diff, get_datetime, getdate, today

from container_depot.container_depot.container_status import GATE_OUT, PRESENT

SETTINGS = "Depot Finance Settings"

# Day-count conventions. The stay is one closed interval [masuk, keluar]; the only
# question is whether the departure day is charged, so the two modes differ by exactly
# one day at the tail and nowhere else.
COUNT_BOTH = "Hari masuk & keluar dihitung"
COUNT_NO_OUT = "Hari keluar tidak dihitung"
DEFAULT_COUNT_MODE = COUNT_BOTH

# The two ways a depot charges storage. This is a COMMERCIAL policy, negotiated per tank
# owner and held on their Depot Contract — not a property of the tank and not a mode the
# operator picks per run:
#
#   * ON_EXIT  — nothing is charged until the tank gates out, then the whole visit at once.
#     The DEFAULT: one stay, one bill, and the dates on it are the gate dates the customer
#     can check. The cost is that a tank sitting for eight months is invoiced for none of
#     them until it leaves.
#   * RUNNING  — charged period by period while the tank is still inside, with the tail
#     billed when it finally leaves.
#
# Orthogonal to ``Depot Contract.payment_type`` (Cash/TOP): the mode decides WHEN the days
# are charged, the payment type decides how the resulting charge is invoiced.
MODE_ON_EXIT = "Saat Tank Keluar"
MODE_RUNNING = "Berjalan (Periodik)"
DEFAULT_MODE = MODE_ON_EXIT

# Source labels (also the report's Sumber column).
SRC_GATE = "Gate Entry"
SRC_MOVEMENT = "Container Movement"
SRC_MASTER = "Container"
SRC_NONE = "-"

MASTER_FIELDS = ["in_date", "out_date", "status"]


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
def count_mode() -> str:
	"""The site's day-count convention (defaults to charging both ends)."""
	return frappe.db.get_single_value(SETTINGS, "storage_day_count") or DEFAULT_COUNT_MODE


def default_free_days() -> int:
	return cint(frappe.db.get_single_value(SETTINGS, "storage_free_days"))


def free_days_for(customer: str | None) -> int:
	"""Free storage days for one tank owner.

	The customer's Active contract wins when it states a figure; **0 on the contract means
	"ikut default global"**, not "no free days" — an Int field cannot hold "unset", and a
	contract that genuinely grants none is expressed by setting the global to 0. Documented
	on the field itself so it cannot be read as a bug.
	"""
	if customer:
		contract = frappe.db.get_value(
			"Depot Contract", {"customer": customer, "status": "Active"}, "name", order_by="valid_from desc"
		)
		if contract:
			own = cint(frappe.db.get_value("Depot Contract", contract, "storage_free_days"))
			if own:
				return own
	return default_free_days()


def billing_mode_for(customer: str | None) -> str:
	"""How this tank owner's storage is charged (contract first, then the global default).

	The contract field is a Select, so **empty genuinely means "ikut default"** — unlike
	free days, there is no zero to confuse it with.
	"""
	if customer:
		contract = frappe.db.get_value(
			"Depot Contract", {"customer": customer, "status": "Active"}, "name", order_by="valid_from desc"
		)
		if contract:
			own = frappe.db.get_value("Depot Contract", contract, "storage_billing_mode")
			if own:
				return own
	return frappe.db.get_single_value(SETTINGS, "storage_billing_mode") or DEFAULT_MODE


def billable_now(period: dict, mode: str) -> bool:
	"""May this stay be charged yet, under the owner's mode?

	Under ON_EXIT an open stay is not billable at all — the customer agreed to be charged
	when the tank leaves, so a running accrual for them is simply not a receivable yet.
	Under RUNNING everything is: the open stay accrues, and a CLOSED one still has to be
	billable or the last days before gate-out would never be charged to anyone.
	"""
	return mode != MODE_ON_EXIT or bool(period.get("end"))


# --------------------------------------------------------------------------- #
# Stay periods — one dict per visit: {start, end, source, ref}
#
# ``start`` is the day the tank came in, ``end`` the day it left (None while it is still
# inside). ``ref`` is the document the dates were
# read from (a Gate Entry name), or None for the derived sources.
# --------------------------------------------------------------------------- #
def stay_periods(container: str, container_no: str | None = None) -> list[dict]:
	"""Every recorded depot visit of one tank, oldest first."""
	container_no = container_no or frappe.db.get_value("Container", container, "container_no")
	return _with_master(
		_raw_periods(container, container_no),
		frappe.db.get_value("Container", container, MASTER_FIELDS, as_dict=True),
	)


def _raw_periods(container: str, container_no: str | None) -> list[dict]:
	return _gate_entry_periods(container_no) or _movement_periods(container) or _master_periods(container)


def visit_for(container: str, day, container_no: str | None = None, *, ref: str | None = None, earlier: bool = False):
	"""The stay ``day`` belongs to: ``(period, lo, hi)``, or ``(None, None, None)``.

	``period`` is the :func:`stay_periods` row (what the Storage Charge ledger is keyed on);
	``lo`` / ``hi`` are its window, from the day in to the day out (or the next arrival; ``hi``
	None while the tank is still inside).

	``ref`` (a Gate Entry) wins when it names a visit. A day outside every window falls to the
	next arrival, or with ``earlier`` to the last one before it: an EIR-In dated before its tank
	came in belongs to the visit it was raised for, an EIR-Out dated after it left to the one
	it closed.
	"""
	container_no = container_no or frappe.db.get_value("Container", container, "container_no")
	final = stay_periods(container, container_no)
	windows = [
		(getdate(p["start"]), getdate(p["end"]) if p["end"] else (getdate(final[i + 1]["start"]) if i + 1 < len(final) else None))
		for i, p in enumerate(final)
	]
	day = getdate(day)
	pick = next((i for i, p in enumerate(final) if ref and p.get("ref") == ref), None)
	if pick is None:
		pick = next((i for i, (lo, hi) in enumerate(windows) if lo <= day and (hi is None or day <= hi)), None)
	if pick is None:
		before = [i for i, (lo, _hi) in enumerate(windows) if lo <= day]
		after = [i for i, (lo, _hi) in enumerate(windows) if lo > day]
		pick = (before[-1] if before else None) if earlier else (after[0] if after else None)
	if pick is None:
		return None, None, None
	return final[pick], *windows[pick]


def periods_for_many(containers: list[dict]) -> dict[str, list[dict]]:
	"""``{container: stay periods}`` for many tanks in ONE Gate Entry query.

	The report walks every tank a principal owns, and Gate Entry answers for almost all of
	them, so asking per container would be a query per tank for no new information. Only
	the tanks Gate Entry does not know about fall through to the per-container fallbacks.

	``containers`` is a list of ``{"name", "container_no"}`` dicts.
	"""
	by_no: dict[str, list[dict]] = {}
	numbers = [c["container_no"] for c in containers if c.get("container_no")]
	if numbers:
		for r in frappe.get_all(
			"Gate Entry",
			filters={
				"container_no": ["in", numbers],
				"docstatus": ["<", 2],
				"status": ["!=", "Cancelled"],
				"gate_in_timestamp": ["is", "set"],
			},
			fields=["name", "container_no", *_GATE_FIELDS],
			order_by="gate_in_timestamp asc",
		):
			by_no.setdefault(r.container_no, []).append(_gate_period(r))
	names = [c["name"] for c in containers]
	master = {r.name: r for r in frappe.get_all(
		"Container", filters={"name": ["in", names or [""]]}, fields=["name", *MASTER_FIELDS],
	)}
	out = {}
	for c in containers:
		out[c["name"]] = _with_master(
			by_no.get(c.get("container_no"))
			or _movement_periods(c["name"])
			or _master_periods(c["name"]),
			master.get(c["name"]),
		)
	return out


def _with_master(periods: list[dict], tank) -> list[dict]:
	"""A visit with no gate record takes the master's ``in_date`` / ``out_date``.

	That is a tank injected by import: its Container Movement is stamped when the import ran,
	so the operator-set dates on the master are the better story. Only the LAST visit, since
	both fields are overwritten on re-entry, and a date that does not fit — before the
	previous visit's exit, or out before in — is ignored. A gated visit never takes them: its
	Gate Entry carries the same bon dates itself.
	"""
	out = list(periods)
	if not out or not tank or out[-1].get("ref"):
		return out
	last = dict(out[-1])
	prev_end = out[-2]["end"] if len(out) > 1 else None
	if tank.in_date and not (prev_end and getdate(tank.in_date) <= getdate(prev_end)):
		if getdate(tank.in_date) != getdate(last["start"]):
			last["source"] = SRC_MASTER
		last["start"] = tank.in_date
	if tank.status == GATE_OUT and tank.out_date and getdate(tank.out_date) >= getdate(last["start"]):
		if not last["end"] or getdate(tank.out_date) != getdate(last["end"]):
			last.update(end=tank.out_date, source=SRC_MASTER)
	if last["end"] and getdate(last["end"]) < getdate(last["start"]):
		return out
	return out[:-1] + [last]


# Gate Entry: the bon dates, and the registration stamps only for a record written before
# the dates existed (patch v1_19.in_out_dates fills them in).
_GATE_FIELDS = ["in_date", "out_date", "gate_in_timestamp", "gate_out_timestamp"]


def _gate_period(r) -> dict:
	return {
		"start": r.in_date or r.gate_in_timestamp,
		"end": r.out_date or r.gate_out_timestamp,
		"source": SRC_GATE,
		"ref": r.name,
	}


def _gate_entry_periods(container_no: str | None) -> list[dict]:
	if not container_no:
		return []
	rows = frappe.get_all(
		"Gate Entry",
		filters={
			"container_no": container_no,
			"docstatus": ["<", 2],
			"status": ["!=", "Cancelled"],
			"gate_in_timestamp": ["is", "set"],
		},
		fields=["name", *_GATE_FIELDS],
		order_by="gate_in_timestamp asc",
	)
	return [_gate_period(r) for r in rows]


def _movement_periods(container: str) -> list[dict]:
	"""Visits rebuilt from the status audit trail.

	A period OPENS on the first move into a present status (In_Depot / Available) and
	CLOSES on the move to Gate_Out — closes, not disappears. The older reading threw the
	interval away at gate-out, which is why a tank that had already left counted zero days:
	exactly the tanks a "charge after it leaves" run is looking for.
	"""
	moves = frappe.get_all(
		"Container Movement",
		filters={"container": container, "event_type": ["in", ["Status", "Combined"]]},
		fields=["to_status", "movement_timestamp"],
		order_by="movement_timestamp asc",
	)
	periods, start = [], None
	for m in moves:
		if m.to_status in PRESENT and start is None:
			start = m.movement_timestamp
		elif m.to_status == GATE_OUT and start is not None:
			periods.append({"start": start, "end": m.movement_timestamp, "source": SRC_MOVEMENT, "ref": None})
			start = None
	if start is not None:
		periods.append({"start": start, "end": None, "source": SRC_MOVEMENT, "ref": None})
	return periods


def _master_periods(container: str) -> list[dict]:
	row = frappe.db.get_value("Container", container, MASTER_FIELDS, as_dict=True)
	if not row or not row.in_date:
		return []
	end = row.out_date if row.status == GATE_OUT else None
	return [{"start": row.in_date, "end": end, "source": SRC_MASTER, "ref": None}]


# --------------------------------------------------------------------------- #
# Day arithmetic
# --------------------------------------------------------------------------- #
def _days(start, end) -> int:
	"""Inclusive day count of [start, end]; 0 when the interval is empty."""
	return max(0, date_diff(end, start) + 1)


def last_billable_day(period: dict, cutoff, mode: str | None = None):
	"""The last day of a stay that may be charged.

	For an OPEN stay that is the cutoff the operator asked for (never past today — a depot
	cannot charge for a night that has not happened). For a CLOSED stay it is the departure
	day, minus one under the ``no-out-day`` convention.
	"""
	mode = mode or count_mode()
	if not period.get("end"):
		return min(getdate(cutoff), getdate(today()))
	out = getdate(period["end"])
	return out if mode == COUNT_BOTH else add_days(out, -1)


def measure(period: dict, from_date, to_date, free_days=0, billed_until=None, mode=None) -> dict:
	"""Turn one stay into its day figures.

	Returns ``in_date`` / ``out_date`` (the physical dates, unclipped — an operator checking
	a bill wants to see the real gate dates, not the window's edges), ``stay_days`` (the
	whole stay to date, what "sudah menginap berapa hari" means), and ``chargeable_days``
	(the part of it inside the window, after free days and after whatever was already
	billed).

	Free days are counted from the START OF THE STAY, per visit — that is what a free-day
	grant means: the first N days of this visit are free. Applying them per window instead
	would hand the customer a fresh grace period every month.
	"""
	mode = mode or count_mode()
	from_date, to_date = getdate(from_date), getdate(to_date)
	start = getdate(period["start"])
	last = last_billable_day(period, to_date, mode)

	charge_from = add_days(start, cint(free_days))
	if billed_until:
		charge_from = max(charge_from, add_days(getdate(billed_until), 1))

	lo, hi = max(charge_from, from_date), min(last, to_date)
	return {
		"in_date": start,
		"out_date": getdate(period["end"]) if period.get("end") else None,
		"is_open": not period.get("end"),
		"source": period.get("source", SRC_NONE),
		"ref": period.get("ref"),
		"stay_days": _days(start, last),
		"free_days": cint(free_days),
		"chargeable_days": _days(lo, hi) if hi >= lo else 0,
		"charge_from": lo if hi >= lo else None,
		"charge_to": hi if hi >= lo else None,
	}


def days_in_depot(container: str, from_date, to_date, *, free_days=0, billed_until=None) -> int:
	"""Total chargeable days for one tank inside a window, across every visit.

	The drop-in accurate replacement for the old per-container day count: it sums ALL visits
	in the window (a tank that came, left and came back is charged for both stays) and it
	does not lose a stay that has already ended.
	"""
	container_no = frappe.db.get_value("Container", container, "container_no")
	mode = count_mode()
	return sum(
		measure(p, from_date, to_date, free_days, billed_until, mode)["chargeable_days"]
		for p in stay_periods(container, container_no)
	)
