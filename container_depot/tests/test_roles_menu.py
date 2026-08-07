"""The PWA menu is derived from DocPerms, never from a role list.

Every test runs as a real, non-Administrator user. Administrator bypasses permissions
entirely in Frappe, so a permission test that runs as Administrator passes no matter how
broken the rules are — it proves nothing.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.ess.context import (
	MENU_KEYS,
	allowed_menu,
	has_desk_access,
	has_field_role,
)

# One user per role under test. Kept apart from real accounts by the domain.
USERS = {
	"Team Cleaning": "rm-cleaning@example.com",
	"Team Survey": "rm-survey@example.com",
	"Team Kalmar": "rm-kalmar@example.com",
	"SPV Lapangan": "rm-spv@example.com",
	"Cashier": "rm-cashier@example.com",
}
AD_HOC_ROLE = "RM Test Field Role"
AD_HOC_USER = "rm-adhoc@example.com"

# Same two roles again, but paired with System Manager so the accounts actually reach the
# Desk. Needed only by the Desk-shortcut test: a field role alone carries desk_access = 0,
# and a user who cannot open the Desk has no sidebar to check.
DESK_USERS = {
	"Team Cleaning": "rm-desk-cleaning@example.com",
	"Cashier": "rm-desk-cashier@example.com",
}
PWA_PAGE = "depot-pwa"


def _user(email: str, roles: list) -> None:
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, ignore_permissions=True, force=True)
	doc = frappe.get_doc({
		"doctype": "User",
		"email": email,
		"first_name": email.split("@")[0],
		"send_welcome_email": 0,
		# System User, not Website User: a Website User cannot hold arbitrary roles, and
		# the field roles carry desk_access = 0 which is what keeps them out of /app.
		"user_type": "System User",
	}).insert(ignore_permissions=True)
	doc.add_roles(*roles)


class TestRoleMenu(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		for role, email in USERS.items():
			_user(email, [role])
		for role, email in DESK_USERS.items():
			_user(email, [role, "System Manager"])
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for email in list(USERS.values()) + list(DESK_USERS.values()) + [AD_HOC_USER]:
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, ignore_permissions=True, force=True)
		frappe.db.delete("Custom DocPerm", {"role": AD_HOC_ROLE})
		if frappe.db.exists("Role", AD_HOC_ROLE):
			frappe.delete_doc("Role", AD_HOC_ROLE, ignore_permissions=True, force=True)
		frappe.db.commit()
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def _menu_as(self, email: str) -> set:
		frappe.set_user(email)
		try:
			return set(allowed_menu())
		finally:
			frappe.set_user("Administrator")

	def test_field_role_gets_only_its_menu(self):
		# Its own worklist, plus the read-only yard browser. `monitor` keys on Container
		# READ, which §8.1 grants to every field role because every worklist shows
		# container data — so the Monitor tile follows. Withholding it would mean taking
		# Container read away, which breaks the doc-level has_permission checks in
		# ess/repairs.py and ess/documents.py. Cosmetics are not worth that.
		self.assertEqual(self._menu_as(USERS["Team Cleaning"]), {"cleaning", "monitor"})
		# What matters is the negative: no gate, no EIR, no M&R, no survey.
		for forbidden in ("gate", "readyOut", "eir", "mr", "periodicTest", "surveyPos", "posFix"):
			self.assertNotIn(forbidden, self._menu_as(USERS["Team Cleaning"]))

	def test_spv_gets_all_menus(self):
		self.assertEqual(self._menu_as(USERS["SPV Lapangan"]), set(MENU_KEYS))
		self.assertEqual(len(MENU_KEYS), 9)

	def test_office_role_gets_empty_menu(self):
		# Cashier holds real DocPerms (Container read, Gate Entry read) but no field role,
		# so /depot opens and stays empty. This is what replaces a "Depot PWA" role.
		frappe.set_user(USERS["Cashier"])
		try:
			self.assertFalse(has_field_role())
			self.assertEqual(allowed_menu(), [])
		finally:
			frappe.set_user("Administrator")

	def test_desk_shortcut_follows_desk_access(self):
		"""The PWA's "Buka Desk" link is offered to office staff and withheld from the field.

		Exactly inverts the field-role split: office roles carry desk_access = 1, field roles
		desk_access = 0 (install.ensure_roles_exist). Cashier lands on the empty PWA and
		needs the way out; Team Cleaning would only be sent to a wall.
		"""
		frappe.set_user(USERS["Cashier"])
		try:
			self.assertTrue(has_desk_access())
			self.assertEqual(allowed_menu(), [], "office staff: Desk yes, PWA menu no")
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(USERS["Team Cleaning"])
		try:
			self.assertFalse(has_desk_access())
			self.assertTrue(allowed_menu(), "field staff: PWA menu yes, Desk no")
		finally:
			frappe.set_user("Administrator")

	def test_pwa_shortcut_hidden_from_desk_users_without_a_field_role(self):
		"""The Desk-side shortcuts to /depot reach only accounts that hold a field role.

		Covers all three surfaces at once, because they are one decision expressed three
		times: the sidebar entry, the workspace Shortcut card, and the /apps tile. The first
		two are filtered by the ``depot-pwa`` Page's roles table (seeded from
		``Role.is_depot_field_role`` by install.setup_pwa_page_roles), the third by
		``www.depot.check_app_permission``.

		This is what a plain ``link_type: URL`` row could not do — Frappe's
		``is_item_allowed`` waves every URL item through, so the shortcut showed to every
		Desk user including office staff with no PWA menu at all.

		Both probes carry System Manager: without Desk access there is no sidebar to test.
		"""
		from frappe.boot import get_sidebar_items
		from frappe.desk.desktop import Workspace

		from container_depot.boot import warm_domain_restricted_caches
		from container_depot.www.depot import check_app_permission

		workspaces = frappe.get_all("Workspace", pluck="name")

		def _surfaces(email):
			frappe.set_user(email)
			try:
				# Frappe reads these caches without a lazy build; unwarmed they are None and
				# is_item_allowed raises. The real request path warms them in before_request.
				warm_domain_restricted_caches()
				sidebar = get_sidebar_items(workspaces).get("container depot") or {}
				workspace = Workspace({"name": "Container Depot"})
				workspace.build_workspace()
				return {
					"sidebar": any(i.get("link_to") == PWA_PAGE for i in sidebar.get("items", [])),
					"shortcut": any(
						s.get("link_to") == PWA_PAGE for s in workspace.shortcuts["items"]
					),
					"apps_tile": bool(check_app_permission()),
				}
			finally:
				frappe.set_user("Administrator")

		self.assertEqual(
			_surfaces(DESK_USERS["Team Cleaning"]),
			{"sidebar": True, "shortcut": True, "apps_tile": True},
			"a field role that also reaches the Desk gets the shortcut everywhere",
		)
		self.assertEqual(
			_surfaces(DESK_USERS["Cashier"]),
			{"sidebar": False, "shortcut": False, "apps_tile": False},
			"office staff are never pointed at a PWA that would be empty for them",
		)

	def test_survey_vs_posfix_split(self):
		# One doctype, two menus, split on write vs submit.
		survey = self._menu_as(USERS["Team Survey"])
		kalmar = self._menu_as(USERS["Team Kalmar"])
		self.assertIn("surveyPos", survey)
		self.assertNotIn("posFix", survey)
		self.assertIn("posFix", kalmar)
		self.assertNotIn("surveyPos", kalmar)

	def test_new_role_needs_no_code_change(self):
		# The whole point of the checkbox: an admin adds a role in the UI, grants it a
		# DocPerm, and its users get the matching menu. No deploy, no edit to _MENU.
		frappe.get_doc({
			"doctype": "Role",
			"role_name": AD_HOC_ROLE,
			"desk_access": 0,
			"is_depot_field_role": 1,
		}).insert(ignore_permissions=True)
		frappe.get_doc({
			"doctype": "Custom DocPerm",
			"parent": "Cleaning Order",
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": AD_HOC_ROLE,
			"permlevel": 0,
			"read": 1,
			"write": 1,
		}).insert(ignore_permissions=True)
		_user(AD_HOC_USER, [AD_HOC_ROLE])
		frappe.db.commit()
		frappe.clear_cache()

		# Only Cleaning Order was granted, so no Container read and hence no monitor tile.
		self.assertEqual(self._menu_as(AD_HOC_USER), {"cleaning"})
