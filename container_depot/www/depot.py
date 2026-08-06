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

# NOTE (2026-08-05): the page used to require the "Depot PWA" role. That role was
# removed with the rest of the custom role model, pending a redesign, so the only gate
# left here is the session itself — any logged-in user may open the PWA. Reattach the
# role check at :func:`_require_pwa_access` once the new roles exist; the individual
# API endpoints keep enforcing their own DocPerms either way.
def _require_pwa_access():
	if frappe.session.user == "Guest":
		frappe.throw(
			frappe._("Anda tidak punya akses Depot OAK. Hubungi admin."),
			frappe.PermissionError,
		)


def check_app_permission():
	"""Whether to show "Depot OAK" on the `/apps` chooser (``add_to_apps_screen`` hook).

	Same gate as :func:`_require_pwa_access` — keep the two in step when the role model
	comes back, so the switcher never offers a tile that then bounces the user.
	"""
	return frappe.session.user != "Guest"


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
