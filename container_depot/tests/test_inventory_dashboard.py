"""Guard the Container Inventory dashboard filter format.

Number Card / Dashboard Chart widgets require 4-element ``[doctype, field, op,
value]`` filters; a compact 3-element spec is mis-parsed by the desk as
``[doctype, field, op]`` and throws ``Invalid filter: <op>``. These tests pin the
qualifier and every seeded card/chart spec so the regression can't return.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.install import (
	INVENTORY_CHARTS,
	INVENTORY_NUMBER_CARDS,
	ORDER_NUMBER_CARDS,
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
		for card in INVENTORY_NUMBER_CARDS + ORDER_NUMBER_CARDS:
			for f in _qualify_filters(card.get("filters_json"), card["document_type"]):
				self.assertGreaterEqual(len(f), 4, f"{card['label']}: {f}")
				self.assertEqual(f[0], card["document_type"], f"{card['label']}: {f}")

	def test_every_chart_spec_qualifies_to_widget_shape(self):
		for chart in INVENTORY_CHARTS:
			for f in _qualify_filters(chart.get("filters_json"), chart["document_type"]):
				self.assertGreaterEqual(len(f), 4, f"{chart['chart_name']}: {f}")
				self.assertEqual(f[0], chart["document_type"], f"{chart['chart_name']}: {f}")


class TestInventoryDashboardSpecsAreValid(FrappeTestCase):
	"""Every seeded card/chart must still address a real doctype, a real field and —
	for a Select — a real option.

	This is the guard the dashboard lacked: a Number Card whose filter names a Select
	option that has since been renamed does not error anywhere, it just counts zero
	forever (exactly what happened to the ``inventory_stage = Cleaning`` cards dropped
	in v0_59). A silent zero is indistinguishable from "no work outstanding", so the
	only place it can be caught is here.
	"""

	# Present on every doctype but absent from ``meta.fields``.
	STANDARD_FIELDS = {"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx", "parent"}
	# Operators whose value is compared against the field's own options.
	VALUE_OPS = {"=", "!=", "in", "not in"}

	def _specs(self):
		for card in INVENTORY_NUMBER_CARDS + ORDER_NUMBER_CARDS:
			yield card["label"], card
		for chart in INVENTORY_CHARTS:
			yield chart["chart_name"], chart

	def _check_field(self, doctype, fieldname, where):
		if fieldname in self.STANDARD_FIELDS:
			return None
		field = frappe.get_meta(doctype).get_field(fieldname)
		self.assertIsNotNone(field, f"{where}: {doctype} has no field '{fieldname}'")
		return field

	def test_every_spec_targets_an_existing_doctype(self):
		for where, spec in self._specs():
			self.assertTrue(
				frappe.db.exists("DocType", spec["document_type"]),
				f"{where}: unknown doctype {spec['document_type']}",
			)

	def test_every_filter_names_a_real_field_and_a_real_option(self):
		for where, spec in self._specs():
			doctype = spec["document_type"]
			for f in _qualify_filters(spec.get("filters_json"), doctype):
				_, fieldname, op, value = f[0], f[1], f[2], f[3]
				field = self._check_field(doctype, fieldname, where)
				if not field or field.fieldtype != "Select" or op not in self.VALUE_OPS:
					continue
				options = {o.strip() for o in (field.options or "").split("\n")}
				for v in (value if isinstance(value, list) else [value]):
					self.assertIn(v, options, f"{where}: '{v}' is not an option of {doctype}.{fieldname}")

	def test_every_chart_groups_or_series_on_a_real_field(self):
		for chart in INVENTORY_CHARTS:
			for key in ("group_by_based_on", "based_on"):
				if chart.get(key):
					self._check_field(chart["document_type"], chart[key], chart["chart_name"])


class TestInventoryWorkspaceMatchesSeeder(FrappeTestCase):
	"""The Container Inventory workspace references cards/charts BY NAME, in three
	places each (``number_cards`` / ``charts`` and again inside ``content``).

	A reference with no seeded record renders as an empty box on the dashboard, and a
	seeded record no one references is invisible work. Both directions are pinned here
	because nothing else connects the JSON to the Python list.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		import json

		path = frappe.get_app_path(
			"container_depot", "container_depot", "workspace", "container_inventory",
			"container_inventory.json",
		)
		cls.ws = json.load(open(path))
		cls.content = json.loads(cls.ws["content"])

	def _content_names(self, block_type, key):
		return {b["data"][key] for b in self.content if b["type"] == block_type}

	def test_number_cards_match_the_seeder_exactly(self):
		seeded = {c["label"] for c in INVENTORY_NUMBER_CARDS + ORDER_NUMBER_CARDS}
		self.assertEqual({c["number_card_name"] for c in self.ws["number_cards"]}, seeded)
		self.assertEqual(self._content_names("number_card", "number_card_name"), seeded)

	def test_charts_match_the_seeder_exactly(self):
		seeded = {c["chart_name"] for c in INVENTORY_CHARTS}
		self.assertEqual({c["chart_name"] for c in self.ws["charts"]}, seeded)
		self.assertEqual(self._content_names("chart", "chart_name"), seeded)

	def test_every_shortcut_block_has_a_shortcut_row(self):
		declared = {s["label"] for s in self.ws["shortcuts"]}
		self.assertEqual(self._content_names("shortcut", "shortcut_name"), declared)
