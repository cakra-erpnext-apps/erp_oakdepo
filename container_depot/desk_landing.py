"""Where a yard user lands when they open ERPNext.

A field-role account carries ``desk_access = 0``, which makes ``User.set_system_user`` flip
its ``user_type`` to **Website User**. Frappe then resolves that account's landing page
through ``frappe.apps.get_default_path`` — and this is the trap:

    frappe/auth.py::set_user_info
        if user_type == "Website User":
            home_page = get_default_path() or "/" + get_home_page()

``get_default_path()`` answers first and usually answers *something*, so ``get_home_page()``
— the only function that reads **Role.home_page** — is never called. Setting a role's Home
Page to ``/depot`` therefore looks like the fix and is silently ignored. Worse, when the
apps visible to that account are all Desk-routed, ``get_default_path`` returns ``"/desk"``,
and ``frappe/www/desk.py`` throws ``PermissionError`` at every Website User. The operator's
first screen after logging in is **Not Permitted**, with no way out.

Two guards, because a login is not the only way to arrive at that wall:

1. :func:`remember_landing_app` stamps ``User.default_app``, which ``get_default_path``
   consults *before* any of its app-count guesswork. That makes the login landing
   deterministic instead of a function of how many apps happen to be visible.

2. :func:`redirect_field_users_off_the_desk` catches every other arrival — a bookmark, a
   shared handset with ``/desk`` still in the address bar, a ``?redirect-to=/desk`` carried
   through the login form — and sends it to ``/depot`` instead of the error page.

WHERE THE DESTINATION COMES FROM
--------------------------------
Two custom fields, a default and the value in force:

    Role Profile.home_page   the default for the JOB     ("/depot" on the seven field profiles)
    User.home_page           the value for the PERSON    (seeded from the profile on save)

:func:`home_page_for` reads the user's, then falls back to the profile's. That split is what
lets one person be moved without redefining the job, and a job be redefined without chasing
every account that holds it.

**Neither is Frappe's ``Role.home_page``.** A Role is a permission object, and
``website/utils.py::get_home_page`` walks every role a user holds and takes the first home page
it finds — so putting ``/depot`` on Security also redirects Administrator, who holds every
role. Patch ``v0_56`` clears it off the app's roles for exactly that reason.

Why guard 2 is a request hook and not a page renderer: ``PathResolver.resolve`` short-circuits
``/desk`` to a hardcoded ``TemplatePage`` **before** it consults ``website_redirects`` or the
``page_renderer`` hook (frappe/website/path_resolver.py, "WARN: Hardcoded for better
performance"). ``before_request`` is the last point at which the path is still interceptable.

Both guards read the same ``Role.is_depot_field_role`` flag as the PWA menu, so a role added
from the Desk tomorrow is covered with no deploy — and neither grants anything. A user who
reaches ``/depot`` this way still meets ``ess/guard.py`` on every endpoint.
"""

from __future__ import annotations

import frappe

from container_depot.ess.context import has_field_role

# Fallback landing for a yard account whose profile says nothing — a user may legitimately
# hold no Role Profile and be assigned roles by hand (see STRUCTURE.md, "Assigning a user").
PWA_HOME = "/depot"

# Prefixes that lead to the Desk. Frappe serves the Desk at /desk in this version and keeps
# /app as a legacy alias; both dead-end identically for a Website User, so both are caught.
_DESK_PREFIXES = ("/desk", "/app")


def home_page_for(user: str) -> str | None:
	"""Where this user lands: their own ``home_page``, else their profile's default, else None.

	Two records, two jobs. ``Role Profile.home_page`` is the **default for the job** — change
	it and every account that has not been given a value of its own follows. ``User.home_page``
	is the **value in force for this person** — set it and that one account moves without
	redefining the job. :func:`remember_landing_app` seeds the second from the first on save,
	so in practice the user field is the one that answers.

	**Neither is Frappe's ``Role.home_page``**, and that is the point. A Role is a permission
	object, and ``website/utils.py::get_home_page`` walks every role a user holds and takes the
	first home page it finds — so putting ``/depot`` on one field role also redirects
	Administrator, who holds them all. See patch v0_56.
	"""
	if not user or user == "Guest":
		return None
	own = frappe.db.get_value("User", user, "home_page")
	if own:
		return own
	return profile_home_page_for(user)


def profile_home_page_for(user: str) -> str | None:
	"""The default their Role Profile carries, ignoring anything set on the user.

	First non-blank wins if an account somehow carries several profiles — deterministic order
	beats an arbitrary one, and a user is meant to hold exactly one.
	"""
	names = frappe.get_all(
		"User Role Profile",
		filters={"parenttype": "User", "parent": user},
		pluck="role_profile",
		order_by="idx",
	)
	for name in names:
		home = frappe.db.get_value("Role Profile", name, "home_page")
		if home:
			return home
	return None


def _app_for_route(route: str) -> str | None:
	"""The installed app whose ``add_to_apps_screen`` route is ``route``.

	KNOWN LIMIT, and it is Frappe's, not ours. ``get_default_path`` — the only thing that
	decides a Website User's landing at login — steers on ``User.default_app``, an app NAME,
	which it resolves through ``get_route()`` to that app's ROOT route. There is no lever for
	an arbitrary path.

	So a home page of ``/depot`` is honoured everywhere, while a deeper one like
	``/depot/monitor`` is honoured by the Desk redirect (which controls its own Location
	header) but **not by login**, which lands on ``/depot``. Pinned by
	``test_login_can_only_land_on_an_app_root``, so the boundary is a documented shape rather
	than a surprise. Closing it would mean the PWA reading a start route of its own.
	"""
	if not route:
		return None
	for app in frappe.get_installed_apps():
		for detail in frappe.get_hooks("add_to_apps_screen", app_name=app) or []:
			if detail.get("route") == route:
				return app
	return None


def remember_landing_app(doc, method=None):
	"""Seed this account's own ``home_page`` from its profile, and point login at it.

	Runs on every User save so a profile change is picked up immediately — assigning the
	profile is exactly the moment the account becomes a Website User.

	Both writes fill a **blank** field only, never overwrite. An admin who moved one person
	keeps that; the profile is a default, not a policy re-imposed on every save. Two
	consequences worth knowing:

	* re-pointing a **profile** moves everyone who has not been given a value of their own,
	  and only them;
	* re-assigning a **person** to a different job does NOT move their landing page — their
	  own value is already set. Clear ``User.home_page`` to make them inherit again.
	"""
	if doc.user_type != "Website User":
		return
	home = _seed_user_home_page(doc.name, doc.get("home_page"))
	if doc.get("default_app"):
		return
	app = _app_for_route(home)
	if not app:
		return
	# Value-only write: this runs inside the User's own on_update and must not re-enter
	# validation or bump the timestamp of a document the admin just saved.
	frappe.db.set_value("User", doc.name, "default_app", app, update_modified=False)


def _seed_user_home_page(user: str, current: str | None) -> str | None:
	"""Copy the profile default onto the user once, and return the value now in force."""
	if current:
		return current
	# PWA_HOME covers a yard account assigned roles by hand, with no profile to inherit from.
	home = profile_home_page_for(user) or (PWA_HOME if has_field_role(user) else None)
	if home:
		frappe.db.set_value("User", user, "home_page", home, update_modified=False)
	return home


def backfill_landing_app():
	"""Seed ``home_page`` / ``default_app`` on accounts that predate :func:`remember_landing_app`.

	Called from ``after_migrate``. Idempotent, and deliberately narrow: only blank fields are
	filled, so re-running it can never move an account an admin has since pointed elsewhere.
	"""
	users = frappe.get_all(
		"User",
		filters={"user_type": "Website User", "enabled": 1},
		fields=["name", "home_page", "default_app"],
	)
	for user in users:
		if user.name == "Guest":
			continue
		home = _seed_user_home_page(user.name, user.home_page)
		if user.default_app:
			continue
		app = _app_for_route(home)
		if app:
			frappe.db.set_value("User", user.name, "default_app", app, update_modified=False)


def redirect_field_users_off_the_desk():
	"""Send a yard account that lands on /desk to /depot instead of "Not Permitted".

	Registered as a ``before_request`` hook. Kept deliberately cheap: it reads the session
	that ``init_request`` has already built and only asks about roles once the path and the
	user type have both already matched, which is a handful of requests per shift.

	Never redirects an account that holds Desk access. A Website User is, by definition,
	someone Frappe would refuse at ``/desk`` anyway, so this replaces a dead end and takes
	nothing away.
	"""
	request = getattr(frappe.local, "request", None)
	if request is None or request.method not in ("GET", "HEAD"):
		return

	path = (request.path or "").rstrip("/")
	if not any(path == p or path.startswith(p + "/") for p in _DESK_PREFIXES):
		return

	user = getattr(frappe.session, "user", None)
	if not user or user == "Guest":
		# Frappe's own "log in to continue" redirect is the right answer here, and it
		# preserves the requested path so the operator resumes where they meant to be.
		return

	# `frappe.session.data.user_type` is the same field frappe/www/desk.py refuses on, and
	# it is already in memory — no query to decide the common case (a Desk user, who is
	# never redirected).
	if (frappe.session.data or {}).get("user_type") != "Website User":
		return

	if not has_field_role(user):
		# Not a yard account. Frappe's permission error is the honest answer for a portal
		# user who wandered into the Desk; inventing a redirect would hide a real misconfig.
		return

	# The profile says where this job belongs; PWA_HOME is the fallback for a yard account
	# assigned roles by hand, with no profile to ask.
	raise _temporary_redirect(home_page_for(user) or PWA_HOME)


def _temporary_redirect(location: str):
	"""A 302 to ``location``, as an exception ``frappe/app.py`` already knows how to render.

	``werkzeug.routing.RequestRedirect`` is an ``HTTPException``, so ``application()`` turns
	it into a real response — unlike ``frappe.Redirect``, which ``handle_exception`` has no
	branch for and would render as "Server Error".

	The code is forced to **302**. RequestRedirect defaults to 308 (permanent), which
	browsers cache: an operator later granted Desk access would keep being bounced to the
	PWA by their own browser, with nothing on the server left to fix.
	"""
	from werkzeug.routing import RequestRedirect

	redirect = RequestRedirect(location)
	redirect.code = 302
	return redirect
