"""report_kit — the shared "Cari" box and the date range on a chosen date column.

Pure functions over finished rows: no fixtures, nothing written.
"""

from __future__ import annotations

from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot import report_kit

COLUMNS = [
	{"fieldname": "tank_no", "fieldtype": "Link"},
	{"fieldname": "order_date", "fieldtype": "Date"},
	{"fieldname": "wash_date", "fieldtype": "Datetime"},
	{"fieldname": "remarks", "fieldtype": "Data"},
]
ROWS = [
	{"tank_no": "UTCU0000001", "order_date": "2026-09-01", "wash_date": "2026-09-20 14:00:00", "remarks": "Ethanol OAK1"},
	{"tank_no": "UTCU0000002", "order_date": "2026-09-15", "wash_date": None, "remarks": "Glycerine OAK2"},
]


def _tanks(filters):
	return [r["tank_no"] for r in report_kit.finish(COLUMNS, list(ROWS), filters, default="order_date")[1]]


class TestReportKit(FrappeTestCase):
	def test_range_defaults_to_the_reports_own_date(self):
		self.assertEqual(_tanks({"from_date": "2026-09-10"}), ["UTCU0000002"])

	def test_range_follows_the_chosen_column_and_drops_rows_without_that_date(self):
		filters = {"date_based_on": "wash_date", "from_date": "2026-09-20", "to_date": "2026-09-20"}
		# A Datetime counts by its day; a row with no wash date is never "between" anything.
		self.assertEqual(_tanks(filters), ["UTCU0000001"])

	def test_sql_prefilter_only_on_its_own_column(self):
		filters = {"from_date": "2026-09-01", "to_date": "2026-09-30"}
		self.assertEqual(report_kit.native_range(filters, "order_date"), ("2026-09-01", "2026-09-30"))
		filters["date_based_on"] = "wash_date"
		self.assertEqual(report_kit.native_range(filters, "order_date"), (None, None))

	def test_search_needs_every_word_somewhere_in_the_row(self):
		self.assertEqual(_tanks({"search": "ethanol oak1"}), ["UTCU0000001"])
		self.assertEqual(_tanks({"search": "0002"}), ["UTCU0000002"])
		self.assertEqual(_tanks({"search": "ethanol oak2"}), [])
