# Copyright (c) 2026, Oak Depot Team and contributors
# For license information, please see license.txt

"""The order every PWA worklist is shown in.

Three tiers, and they answer three different questions in the order an operator asks them:

1. **Prioritas gate-out** — tanks the customer has already given a lift-on date for, nearest
   first. This is the only tier with a deadline attached to it, so it outranks everything
   else: a wash finished a day late on a tank nobody is coming for costs nothing, the same
   day lost on a tank on a truck's schedule costs a truck.
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

# Sorts after every real lift-on date, so an unstamped row falls to the BOTTOM of tier 1
# instead of the top — which is where an empty value would otherwise land it.
_NO_LIFT_ON = "2999-12-31"


def sort_by_priority(items: list, started, start=0, page_length=None) -> list:
	"""Order ``items`` by the three tiers above, then slice one page out of them.

	``started`` is a predicate over a row — each worklist passes its own test for "sedang
	dikerjakan" (a status, or the stamp its Mulai writes), so the order always agrees with
	the Belum / Dikerjakan split the same screen shows.

	Python's sort is stable, so whatever the query's own ``order_by`` decided still settles
	ties inside a tier — that is where "oldest first" comes from, not from this function.
	"""
	items.sort(key=lambda r: (getdate(r.get("target_lift_on") or _NO_LIFT_ON), 0 if started(r) else 1))
	pl = cint(page_length or 0)
	return items[cint(start):cint(start) + pl] if pl else items[cint(start):]
