"""Every role that may READ a depot document may also PRINT it.

`print` is its own permission flag in Frappe, and the seeder's compact grammar expanded
`r` to read+report+export while quietly omitting it. Because the first Custom DocPerm on a
doctype makes Frappe ignore that doctype's shipped permissions wholesale, a flag the seeder
never sets is a flag nobody has — the Desk offered no Print action on ANY Container Depot
document. This pins both halves of the fix: the grammar, and the rows already in the site.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.install import _PERM_LETTERS, _perm_dict


class TestPrintPermission(FrappeTestCase):
	def test_the_read_bundle_carries_print(self):
		self.assertIn("print", _PERM_LETTERS["r"])
		self.assertEqual(_perm_dict("r", False).get("print"), 1)

	def test_email_is_not_in_the_read_bundle(self):
		"""Printing hands a copy to someone already allowed to read; emailing does not."""
		self.assertNotIn("email", _PERM_LETTERS["r"])
		self.assertIsNone(_perm_dict("r", False).get("email"))

	def test_no_depot_doctype_is_readable_but_unprintable(self):
		doctypes = frappe.get_all(
			"DocType", filters={"module": "Container Depot", "istable": 0}, pluck="name"
		)
		self.assertTrue(doctypes)
		unprintable = [
			dt
			for dt in doctypes
			if frappe.db.count("Custom DocPerm", {"parent": dt, "read": 1})
			and not frappe.db.count("Custom DocPerm", {"parent": dt, "print": 1})
		]
		self.assertEqual(unprintable, [])

	def test_a_field_role_can_print_an_eir(self):
		"""The symptom that started this: no Print action on a submitted EIR."""
		self.assertTrue(
			frappe.db.exists("Custom DocPerm", {"parent": "Inspection", "role": "Team EIR", "print": 1})
		)
