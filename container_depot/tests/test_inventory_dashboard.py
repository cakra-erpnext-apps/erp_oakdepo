"""Guard the Container Inventory dashboard filter format.

Number Card / Dashboard Chart widgets require 4-element ``[doctype, field, op,
value]`` filters; a compact 3-element spec is mis-parsed by the desk as
``[doctype, field, op]`` and throws ``Invalid filter: <op>``. These tests pin the
qualifier and every seeded card/chart spec so the regression can't return.
"""

from __future__ import annotations

from frappe.tests.utils import FrappeTestCase

from container_depot.install import (
	INVENTORY_CHARTS,
	INVENTORY_NUMBER_CARDS,
	_qualify_filters,
)


class TestInventoryDashboardFilters(FrappeTestCase):
	def test_qualify_prepends_doctype_to_three_element_filter(self):
		out = _qualify_filters([["inventory_stage", "not in", ["Pre-Arrival"]]], "Container")
		self.assertEqual(out, [["Container", "inventory_stage", "not in", ["Pre-Arrival"]]])

	def test_qualify_passes_through_four_element_filter(self):
		already = [["Container", "status", "=", "Available"]]
		self.assertEqual(_qualify_filters(already, "Container"), already)

	def test_qualify_handles_empty(self):
		self.assertEqual(_qualify_filters(None, "Container"), [])
		self.assertEqual(_qualify_filters([], "Container"), [])

	def test_every_card_spec_qualifies_to_widget_shape(self):
		for card in INVENTORY_NUMBER_CARDS:
			for f in _qualify_filters(card.get("filters_json"), card["document_type"]):
				self.assertGreaterEqual(len(f), 4, f"{card['label']}: {f}")
				self.assertEqual(f[0], card["document_type"], f"{card['label']}: {f}")

	def test_every_chart_spec_qualifies_to_widget_shape(self):
		for chart in INVENTORY_CHARTS:
			for f in _qualify_filters(chart.get("filters_json"), chart["document_type"]):
				self.assertGreaterEqual(len(f), 4, f"{chart['chart_name']}: {f}")
				self.assertEqual(f[0], chart["document_type"], f"{chart['chart_name']}: {f}")
