"""Keeping the Storage Charge ledger in step with what the gate recorded.

One :doc:`Storage Charge` per depot visit, derived from the same
:func:`storage.stay_periods` the report reads — so the ledger and the day count can never
tell two different stories.

**Derived, not entered.** Nothing here is a user's typing: the visit's dates come from the
Gate Entry, the day figures from :mod:`container_depot.storage`, and the status from those
two. That is why :func:`sync` is safe to re-run on any container at any time — it converges
on what the gate says, and the only fields it will not touch are the ones billing owns
(``billed_until``, ``billed_days``, ``sales_invoice``).

**Idempotent by key.** A visit is identified by its Gate Entry when it has one, and by
``container + tanggal masuk`` when it does not. Re-running never duplicates a visit, and a
corrected gate timestamp updates the record it already has rather than opening a second one.

Called from ``Container.on_update`` whenever a tank's status changes (arrival, departure)
and nightly from the scheduler, which is what heals the records nobody's status change
happened to touch — a backdated Gate Entry, a hand-fixed timestamp.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, cint, date_diff, getdate, today

from container_depot import storage
from container_depot.container_depot.container_status import GATE_OUT, PRESENT

DOCTYPE = "Storage Charge"

# Statuses. "Paid" here means the visit's days have been taken into a bill — the money's
# own state lives on the Sales Invoice, and once billing is wired to this ledger the two
# can be reconciled. Kept in the user's vocabulary (paid/unpaid) rather than the code's.
RUNNING = "Berjalan"
UNPAID = "Unpaid"
PARTLY = "Partly Paid"
PAID = "Paid"


def _key(container: str, period: dict) -> dict:
	"""Filters identifying the one Storage Charge row for this visit."""
	if period.get("ref"):
		return {"gate_entry": period["ref"]}
	return {"container": container, "date_in_key": _date_in_key(period)}


def _date_in_key(period: dict) -> str:
	return str(getdate(period["start"]))


def _status(period: dict, unbilled: int, billed: int) -> str:
	"""Berjalan while the tank is inside; paid/unpaid once the visit is closed.

	An open visit is never Unpaid, however many days it has run: the visit is not finished,
	so nothing about it is final. What it has outstanding is on ``unbilled_days``, which is
	the honest number either way — and under *Berjalan (Periodik)* that is exactly what the
	next periodic bill picks up.
	"""
	if not period.get("end"):
		return RUNNING
	if unbilled <= 0:
		return PAID
	return PARTLY if billed else UNPAID


def sync(container: str, container_no: str | None = None) -> list[str]:
	"""Create/refresh the ledger rows for one tank's visits. Returns their names."""
	row = frappe.db.get_value(
		"Container", container, ["container_no", "principal", "depot"], as_dict=True
	)
	if not row:
		return []
	mode = storage.billing_mode_for(row.principal)
	free_days = storage.free_days_for(row.principal)
	count_mode = storage.count_mode()

	names = []
	for period in storage.stay_periods(container, container_no or row.container_no):
		names.append(_upsert(container, row, period, mode, free_days, count_mode))
	_prune(container, names)
	return names


def _prune(container: str, keep: list[str]) -> None:
	"""Drop rows for visits the gate records no longer describe.

	A tank's dates can move to a better source — a Gate Entry appears for a visit that had
	only the status trail to go on — and the rows built from the weaker source then describe
	a visit that, as far as the records now go, never happened. Left alone they would be
	counted twice.

	**A row carrying billing state is never dropped.** Once a day has been billed the row is
	evidence, and evidence that contradicts the current records is something a human has to
	look at — not something a nightly sweep may delete.
	"""
	for r in frappe.get_all(
		DOCTYPE, filters={"container": container}, fields=["name", "billed_until", "sales_invoice"]
	):
		if r.name in keep or r.billed_until or r.sales_invoice:
			continue
		frappe.db.delete(DOCTYPE, {"name": r.name})


def _upsert(container, row, period, mode, free_days, count_mode) -> str:
	existing = frappe.db.get_value(DOCTYPE, _key(container, period), ["name", "billed_until"], as_dict=True)
	billed_until = existing.billed_until if existing else None

	# Days, measured over the visit's own span rather than a reporting window: this ledger
	# is about the visit, and a window belongs to whoever is billing.
	last = storage.last_billable_day(period, getdate(today()), count_mode)
	measured = storage.measure(
		period, getdate(period["start"]), last,
		free_days=free_days, billed_until=billed_until, mode=count_mode,
	)
	billed = _billed_days(period, free_days, billed_until, count_mode)
	values = {
		"container": container,
		"principal": row.principal,
		"depot": row.depot,
		"gate_entry": period.get("ref"),
		"source": period.get("source"),
		"date_in": period["start"],
		"date_out": period.get("end"),
		"date_in_key": _date_in_key(period),
		"stay_days": measured["stay_days"],
		"unbilled_days": measured["chargeable_days"],
		"billed_days": billed,
		"status": _status(period, measured["chargeable_days"], billed),
	}
	if existing:
		# billing_mode / free_days are snapshots taken when the visit opened — a contract
		# renegotiated mid-stay must not silently restate what an existing visit was owed.
		frappe.db.set_value(DOCTYPE, existing.name, values, update_modified=False)
		return existing.name
	doc = frappe.get_doc({
		"doctype": DOCTYPE, "billing_mode": mode, "free_days": free_days, **values
	})
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _billed_days(period, free_days, billed_until, count_mode) -> int:
	"""Chargeable days of this visit that the watermark already covers."""
	if not billed_until:
		return 0
	start = getdate(period["start"])
	last = storage.last_billable_day(period, getdate(today()), count_mode)
	charge_from = add_days(start, cint(free_days))
	hi = min(getdate(billed_until), last)
	return max(0, date_diff(hi, charge_from) + 1) if hi >= charge_from else 0


def sync_all(principal: str | None = None) -> int:
	"""Refresh every tank that could have a visit. Returns the row count touched."""
	filters = {"status": ["in", PRESENT + (GATE_OUT,)]}
	if principal:
		filters["principal"] = principal
	touched = 0
	for c in frappe.get_all("Container", filters=filters, fields=["name", "container_no"]):
		touched += len(sync(c.name, c.container_no))
	frappe.db.commit()
	return touched


def on_container_status_change(doc, method=None):
	"""``Container.on_update`` hook — a tank arriving or leaving opens/closes a visit."""
	try:
		sync(doc.name, doc.get("container_no"))
	except Exception:
		# The ledger must never be able to block a gate move. A missed visit is repaired by
		# the nightly sweep; a refused gate-in is a truck stuck at the gate.
		frappe.log_error(frappe.get_traceback(), "Storage Charge sync failed")
