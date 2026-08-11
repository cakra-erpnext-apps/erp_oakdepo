"""Where a yard account lands when it opens ERPNext — see ``container_depot/desk_landing.py``.

The bug these pin: a field-role account is a Website User, and ``frappe/www/desk.py`` answers
every Website User with "Not Permitted". Operators were meeting that error as their first
screen after logging in, and the obvious fix — setting the Role's Home Page to ``/depot`` —
cannot work, for two independent reasons this file also pins:

* ``frappe/auth.py`` resolves a Website User's landing through ``get_default_path()``, which
  answers before ``get_home_page()`` (the only reader of ``Role.home_page``) is ever called;
* the login page prefers ``localStorage.last_visited`` over the server's answer entirely, so
  a browser that has ever been on the Desk goes back to the Desk no matter what.

Only the request-hook redirect covers the second one, which is why it exists.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from container_depot import desk_landing

FIELD_USER = "landing-field@example.com"
DESK_USER = "landing-desk@example.com"


def _make_user(email, roles=None, profile=None):
	"""A disposable account, by hand-assigned roles or by Role Profile (the real path)."""
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, force=True, ignore_permissions=True)
	payload = {
		"doctype": "User",
		"email": email,
		"first_name": "Landing Test",
		"user_type": "System User",
		"send_welcome_email": 0,
	}
	if profile:
		payload["role_profiles"] = [{"role_profile": profile}]
	if roles:
		payload["roles"] = [{"role": r} for r in roles]
	return frappe.get_doc(payload).insert(ignore_permissions=True)


class TestLandingLivesOnTheProfile(FrappeTestCase):
	"""The landing page is a property of the JOB, so it lives on the Role Profile.

	Frappe's own ``Role.home_page`` is the thing being replaced, and the reason is not taste:
	``get_home_page`` walks every role a user holds and takes the first home page it finds, so
	putting ``/depot`` on Security also redirects Administrator, who holds every role.
	"""

	@classmethod
	def tearDownClass(cls):
		for email in (FIELD_USER, DESK_USER):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		super().tearDownClass()

	def test_the_shipped_field_profiles_land_on_the_pwa(self):
		from container_depot.install import FIELD_ROLES

		for name in FIELD_ROLES:
			with self.subTest(profile=name):
				self.assertEqual(
					frappe.db.get_value("Role Profile", name, "home_page"), desk_landing.PWA_HOME
				)

	def test_admin_ops_keeps_the_desk_as_its_home(self):
		"""It carries the field-role flag AND desk_access — the ops backstop works both
		surfaces, and a landing page would have to pick one. It keeps the Desk."""
		self.assertFalse(frappe.db.get_value("Role Profile", "Admin Ops", "home_page"))

	def test_office_profiles_have_no_landing_override(self):
		for name in ("Cashier", "Finance", "Commercial", "Warehouse", "Management"):
			with self.subTest(profile=name):
				self.assertFalse(frappe.db.get_value("Role Profile", name, "home_page"))

	def test_the_app_roles_carry_no_home_page(self):
		"""Patch v0_56, pinned. A home page here is not a duplicate of the profile setting —
		it is a leak, because it follows the ROLE onto every account that holds it."""
		from container_depot.install import FIELD_ROLES, OFFICE_ROLES

		leaked = {
			r: frappe.db.get_value("Role", r, "home_page")
			for r in FIELD_ROLES + OFFICE_ROLES
			if frappe.db.exists("Role", r) and frappe.db.get_value("Role", r, "home_page")
		}
		self.assertEqual(leaked, {}, "Role.home_page redirects Administrator too — use the profile")

	def test_a_users_landing_is_seeded_from_their_profile(self):
		_make_user(FIELD_USER, profile="Security")
		self.assertEqual(
			frappe.db.get_value("User", FIELD_USER, "home_page"),
			desk_landing.PWA_HOME,
			"the profile is the default the account is seeded FROM",
		)
		self.assertEqual(desk_landing.home_page_for(FIELD_USER), desk_landing.PWA_HOME)

	def test_the_users_own_value_wins_over_the_profile(self):
		"""The reason the setting is on the user at all: move one person without redefining
		the job for everyone who holds it."""
		_make_user(FIELD_USER, profile="Security")
		frappe.db.set_value("User", FIELD_USER, "home_page", "/depot/monitor", update_modified=False)
		self.assertEqual(desk_landing.home_page_for(FIELD_USER), "/depot/monitor")
		self.assertEqual(
			desk_landing.profile_home_page_for(FIELD_USER),
			desk_landing.PWA_HOME,
			"and the job's default is untouched by that",
		)

	def test_a_users_own_value_is_never_overwritten_on_save(self):
		_make_user(FIELD_USER, profile="Security")
		frappe.db.set_value("User", FIELD_USER, "home_page", "/depot/monitor", update_modified=False)
		frappe.get_doc("User", FIELD_USER).save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("User", FIELD_USER, "home_page"), "/depot/monitor")

	def test_clearing_the_user_value_makes_the_profile_answer_again(self):
		"""How an admin undoes an override — and how re-assigning someone to a different job
		is meant to be finished."""
		_make_user(FIELD_USER, profile="Security")
		frappe.db.set_value("User", FIELD_USER, "home_page", None, update_modified=False)
		self.assertEqual(desk_landing.home_page_for(FIELD_USER), desk_landing.PWA_HOME)

	def test_repointing_a_profile_moves_everyone_still_inheriting(self):
		original = frappe.db.get_value("Role Profile", "Security", "home_page")
		try:
			_make_user(FIELD_USER, profile="Security")
			frappe.db.set_value("User", FIELD_USER, "home_page", None, update_modified=False)
			frappe.db.set_value("Role Profile", "Security", "home_page", "/depot/gate", update_modified=False)
			self.assertEqual(desk_landing.home_page_for(FIELD_USER), "/depot/gate")
		finally:
			frappe.db.set_value("Role Profile", "Security", "home_page", original, update_modified=False)

	def test_an_account_with_no_profile_asks_for_nothing(self):
		_make_user(DESK_USER, roles=["Cashier"])
		self.assertIsNone(desk_landing.home_page_for(DESK_USER))

	def test_an_office_account_is_never_stamped(self):
		"""Only Website Users are seeded. A Desk account has no landing problem to solve."""
		_make_user(DESK_USER, profile="Cashier")
		self.assertFalse(frappe.db.get_value("User", DESK_USER, "home_page"))


class TestPwaDefaultApp(FrappeTestCase):
	"""``User.default_app`` is the one lever ``get_default_path`` checks before guessing."""

	@classmethod
	def tearDownClass(cls):
		for email in (FIELD_USER, DESK_USER):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		super().tearDownClass()

	def test_a_field_account_is_pointed_at_the_pwa_on_save(self):
		user = _make_user(FIELD_USER, ["Security"])
		self.assertEqual(
			user.user_type, "Website User", "a desk_access=0 role is what demotes the account"
		)
		self.assertEqual(
			frappe.db.get_value("User", FIELD_USER, "default_app"),
			desk_landing._app_for_route(desk_landing.PWA_HOME),
			"without this, get_default_path falls through to guessing from the app list",
		)

	def test_the_landing_path_frappe_computes_is_actually_depot(self):
		"""The assertion that matters — the field above only matters through this function."""
		_make_user(FIELD_USER, ["Security"])
		from frappe.apps import get_default_path

		frappe.set_user(FIELD_USER)
		try:
			self.assertEqual(get_default_path(), "/depot")
		finally:
			frappe.set_user("Administrator")

	def test_login_can_only_land_on_an_app_root(self):
		"""The one place a deep home page is NOT honoured, pinned so it stays a known shape.

		``get_default_path`` steers on ``User.default_app`` — an app name — and resolves it to
		that app's root route. A deeper value still governs the Desk redirect, which writes its
		own Location header, but login lands on ``/depot``. Verified over real HTTP too.
		"""
		from frappe.apps import get_default_path

		_make_user(FIELD_USER, profile="Security")
		frappe.db.set_value("User", FIELD_USER, "home_page", "/depot/monitor", update_modified=False)
		frappe.get_doc("User", FIELD_USER).save(ignore_permissions=True)
		frappe.set_user(FIELD_USER)
		try:
			self.assertEqual(get_default_path(), "/depot")
		finally:
			frappe.set_user("Administrator")

	def test_a_desk_account_is_left_alone(self):
		"""Office staff work in the Desk. Sending them to an empty PWA would be the same
		bug pointed the other way."""
		user = _make_user(DESK_USER, ["Cashier"])
		self.assertEqual(user.user_type, "System User")
		self.assertFalse(frappe.db.get_value("User", DESK_USER, "default_app"))

	def test_an_admins_own_choice_is_never_overwritten(self):
		"""Only a BLANK default_app is filled. We supply a missing default; we do not
		enforce a policy over an admin who pointed the account somewhere deliberately."""
		_make_user(FIELD_USER, ["Security"])
		frappe.db.set_value("User", FIELD_USER, "default_app", "helpdesk", update_modified=False)
		user = frappe.get_doc("User", FIELD_USER)
		user.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("User", FIELD_USER, "default_app"), "helpdesk")

	def test_backfill_reaches_accounts_that_predate_the_hook(self):
		_make_user(FIELD_USER, ["Security"])
		frappe.db.set_value("User", FIELD_USER, "default_app", None, update_modified=False)
		desk_landing.backfill_landing_app()
		self.assertEqual(
			frappe.db.get_value("User", FIELD_USER, "default_app"), desk_landing._app_for_route(desk_landing.PWA_HOME)
		)

	def test_backfill_leaves_desk_accounts_alone(self):
		_make_user(DESK_USER, ["Cashier"])
		desk_landing.backfill_landing_app()
		self.assertFalse(frappe.db.get_value("User", DESK_USER, "default_app"))


class TestDeskRedirect(FrappeTestCase):
	"""The guard for every arrival a landing page cannot control."""

	@classmethod
	def tearDownClass(cls):
		for email in (FIELD_USER, DESK_USER):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		super().tearDownClass()

	def _redirect_for(self, path, user, user_type, method="GET"):
		"""Run the hook as ``user`` would hit ``path``; return the raised redirect or None."""
		had_request = hasattr(frappe.local, "request")
		old_request = getattr(frappe.local, "request", None)
		old_type = (frappe.session.data or {}).get("user_type")
		frappe.local.request = frappe._dict(path=path, method=method)
		# AFTER set_user, never before: set_user rebuilds session.data, so injecting the
		# user_type first silently loses it and every redirect assertion passes as a no-op.
		frappe.set_user(user)
		frappe.session.data["user_type"] = user_type
		try:
			desk_landing.redirect_field_users_off_the_desk()
			return None
		except Exception as e:
			return e
		finally:
			frappe.set_user("Administrator")
			frappe.session.data["user_type"] = old_type
			if had_request:
				frappe.local.request = old_request
			else:
				del frappe.local.request

	def test_a_field_account_on_the_desk_is_sent_to_the_pwa(self):
		_make_user(FIELD_USER, ["Security"])
		redirect = self._redirect_for("/desk", FIELD_USER, "Website User")
		self.assertIsNotNone(redirect, "this is the request that used to render Not Permitted")
		self.assertEqual(redirect.new_url, "/depot")

	def test_the_redirect_is_temporary(self):
		"""302, never RequestRedirect's default 308.

		A permanent redirect is cached by the browser, so an operator granted Desk access
		tomorrow would keep being bounced into the PWA by their own machine, with nothing
		left on the server to fix.
		"""
		_make_user(FIELD_USER, ["Security"])
		self.assertEqual(self._redirect_for("/desk", FIELD_USER, "Website User").code, 302)

	def test_the_redirect_target_follows_the_profile(self):
		"""Not a hardcoded /depot: an admin can repoint a job without a deploy, which is the
		whole point of moving the setting out of the code."""
		original = frappe.db.get_value("Role Profile", "Security", "home_page")
		frappe.db.set_value("Role Profile", "Security", "home_page", "/depot/gate", update_modified=False)
		try:
			_make_user(FIELD_USER, profile="Security")
			redirect = self._redirect_for("/desk", FIELD_USER, "Website User")
			self.assertEqual(redirect.new_url, "/depot/gate")
		finally:
			frappe.db.set_value("Role Profile", "Security", "home_page", original, update_modified=False)

	def test_the_redirect_target_follows_the_users_own_override(self):
		"""One operator can be sent somewhere else without touching their colleagues."""
		_make_user(FIELD_USER, profile="Security")
		frappe.db.set_value("User", FIELD_USER, "home_page", "/depot/monitor", update_modified=False)
		self.assertEqual(
			self._redirect_for("/desk", FIELD_USER, "Website User").new_url, "/depot/monitor"
		)

	def test_a_yard_account_with_no_profile_still_reaches_the_pwa(self):
		"""Roles may be assigned by hand, with no profile to inherit from. The fallback is
		what keeps that account off the Not Permitted page — and it is stamped on the user
		like any other value, so the account is not a special case afterwards."""
		_make_user(FIELD_USER, roles=["Security"])
		self.assertIsNone(desk_landing.profile_home_page_for(FIELD_USER), "no profile to ask")
		self.assertEqual(frappe.db.get_value("User", FIELD_USER, "home_page"), desk_landing.PWA_HOME)
		self.assertEqual(
			self._redirect_for("/desk", FIELD_USER, "Website User").new_url, desk_landing.PWA_HOME
		)

	def test_a_deep_desk_link_is_caught_too(self):
		"""The dead end is not only the Desk home — `last_visited` is whatever form the
		browser was last on."""
		_make_user(FIELD_USER, ["Security"])
		for path in ("/desk/booking-code/view/list", "/app/order-muat", "/app"):
			with self.subTest(path=path):
				self.assertIsNotNone(self._redirect_for(path, FIELD_USER, "Website User"))

	def test_a_desk_account_is_never_redirected(self):
		"""Office staff live in the Desk."""
		_make_user(DESK_USER, ["Cashier"])
		self.assertIsNone(self._redirect_for("/desk", DESK_USER, "System User"))

	def test_admin_ops_keeps_the_desk(self):
		"""THE load-bearing negative, and the reason the user_type check exists at all.

		Admin Ops is the one role that is both: ``is_depot_field_role = 1`` *and*
		``desk_access = 1`` (install.PWA_OFFICE_ROLES). A guard keyed on the field-role flag
		alone would look correct and would throw the ops backstop out of the Desk — the
		account that most needs to be in it. Only ``user_type`` separates the two families.
		"""
		self.assertTrue(
			frappe.db.get_value("Role", "Admin Ops", "is_depot_field_role"),
			"premise of this test: Admin Ops is flagged for the PWA",
		)
		user = _make_user(DESK_USER, ["Admin Ops"])
		self.assertEqual(user.user_type, "System User", "Admin Ops keeps desk_access")
		self.assertIsNone(self._redirect_for("/desk", DESK_USER, "System User"))

	def test_a_website_user_with_no_field_role_gets_frappes_own_answer(self):
		"""A portal user who wandered into the Desk is a misconfiguration, not a yard
		worker. Redirecting them would hide it; Frappe's permission error names it."""
		_make_user(DESK_USER, ["Cashier"])
		self.assertIsNone(self._redirect_for("/desk", DESK_USER, "Website User"))

	def test_paths_outside_the_desk_are_untouched(self):
		"""The hook runs on EVERY request. It must not touch the PWA or its API."""
		_make_user(FIELD_USER, ["Security"])
		for path in ("/depot", "/depot/gate", "/api/method/container_depot.ess.context.get_menu",
		             "/assets/container_depot/ess/index.js", "/desktop-notes", "/login"):
			with self.subTest(path=path):
				self.assertIsNone(self._redirect_for(path, FIELD_USER, "Website User"))

	def test_writes_are_never_redirected(self):
		"""A POST that answered with a 302 would silently drop the body."""
		_make_user(FIELD_USER, ["Security"])
		self.assertIsNone(self._redirect_for("/desk", FIELD_USER, "Website User", method="POST"))

	def test_no_request_is_not_a_crash(self):
		"""before_request also runs where there is no HTTP request at all (bench, workers)."""
		had_request = hasattr(frappe.local, "request")
		old_request = getattr(frappe.local, "request", None)
		if had_request:
			del frappe.local.request
		try:
			self.assertIsNone(desk_landing.redirect_field_users_off_the_desk())
		finally:
			if had_request:
				frappe.local.request = old_request
