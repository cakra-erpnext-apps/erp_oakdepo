"""Creating a master from a Link field must open its real form, not a modal.

Frappe's quick-entry modal shows only the fields flagged ``reqd`` /
``allow_in_quick_entry`` and runs without an ``frm`` — so no ``fetch_from``, no
doctype client script. On the masters this depot creates mid-flow that is not a
shortcut but a trap: the operator saves a Customer with 2 of its 54 fields and has
to reopen it on the form to finish the job.

``install.PROPERTY_SETTERS`` turns the modal off for exactly those masters. These
tests hold that line: the flag has to survive every migrate (the setters are
re-applied by ``after_migrate``), and the count of fields the modal *would* have
shown is the evidence a master belongs on the list at all.

Read-only: Property Setters are site configuration, not fixtures, so nothing here
creates or deletes a row.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.install import PROPERTY_SETTERS

# Its whole form is one field, so its modal already IS the form. Listed here so the
# omission reads as a decision rather than an oversight.
FULL_FORM_IN_A_MODAL = "Branch"


def _quick_entry_off_for():
	return [dt for dt, fieldname, prop, value, _t in PROPERTY_SETTERS if fieldname is None and prop == "quick_entry" and value == "0"]


class TestQuickEntryIsOff(FrappeTestCase):
	def test_the_masters_created_mid_flow_are_all_covered(self):
		"""Every master this app reaches from a Link field and that has a modal worth killing."""
		self.assertEqual(
			sorted(_quick_entry_off_for()),
			["Customer", "Item", "Item Price", "Role", "UOM", "User"],
		)

	def test_meta_reports_the_modal_as_disabled(self):
		for doctype in _quick_entry_off_for():
			with self.subTest(doctype=doctype):
				self.assertFalse(
					frappe.get_meta(doctype).quick_entry,
					f"{doctype}: quick entry is back on — Property Setter missing or overwritten",
				)

	def test_branch_keeps_its_modal(self):
		"""Nothing to gain from a page load when the modal shows the whole form."""
		meta = frappe.get_meta(FULL_FORM_IN_A_MODAL)
		editable = [f for f in meta.fields if f.fieldtype not in ("Section Break", "Column Break", "Tab Break")]
		self.assertTrue(meta.quick_entry)
		self.assertEqual(len(editable), 1, "Branch grew fields — reconsider whether its modal still shows them all")
