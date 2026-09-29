"""The Cari box: search_text follows every change, backfills, and names only real fields."""

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot import list_search

CODE = "ZZ-CARI-TEST"


class TestListSearch(FrappeTestCase):
	def tearDown(self):
		frappe.db.delete("Inspection Damage Code", CODE)
		frappe.db.commit()

	def test_every_listed_field_exists(self):
		"""A typo or a renamed field would silently drop out of the search."""
		for dt, fields in list_search.SEARCH_FIELDS.items():
			if not frappe.db.exists("DocType", dt):
				continue  # a menu whose doctype is not on this site yet
			meta = frappe.get_meta(dt)
			self.assertTrue(meta.has_field(list_search.FIELD), dt)
			for f in fields:
				table, _, child = f.partition(".")
				self.assertTrue(meta.has_field(table), f"{dt}.{table}")
				if child:
					self.assertTrue(frappe.get_meta(meta.get_field(table).options).has_field(child), f"{dt}.{f}")

	def test_build_takes_name_then_fields_and_child_rows_once(self):
		doc = frappe._dict(
			name="BKG-1", customer="Acme", reff_doc="",
			items=[frappe._dict(container_no="OAKU1"), frappe._dict(container_no="OAKU1"), frappe._dict(container_no="OAKU2")],
		)
		self.assertEqual(
			list_search.build(doc, ["customer", "reff_doc", "items.container_no"]),
			"BKG-1 · Acme · OAKU1 · OAKU2",
		)

	def test_follows_insert_save_and_db_set_then_backfills(self):
		get = lambda: frappe.db.get_value("Inspection Damage Code", CODE, list_search.FIELD)
		doc = frappe.get_doc({
			"doctype": "Inspection Damage Code", "code": CODE, "category": "Zzcat", "description": "Penyok",
		}).insert(ignore_permissions=True)
		self.assertEqual(get(), f"{CODE} · Penyok · Zzcat")
		doc.description = "Retak"
		doc.save(ignore_permissions=True)
		self.assertIn("Retak", get())
		doc.db_set("category", "Zzother")  # no save: on_change still runs
		self.assertIn("Zzother", get())

		frappe.db.set_value("Inspection Damage Code", CODE, list_search.FIELD, None)
		list_search.backfill("Inspection Damage Code")
		self.assertEqual(get(), f"{CODE} · Retak · Zzother")
