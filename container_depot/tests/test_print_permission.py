"""Every role that may READ a depot document may also PRINT it — and EMAIL it.

`print` and `email` are each their own permission flag in Frappe, and the seeder's compact
grammar expanded `r` to read+report+export while quietly omitting both. Because the first
Custom DocPerm on a doctype makes Frappe ignore that doctype's shipped permissions
wholesale, a flag the seeder never sets is a flag nobody has — the Desk offered no Print
action on ANY Container Depot document (fixed 2026-08-27, patch v0_83) and then no Email
action either (fixed 2026-09-14, patch v0_97). This pins both halves of each fix: the
grammar, and the rows already in the site.

Sending also needs the standard `Inbox User` role, which is what actually reads
`Email Account`; that half is pinned in test_role_profiles.py.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.install import _PERM_LETTERS, _perm_dict


class TestPrintPermission(FrappeTestCase):
	def test_the_read_bundle_carries_print(self):
		self.assertIn("print", _PERM_LETTERS["r"])
		self.assertEqual(_perm_dict("r", False).get("print"), 1)

	def test_the_read_bundle_carries_email(self):
		"""Reversed 2026-09-14 on the user's instruction: mailing the customer a bon, an
		EIR or an invoice IS the job, and `export` already hands over strictly more."""
		self.assertIn("email", _PERM_LETTERS["r"])
		self.assertEqual(_perm_dict("r", False).get("email"), 1)

	def test_no_depot_doctype_is_readable_but_unprintable(self):
		self.assertEqual(self._readable_but_missing("print"), [])

	def test_no_depot_doctype_is_readable_but_unmailable(self):
		self.assertEqual(self._readable_but_missing("email"), [])

	def _readable_but_missing(self, flag: str) -> list[str]:
		doctypes = frappe.get_all(
			"DocType", filters={"module": "Container Depot", "istable": 0}, pluck="name"
		)
		self.assertTrue(doctypes)
		return [
			dt
			for dt in doctypes
			if frappe.db.count("Custom DocPerm", {"parent": dt, "read": 1})
			and not frappe.db.count("Custom DocPerm", {"parent": dt, flag: 1})
		]

	def test_a_field_role_can_print_an_eir(self):
		"""The symptom that started this: no Print action on a submitted EIR."""
		self.assertTrue(
			frappe.db.exists("Custom DocPerm", {"parent": "Inspection", "role": "Team EIR", "print": 1})
		)
