"""The User form trim (public/js/user.js §3) hides fields by name — check they still exist.

The list is JavaScript, so nothing in Python fails when Frappe renames or drops one of those
sections on the next upgrade: the form would simply come back with Security Settings and the
Sessions tab on it, and nobody would notice until a customer went looking. This reads the
names straight out of the script and asserts each one is still a real Section/Tab Break on
the User doctype.
"""

import re
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

_JS = Path(frappe.get_app_path("container_depot", "public", "js", "user.js"))


def _hidden_fieldnames() -> list[str]:
	"""Both lists in §3: the Settings sections and the tabs (hidden a different way)."""
	js = _JS.read_text()
	names = []
	for const in ("SELF_VIEW_HIDDEN_TABS", "SELF_VIEW_HIDDEN"):
		body = re.search(rf"const {const} = \[(.*?)\];", js, re.S)
		if body:
			names += re.findall(r'"([^"]+)"', body.group(1))
	return names


class TestUserFormTrim(FrappeTestCase):
	def test_hidden_sections_still_exist(self):
		names = _hidden_fieldnames()
		self.assertTrue(names, "SELF_VIEW_HIDDEN not found in user.js")
		meta = frappe.get_meta("User")
		for fieldname in names:
			df = meta.get_field(fieldname)
			self.assertIsNotNone(df, f"User.{fieldname} is gone — user.js §3 hides nothing")
			self.assertIn(df.fieldtype, ("Section Break", "Tab Break"), fieldname)

	def test_change_password_is_not_hidden(self):
		"""The one section the trim must leave standing."""
		self.assertNotIn("change_password", _hidden_fieldnames())
		self.assertIsNotNone(frappe.get_meta("User").get_field("new_password"))
