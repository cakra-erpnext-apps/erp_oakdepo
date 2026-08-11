"""Role Profiles are the assignment UX for the role model — one pick, not three.

The payoff being pinned here is that picking a profile grants the depot role AND its
COMPANION_ROLES together, so the companion can no longer be forgotten when an account is
created. The risk being pinned is the other half of Frappe's behaviour: a profile is
authoritative over a user's roles, so a seeder that "corrected" an admin's additions
would silently revoke access. `setup_role_profiles` is add-only, and that is tested.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot.install import (
	COMPANION_ROLES,
	FIELD_ROLES,
	OFFICE_ROLES,
	STOCK_ROLE_PROFILES,
	setup_role_profiles,
)

USER = "rp-cashier@example.com"
HELD_PROFILE = "RP Test Stock Bundle"
HELD_USER = "rp-held@example.com"
# A throwaway role rather than a real one: these tests bolt it onto a live profile to
# prove the seeder leaves it there, and no depot account should inherit anything from that.
EXTRA_ROLE = "RP Test Extra Role"


def _user(email: str) -> "frappe.Document":
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, ignore_permissions=True, force=True)
	return frappe.get_doc({
		"doctype": "User",
		"email": email,
		"first_name": email.split("@")[0],
		"send_welcome_email": 0,
		"user_type": "System User",
	}).insert(ignore_permissions=True)


class TestRoleProfiles(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		if not frappe.db.exists("Role", EXTRA_ROLE):
			frappe.get_doc({
				"doctype": "Role",
				"role_name": EXTRA_ROLE,
				"desk_access": 1,
			}).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for email in (USER, HELD_USER):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, ignore_permissions=True, force=True)
		if frappe.db.exists("Role Profile", HELD_PROFILE):
			frappe.delete_doc("Role Profile", HELD_PROFILE, ignore_permissions=True, force=True)
		# The add-only test appends a role to a REAL profile. Undo it, or every later run
		# of this suite starts from a dirtier site than the one before.
		if frappe.db.exists("Role Profile", "Security"):
			doc = frappe.get_doc("Role Profile", "Security")
			if any(row.role == EXTRA_ROLE for row in doc.roles):
				doc.roles = [row for row in doc.roles if row.role != EXTRA_ROLE]
				doc.save(ignore_permissions=True)
		frappe.db.delete("Has Role", {"role": EXTRA_ROLE})
		if frappe.db.exists("Role", EXTRA_ROLE):
			frappe.delete_doc("Role", EXTRA_ROLE, ignore_permissions=True, force=True)
		frappe.db.commit()
		super().tearDownClass()

	def test_every_app_role_has_a_profile_with_its_companions(self):
		for role in FIELD_ROLES + OFFICE_ROLES:
			with self.subTest(role=role):
				self.assertTrue(
					frappe.db.exists("Role Profile", role), f"{role} has no Role Profile"
				)
				carried = {
					row.role
					for row in frappe.get_doc("Role Profile", role).roles
				}
				self.assertIn(role, carried)
				for companion in COMPANION_ROLES.get(role, []):
					self.assertIn(
						companion,
						carried,
						f"{role} profile must carry {companion} — that is why it exists",
					)

	def test_stock_bundles_are_retired(self):
		for profile in STOCK_ROLE_PROFILES:
			self.assertFalse(
				frappe.db.exists("Role Profile", profile),
				f"{profile} is an ERPNext/HRMS bundle that maps to no depot job",
			)

	def test_assigning_a_profile_grants_role_and_companion(self):
		"""The point of the whole thing: step 2 and step 3 collapse into one pick."""
		user = _user(USER)
		user.append("role_profiles", {"role_profile": "Cashier"})
		user.save(ignore_permissions=True)

		roles = frappe.get_roles(USER)
		self.assertIn("Cashier", roles)
		self.assertIn("Accounts User", roles, "the companion role must come along for free")

	def test_seeder_never_removes_an_admins_extra_role(self):
		"""Add-only. A profile is authoritative over its users' roles, so a seeder that
		pruned back to the shipped list would revoke access on the next migrate."""
		doc = frappe.get_doc("Role Profile", "Security")
		doc.append("roles", {"role": EXTRA_ROLE})
		doc.save(ignore_permissions=True)

		setup_role_profiles()

		carried = {row.role for row in frappe.get_doc("Role Profile", "Security").roles}
		self.assertIn(EXTRA_ROLE, carried, "migrate must not undo an admin's addition")
		self.assertIn("Security", carried, "…and must still re-assert the app's own role")

	def test_a_stock_bundle_still_held_by_a_user_is_kept(self):
		"""Deleting it would strip that user's roles on their next save, with nothing left
		on the account to reconstruct them from. Report and skip instead."""
		frappe.get_doc({
			"doctype": "Role Profile",
			"role_profile": HELD_PROFILE,
			"roles": [{"role": EXTRA_ROLE}],
		}).insert(ignore_permissions=True)
		user = _user(HELD_USER)
		user.append("role_profiles", {"role_profile": HELD_PROFILE})
		user.save(ignore_permissions=True)

		with patch("container_depot.install.STOCK_ROLE_PROFILES", [HELD_PROFILE]):
			setup_role_profiles()

		self.assertTrue(
			frappe.db.exists("Role Profile", HELD_PROFILE),
			"a profile with holders must survive the sweep",
		)
