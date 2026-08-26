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

1. ``Gate Entry`` — one record spans a whole visit (``gate_in_timestamp`` +
   ``gate_out_timestamp``), written at the gate by security, and there is one per visit.
   The only source that can describe a tank that came, left, and came back.
2. ``Container Movement`` — the status audit trail. Timestamped when the status was
   *saved*, not when the truck actually moved, so it is a fallback: right to the day for
   same-day data entry, wrong for anything entered late.
3. ``Container.eir_in_date`` / ``eir_out_date`` — last resort, and only ever the LAST
   visit (both fields are overwritten on re-entry).

Each row reports which source it used, because a storage bill that cannot be traced to a
gate record is a bill the customer will argue with.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, cint, date_diff, getdate, today

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
SRC_EIR = "EIR (Container)"
SRC_NONE = "-"


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
# Stay periods — one dict per visit: {start, end, source, ref, open}
#
# ``end`` is None while the tank is still inside. ``ref`` is the document the dates were
# read from (a Gate Entry name), or None for the derived sources.
# --------------------------------------------------------------------------- #
def stay_periods(container: str, container_no: str | None = None) -> list[dict]:
	"""Every recorded depot visit of one tank, oldest first."""
	container_no = container_no or frappe.db.get_value("Container", container, "container_no")
	return (
		_gate_entry_periods(container_no)
		or _movement_periods(container)
		or _eir_periods(container)
	)


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
			fields=["name", "container_no", "gate_in_timestamp", "gate_out_timestamp"],
			order_by="gate_in_timestamp asc",
		):
			by_no.setdefault(r.container_no, []).append({
				"start": r.gate_in_timestamp,
				"end": r.gate_out_timestamp,
				"source": SRC_GATE,
				"ref": r.name,
			})
	out = {}
	for c in containers:
		out[c["name"]] = (
			by_no.get(c.get("container_no"))
			or _movement_periods(c["name"])
			or _eir_periods(c["name"])
		)
	return out


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
		fields=["name", "gate_in_timestamp", "gate_out_timestamp"],
		order_by="gate_in_timestamp asc",
	)
	return [
		{
			"start": r.gate_in_timestamp,
			"end": r.gate_out_timestamp,
			"source": SRC_GATE,
			"ref": r.name,
		}
		for r in rows
	]


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


def _eir_periods(container: str) -> list[dict]:
	row = frappe.db.get_value(
		"Container", container, ["eir_in_date", "eir_out_date", "status"], as_dict=True
	)
	if not row or not row.eir_in_date:
		return []
	end = row.eir_out_date if row.status == GATE_OUT else None
	return [{"start": row.eir_in_date, "end": end, "source": SRC_EIR, "ref": None}]


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
