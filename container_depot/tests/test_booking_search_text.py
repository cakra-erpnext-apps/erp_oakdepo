"""The booking list's Cari box searches one column; this pins what goes into it."""

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.container_depot.doctype.container_booking.container_booking import build_search_text


class TestBookingSearchText(FrappeTestCase):
	def test_header_and_row_values_in_one_deduplicated_line(self):
		doc = frappe._dict(
			name="BKG-IN-2026-00001", customer="Cakra", principal="Cakra", reff_doc="PL-SO/01",
			do_reference=None, items=[
				frappe._dict(container_no="OAKU2400291", emkl="Trans Jaya", truck_plate="B 1234 XY"),
				frappe._dict(container_no="OAKU2400292", emkl="Trans Jaya"),
			],
		)
		self.assertEqual(
			build_search_text(doc),
			"BKG-IN-2026-00001 · Cakra · PL-SO/01 · OAKU2400291 · Trans Jaya · B 1234 XY · OAKU2400292",
		)
