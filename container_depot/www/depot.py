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


def get_context(context):
	# Reuse the Frappe session cookie. Unauthenticated -> standard login -> /depot.
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/depot"
		raise frappe.Redirect

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
	return get_boot()
