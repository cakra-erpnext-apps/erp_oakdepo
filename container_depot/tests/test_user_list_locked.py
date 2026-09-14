"""Depot roles never hold `read` or `write` on the `User` doctype.

Checked 2026-09-14 when the question "can a depot role reach the user list?" came up. The
answer measured on the site: they hold no role permission on `User` at all — only the
standard `Desk User` role's bare `select`, which is what makes every User link field (Assign
To, Customer Portal User, Share, Notification recipients) work. That `select` does let the
list view render names, and the user decided to keep it rather than break every picker.

What this pins is the part that IS a lock: no depot role may read a User record's contents,
and no depot account may open somebody else's profile. Worth a test because the FIRST Custom
DocPerm written on a doctype makes Frappe ignore its shipped permissions wholesale (see
install.setup_permissions) — `User` already carries such rows, so one more added by hand, or
by a seeder that stopped scoping itself to module=Container Depot, would silently rewrite the
whole matrix instead of adding to it.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.install import FIELD_ROLES, OFFICE_ROLES

USER = "user-list-lock@example.com"
DEPOT_ROLES = FIELD_ROLES + OFFICE_ROLES


class TestUserListLocked(FrappeTestCase):
	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		if frappe.db.exists("User", USER):
			frappe.delete_doc("User", USER, ignore_permissions=True, force=True)
		frappe.db.commit()
		super().tearDownClass()

	def test_no_depot_role_holds_a_permission_on_the_user_doctype(self):
		for role in DEPOT_ROLES:
			for table in ("DocPerm", "Custom DocPerm"):
				for ptype in ("read", "write", "create", "delete"):
					with self.subTest(role=role, table=table, ptype=ptype):
						self.assertFalse(
							frappe.db.exists(table, {"parent": "User", "role": role, ptype: 1}),
							f"{role} must not hold {ptype} on User ({table})",
						)

	def test_an_admin_ops_account_cannot_open_another_users_profile(self):
		"""The real lock: the list may render names, a record may not be opened."""
		if frappe.db.exists("User", USER):
			frappe.delete_doc("User", USER, ignore_permissions=True, force=True)
		user = frappe.get_doc({
			"doctype": "User",
			"email": USER,
			"first_name": "User List Lock",
			"send_welcome_email": 0,
			"user_type": "System User",
		}).insert(ignore_permissions=True)
		user.append("role_profiles", {"role_profile": "Admin Ops"})
		user.save(ignore_permissions=True)
		self.assertIn("Admin Ops", frappe.get_roles(USER))

		frappe.set_user(USER)
		try:
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc("User", "Administrator").check_permission("read")
		finally:
			frappe.set_user("Administrator")
