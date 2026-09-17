"""A Link picker on a depot form opens for anyone the form itself is open to.

Access to depot work is decided once, by the DocPerm on the form. A picker that demands a
SECOND role on the linked doctype gates the same decision twice, and fails as a 403 inside a
form the user was told they may use: `Insufficient Permission for Currency` on Depot Contract
(Admin Ops holds no Accounts/Sales/Purchase role), then the same for `Branch`, with `Employee`,
`User`, `Role` and `Warehouse` queued up behind them (2026-09-16).

`setup_permissions` therefore sweeps every doctype a Container Depot form links to and grants
`select` to `All`. This pins both halves: the pickers open, and `select` did not quietly turn
into `read` — Custom DocPerm defaults `read` and `export` to 1, so the grant has to spell every
flag out.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.install import META_PERM_DOCTYPES, _link_targets


def _external_targets() -> list[str]:
	"""Linked doctypes the sweep is responsible for (child tables inherit their parent)."""
	out = []
	for target in sorted(_link_targets()):
		if not frappe.db.exists("DocType", target):
			continue
		meta = frappe.get_meta(target)
		if meta.istable or meta.module == "Container Depot":
			continue
		out.append(target)
	return out


class TestLinkSelect(FrappeTestCase):
	def test_every_linked_doctype_is_selectable_without_a_role(self):
		"""The picker is open to `All`, so no companion role is needed to fill the field."""
		blocked = [
			dt
			for dt in _external_targets()
			if not any(p.role == "All" and (p.get("select") or p.get("read")) for p in frappe.get_meta(dt).permissions)
		]
		self.assertEqual(blocked, [], f"link pickers still gated behind a role: {blocked}")

	def test_the_grant_is_select_only(self):
		"""`select` means "may be chosen in a Link field" and nothing else — the list view,
		report view and export of a linked doctype stay shut. Guards the Custom DocPerm
		field defaults, which hand out `read` and `export` unless told otherwise."""
		leaked = []
		for dt in _external_targets():
			for perm in frappe.get_all(
				"Custom DocPerm",
				filters={"parent": dt, "role": "All"},
				fields=["parent", "select", "read", "report", "export", "write"],
			):
				if perm.select and (perm.read or perm.report or perm.export or perm.write):
					leaked.append(perm.parent)
		self.assertEqual(leaked, [], f"select grant carried more than select: {leaked}")

	def test_the_targets_include_the_fields_that_broke(self):
		"""Regression pin for the two reported 403s and the sweep that found the rest."""
		targets = _link_targets()
		for dt in ("Currency", "Branch", "Employee", "User", "Warehouse"):
			self.assertIn(dt, targets)

	def test_doctypes_frappe_ignores_custom_perms_for_are_left_alone(self):
		"""`Meta.set_custom_permissions` skips these by name, so a row written for them is
		never consulted — writing one anyway would be a grant that silently does nothing."""
		self.assertFalse(_link_targets() & META_PERM_DOCTYPES)
