"""Shared filters for the depot's script reports: one "Cari" box and one date range.

Every register used to filter its date range on ONE fixed column (order date, survey date,
pick-up date...), while its rows carry several dates. "Which tanks finished cleaning last
week" could not be asked of a report that only knew order dates. So the range now applies
to the date column the user picks (``date_based_on``), and the free-text ``search`` looks
through every text cell of the row — tank number, document, customer, remarks — so nobody
has to know which filter field holds the thing they are looking for.

The browser half is ``public/js/report_kit.js`` (the filter fields + the Excel-style header).

Wiring a report::

    frm, to = report_kit.native_range(filters, "order_date")   # SQL pre-filter, optional
    ...
    return report_kit.finish(columns, rows, filters, default="order_date")

``native_range`` hands back the range only while it is applied to the column the report's
own SQL filters on, so that column can still be narrowed in the database. For any other
column the SQL leaves the date alone and :func:`finish` filters the finished rows.
"""

from __future__ import annotations

from frappe.utils import getdate

DATE_TYPES = ("Date", "Datetime")
NUMBER_TYPES = ("Int", "Float", "Currency", "Percent")


def _dress(columns):
	"""Excel-sheet reading: every heading fits its column on one line (the grid cannot grow
	a header row, so a wrapped one is cut off), dates centred, text left. The grid would
	otherwise guess right-alignment for a text column whose first cell happens to be empty."""
	for c in columns:
		label = c.get("label") or ""
		# ...and a full dd-mm-yyyy (hh:mm) fits too, instead of "21-09-2…".
		floor = {"Date": 110, "Datetime": 155}.get(c.get("fieldtype"), 0)
		c["width"] = max(int(c.get("width") or 0), len(label) * 8 + 30, floor)
		if c.get("fieldtype") in DATE_TYPES:
			c.setdefault("align", "center")
		elif c.get("fieldtype") not in NUMBER_TYPES:
			c.setdefault("align", "left")
	return columns


def basis(filters, default: str | None) -> str | None:
	"""The date column the range applies to: the user's pick, else the report's default."""
	return (filters or {}).get("date_based_on") or default


def native_range(filters, native: str, default: str | None = None):
	"""``(from_date, to_date)`` for the report's SQL, or ``(None, None)`` when the range is
	aimed at another column (the rows are then filtered by :func:`finish`)."""
	filters = filters or {}
	if basis(filters, default or native) != native:
		return None, None
	return filters.get("from_date") or None, filters.get("to_date") or None


def _day(value):
	try:
		return getdate(value) if value else None
	except Exception:
		return None


def finish(columns, rows, filters, default: str | None = None):
	"""Apply the date range (on the chosen column) and the "Cari" text to finished rows."""
	filters = filters or {}
	columns = _dress(columns)
	dates = [c["fieldname"] for c in columns if c.get("fieldtype") in DATE_TYPES]
	field = basis(filters, default or (dates[0] if dates else None))
	frm, to = _day(filters.get("from_date")), _day(filters.get("to_date"))
	if field in dates and (frm or to):
		kept = []
		for r in rows:
			d = _day(r.get(field))
			# A row with no date in that column cannot be "between" anything — dropped, the
			# same way the database drops a NULL from a BETWEEN.
			if d and (not frm or d >= frm) and (not to or d <= to):
				kept.append(r)
		rows = kept

	# Every word must appear somewhere in the row ("ethanol oak1"), in any text cell.
	terms = (filters.get("search") or "").lower().split()
	if terms:
		rows = [r for r in rows if all(
			any(isinstance(v, str) and t in v.lower() for v in r.values()) for t in terms
		)]
	return columns, rows
