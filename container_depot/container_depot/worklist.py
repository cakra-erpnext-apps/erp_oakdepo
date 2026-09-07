# Copyright (c) 2026, Oak Depot Team and contributors
# For license information, please see license.txt

"""The order every PWA worklist is shown in.

Three tiers, and they answer three different questions in the order an operator asks them:

1. **Prioritas tanggal survey** — tanks with a date on them, nearest first. This is the only
   tier with a deadline attached to it, so it outranks everything else: a wash finished a day
   late on a tank nobody is coming for costs nothing, the same day lost on a tank on a truck's
   schedule costs a truck.

   The date is the booking's **survey day**, and the pickup day only when no survey has been
   scheduled (changed 2026-09-07). Preparation is finished at the survey — that is the
   morning the tank has to be down, clean, repaired and inspectable — so sorting by the
   pickup meant every queue was working to a deadline days later than the real one. The
   fallback matters as much as the rule: a booking whose survey day nobody has set yet still
   has a truck coming, and dropping it to the bottom would hide it.
2. **Sedang dikerjakan** — a job already in this operator's hands. Finishing what is open
   beats opening something new, and a half-filled form left at the bottom of a long list is
   how a tank ends up worked twice.
3. **Belum** — everything else, in the order the query gave it (oldest first).

Written once here because five worklists need to agree on it — EIR in, EIR out, cleaning,
M&R, and both halves of the position survey. They drifted before: the three of them each
carried their own copy of the lift-on sort, and the EIR screen then re-sorted the merged
list in the browser and threw the priority away.

Sorted in Python rather than SQL because this Frappe's ``order_by`` validator rejects the
``ifnull(...)`` an unstamped date needs, and because tier 2 is a per-doctype question — each
worklist names its in-progress state differently. The lists are bounded by the tanks standing
in the yard, which is what makes paging in Python affordable.
"""

from __future__ import annotations

from frappe.utils import cint, getdate

# Sorts after every real date, so an unstamped row falls to the BOTTOM of tier 1 instead of
# the top — which is where an empty value would otherwise land it.
_NO_DATE = "2999-12-31"


def priority_date(row):
	"""The deadline this row is worked to: its survey day, else its pickup day.

	One definition, because the sort and the badge have to agree — a queue ordered by one date
	while every row shows another is worse than either alone. Read straight off the row: both
	are stamped there by ``lift_on.push_to_open_orders`` precisely so a paged worklist never
	has to join back to the booking.
	"""
	return row.get("target_survey_on") or row.get("target_lift_on")


def sort_by_priority(items: list, started, start=0, page_length=None) -> list:
	"""Order ``items`` by the three tiers above, then slice one page out of them.

	``started`` is a predicate over a row — each worklist passes its own test for "sedang
	dikerjakan" (a status, or the stamp its Mulai writes), so the order always agrees with
	the Belum / Dikerjakan split the same screen shows.

	Python's sort is stable, so whatever the query's own ``order_by`` decided still settles
	ties inside a tier — that is where "oldest first" comes from, not from this function.
	"""
	items.sort(key=lambda r: (getdate(priority_date(r) or _NO_DATE), 0 if started(r) else 1))
	pl = cint(page_length or 0)
	return items[cint(start):cint(start) + pl] if pl else items[cint(start):]
