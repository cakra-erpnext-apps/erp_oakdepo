"""Server-side context for the ESS PWA shell mounted at ``/depot``.

The built Vue entry (``container_depot/public/ess/index.html``) is copied to
``container_depot/www/depot.html`` by the frontend ``copy-html-entry`` build
step. This controller renders that page with the CSRF token + boot context and
enforces auth: a Guest is bounced to the standard Frappe login and returned to
``/depot`` (PRD §3.3 — no custom auth, reuse the Frappe session).
"""

import frappe
from frappe.boot import load_translations

no_cache = 1

# DECIDED (handoff §5.5, 2026-08-06): /depot stays open to every logged-in user, and this
# gate stays a session check. Do NOT add a role check here. What empties the page for
# someone without a field role is `ess.context.get_menu` returning [] — the PWA then shows
# its "no menu for this account" card, which reads as "you lack access" rather than as an
# error, and each API endpoint enforces its own DocPerm regardless (ess/guard.py).
def _require_pwa_access():
	if frappe.session.user == "Guest":
		frappe.throw(
			frappe._("Anda tidak punya akses Depot OAK. Hubungi admin."),
			frappe.PermissionError,
		)


def check_app_permission():
	"""Whether to show "Depot OAK" on the `/apps` chooser (``add_to_apps_screen`` hook).

	Stricter than :func:`_require_pwa_access` on purpose, and that asymmetry is the point:
	the page must stay openable (a bookmark, a link in a chat, the Desk shortcut) while the
	*advertisement* for it should only reach people it is useful to. Offering the tile to
	an office account promises an app that turns out to be empty.

	Keyed on the field-role flag, so it tracks the same checkbox as the PWA menu with no
	deploy and no migrate — tick `Role.is_depot_field_role` and the tile appears.
	"""
	from container_depot.ess.context import has_field_role

	return frappe.session.user != "Guest" and has_field_role()


def get_context(context):
	# Reuse the Frappe session cookie. Unauthenticated -> standard login -> /depot.
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/depot"
		raise frappe.Redirect

	_require_pwa_access()

	context = frappe._dict()
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.boot = get_boot()
	context.site_name = frappe.local.site
	frappe.db.commit()  # nosemgrep — persist the CSRF token issuance
	return context


def get_boot():
	bootinfo = frappe._dict(
		{
			"site_name": frappe.local.site,
			"user": frappe.session.user,
			"default_route": "/depot",
		}
	)
	bootinfo.lang = frappe.local.lang
	load_translations(bootinfo)
	return bootinfo


@frappe.whitelist(methods=["GET", "POST"])
def get_context_for_dev():
	"""Boot context for `vite dev`, where the Jinja page is not rendered.

	Authenticated only (the whitelist already rejects Guest) and gated to
	developer mode, mirroring how hrms serves its dev boot.
	"""
	if not frappe.conf.developer_mode:
		frappe.throw(frappe._("This method is only meant for developer mode."))
	_require_pwa_access()
	return get_boot()
