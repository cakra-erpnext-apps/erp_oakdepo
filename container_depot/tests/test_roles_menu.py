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
	"Admin Ops": "rm-adminops@example.com",
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
# The /desk home tile. Named for the label because Desktop Icon is autonamed field:label.
PWA_ICON = "Depot OAK (Mobile)"


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
		for forbidden in ("gate", "eir", "mr", "periodicTest", "surveyPos", "posFix"):
			self.assertNotIn(forbidden, self._menu_as(USERS["Team Cleaning"]))

	def test_spv_gets_all_menus(self):
		self.assertEqual(self._menu_as(USERS["SPV Lapangan"]), set(MENU_KEYS))
		self.assertEqual(len(MENU_KEYS), 8)

	def test_office_role_gets_empty_menu(self):
		# Cashier holds real DocPerms (Container read, Gate Entry read) but no field role,
		# so /depot opens and stays empty. This is what replaces a "Depot PWA" role.
		frappe.set_user(USERS["Cashier"])
		try:
			self.assertFalse(has_field_role())
			self.assertEqual(allowed_menu(), [])
		finally:
			frappe.set_user("Administrator")

	def test_admin_ops_works_both_surfaces(self):
		"""Admin Ops is the one office role that is also a PWA role.

		The two flags are independent, and this pins that: `is_depot_field_role` opens
		/depot without `desk_access` being sacrificed. Losing either half is a silent
		regression — an Admin Ops with an empty PWA looks like a permission bug, and one
		locked out of /app looks like a broken login.

		The menu is every tile rather than a curated subset because Admin Ops holds
		DocPerm on every depot doctype (§8.2) and the menu is derived from DocPerm. If that
		is ever unwanted, the fix is the DocPerms, not a menu allow-list.
		"""
		frappe.set_user(USERS["Admin Ops"])
		try:
			self.assertTrue(has_field_role())
			self.assertTrue(has_desk_access(), "Admin Ops must keep the Desk")
			self.assertEqual(set(allowed_menu()), set(MENU_KEYS))
		finally:
			frappe.set_user("Administrator")

		flags = frappe.db.get_value(
			"Role", "Admin Ops", ["is_depot_field_role", "desk_access"], as_dict=True
		)
		self.assertEqual((flags.is_depot_field_role, flags.desk_access), (1, 1))

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

	def test_container_depot_menus_do_not_advertise_the_pwa(self):
		"""The Container Depot sidebar and workspace carry no /depot entry at all.

		Removed 2026-08-11: the /desk **home tile** (Desktop Icon "Depot OAK (Mobile)", the
		Raven-style App icon covered by the next test) already puts the PWA one click from
		the landing screen, so the sidebar row and the workspace Shortcut card were two extra
		doors to the same app.

		Asserted for a field-role user — the account that USED to see both. Anyone else seeing
		them was already impossible, so proving their absence for the one user who qualified
		proves it for everybody.

		The guard matters because of how the entries would come back. A ``link_type: URL``
		row is the obvious way to re-add one and the wrong one: Frappe's ``is_item_allowed``
		waves every URL item through unconditionally, so it would show to every Desk user
		including office staff whose PWA is empty. That is why the removed entries pointed at
		the ``depot-pwa`` Page — it owns a ``roles`` table and IS filtered. Re-add through the
		Page or not at all.

		The probe carries System Manager: without Desk access there is no sidebar to read.
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
			{"sidebar": False, "shortcut": False, "apps_tile": True},
			"the Desk menus are clean; the /apps tile is the surviving pointer",
		)
		self.assertFalse(
			_surfaces(DESK_USERS["Cashier"])["apps_tile"],
			"office staff are never pointed at a PWA that would be empty for them",
		)

	def test_pwa_page_stays_shut_to_office_staff(self):
		"""``/app/depot-pwa`` itself is still role-gated, now that no menu leads to it.

		With the sidebar row and the Shortcut card gone, the Page's ``roles`` table is no
		longer decorating a menu — it is the only thing standing between an old bookmark and
		an office user staring at an empty PWA. ``install.setup_pwa_page_roles`` keeps it
		equal to the roles carrying ``is_depot_field_role``, so an empty table here would
		read as "everyone" and silently open the page to the whole Desk.
		"""
		roles = set(frappe.get_all("Has Role", filters={"parenttype": "Page", "parent": PWA_PAGE}, pluck="role"))
		self.assertTrue(roles, "an empty roles table means EVERYONE — the wrong way to fail")
		flagged = set(frappe.get_all("Role", filters={"is_depot_field_role": 1}, pluck="name"))
		# Subset, not equality: the sync runs on migrate, so a role flagged mid-suite (or
		# mid-session by an admin) is legitimately not on the page yet. What must never
		# happen is the reverse — a role on the page that does not carry the flag, which is
		# how an office account would quietly acquire the door.
		self.assertLessEqual(
			roles, flagged, "every role on the page carries the flag; none was hand-added"
		)

	def test_desk_home_icon_survives_a_blocked_module(self):
		"""The /desk home tile for the PWA must not depend on Container Depot module access.

		Allow Modules governs the Desk. The PWA is a different surface, so an operator whose
		Allow Modules omits Container Depot — a perfectly reasonable setup for someone who
		only works the yard — must still find their way to /depot from the Desk home.

		That is the whole reason the shipped icon is ``icon_type: App`` rather than a Link to
		the workspace: ``DesktopIcon.is_permitted`` resolves a module (and honours the block)
		only for Link icons, and dispatches App icons to the owning app's
		``add_to_apps_screen.has_permission`` hook instead. The two icons under the same block
		are asserted together because the contrast IS the behaviour.
		"""
		# A Link icon also disappears when its sidebar is empty, so hand is_permitted a
		# populated one — otherwise a False below would prove nothing about the block.
		bootinfo = frappe._dict({
			"workspace_sidebar_item": {"container depot": {"items": [{"type": "Link"}]}}
		})

		def _icons_for(email, blocked):
			user = frappe.get_doc("User", email)
			user.set("block_modules", [{"module": m} for m in blocked])
			user.save(ignore_permissions=True)
			frappe.clear_cache(user=email)
			frappe.set_user(email)
			try:
				return {
					name: bool(frappe.get_doc("Desktop Icon", name).is_permitted(bootinfo))
					for name in (PWA_ICON, "Container Depot")
				}
			finally:
				frappe.set_user("Administrator")

		field_user = DESK_USERS["Team Cleaning"]
		self.assertEqual(
			_icons_for(field_user, []),
			{PWA_ICON: True, "Container Depot": True},
			"baseline: nothing blocked, both tiles show",
		)
		self.assertEqual(
			_icons_for(field_user, ["Container Depot"]),
			{PWA_ICON: True, "Container Depot": False},
			"blocking the module hides the workspace tile and only that one",
		)
		self.assertFalse(
			_icons_for(DESK_USERS["Cashier"], [])[PWA_ICON],
			"office staff still get no PWA tile — the hook gate is unchanged",
		)

	def test_parking_a_role_hides_it_without_unassigning_anyone(self):
		"""The mechanism behind patch v0_54, pinned because the obvious alternative is a trap.

		``Role.disabled`` looks equivalent and is not: ``Role.validate`` sends it to
		``remove_roles()``, which DELETES every Has Role row for that role, and unticking the
		box does not restore them. Tagging ``restrict_to_domain`` with a domain that is not
		active hides the role from the User form's picker and leaves assignments alone.

		Tested on a throwaway role rather than on the parked list itself: an admin un-parking
		one of those is a legitimate act, not a regression.
		"""
		from frappe.core.doctype.user.user import get_all_roles

		from container_depot.install import PARKED_DOMAIN, _ensure_parked_domain

		_ensure_parked_domain()
		if not frappe.db.exists("Role", AD_HOC_ROLE):
			frappe.get_doc({
				"doctype": "Role",
				"role_name": AD_HOC_ROLE,
				"desk_access": 1,
			}).insert(ignore_permissions=True)
		_user(AD_HOC_USER, [AD_HOC_ROLE])
		frappe.db.commit()

		self.assertIn(AD_HOC_ROLE, get_all_roles())
		self.assertEqual(frappe.db.count("Has Role", {"role": AD_HOC_ROLE}), 1)

		frappe.db.set_value("Role", AD_HOC_ROLE, "restrict_to_domain", PARKED_DOMAIN)
		self.assertNotIn(AD_HOC_ROLE, get_all_roles(), "parked role must leave the picker")
		self.assertEqual(
			frappe.db.count("Has Role", {"role": AD_HOC_ROLE}),
			1,
			"parking must NOT unassign anyone — that is the whole reason we avoid `disabled`",
		)
		self.assertIn(AD_HOC_ROLE, frappe.get_roles(AD_HOC_USER))

		frappe.db.set_value("Role", AD_HOC_ROLE, "restrict_to_domain", None)
		self.assertIn(AD_HOC_ROLE, get_all_roles(), "un-parking is one field, no re-assignment")

	def test_parked_domain_is_never_activated(self):
		"""Activating the `Unused` domain would put all ~48 parked roles back on screen."""
		from container_depot.install import PARKED_DOMAIN

		self.assertNotIn(PARKED_DOMAIN, frappe.get_active_domains())

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
